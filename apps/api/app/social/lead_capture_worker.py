"""Minute repair sweep plus durable queued history reads; exclusively GET upstream."""

import threading
from time import monotonic

from fastapi import HTTPException

from ..crm.database import connect
from ..inbox.models import Execute, validate
from . import lead_capture as capture

_stop = threading.Event()
_wake = threading.Event()
_thread = None
_heartbeat = 0.0
_error = None
LOCK = 9142071


def read(credentials, account, operation, query=None, path=None):
    command, args = validate(
        Execute(operation=operation, account_id=account, query=query or {}, path=path or {}),
        credentials,
    )
    if command["method"] != "GET":
        raise ValueError("capture_read_only")
    result = capture.inbox_provider.request(credentials, command, args)
    return capture.inbox_service.scope_result(result, account)


def page(result, key, previous=None):
    rows = result.get(key)
    if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(r, dict) for r in rows):
        raise ValueError("capture_invalid_page")
    meta = result.get("meta") or {}
    if not isinstance(meta, dict) or meta.get("accountsFailed") or meta.get("accountsSkipped"):
        raise ValueError("capture_partial_page")
    pagination = result.get("pagination") or {}
    if not isinstance(pagination, dict):
        raise TypeError("capture_invalid_cursor")
    cursor = pagination.get("nextCursor") or pagination.get("cursor")
    if pagination.get("hasMore") is False:
        cursor = None
    if pagination.get("hasMore") is True and not cursor:
        raise ValueError("capture_missing_cursor")
    if cursor is not None and (
        not isinstance(cursor, str) or len(cursor) > 4000 or cursor == previous
    ):
        raise ValueError("capture_repeated_cursor")
    return rows, cursor


def scopes(platform):
    for status in ("active", "archived"):
        for folder in ("inbox", "requests") if platform == "facebook" else (None,):
            yield (
                status + ":" + (folder or "all"),
                {"status": status, **({"folder": folder} if folder else {})},
            )


def sweep(db, credentials, account):
    profile, aid = credentials["profile_id"], account["id"]
    for scope, filters in scopes(account["platform"]):
        db.execute(
            "INSERT INTO crm.lead_capture_scans(profile_id,account_id,scope) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (profile, aid, scope),
        )
        saved = db.execute(
            "SELECT cursor FROM crm.lead_capture_scans WHERE profile_id=%s AND account_id=%s AND scope=%s",
            (profile, aid, scope),
        ).fetchone()
        db.commit()
        try:
            query = {"platform": account["platform"], "limit": 100, "sortOrder": "desc", **filters}
            if saved["cursor"]:
                query["cursor"] = saved["cursor"]
            result = read(credentials, aid, "listInboxConversations", query)
            rows, cursor = page(result, "data", saved["cursor"])
            for row in rows:
                if row.get("accountId") != aid or row.get("platform") != account["platform"]:
                    raise ValueError("capture_scope_mismatch")
                if not capture.remember(db, profile, row):
                    raise ValueError("capture_identity_changed")
            db.execute(
                "UPDATE crm.lead_capture_scans SET cursor=%s,last_success=now(),last_error=NULL WHERE profile_id=%s AND account_id=%s AND scope=%s",
                (cursor, profile, aid, scope),
            )
            db.commit()
        except Exception:  # noqa: BLE001 - safe finite diagnostics, no upstream body/PII
            db.rollback()
            db.execute(
                "UPDATE crm.lead_capture_scans SET last_error='capture_sweep_failed' WHERE profile_id=%s AND account_id=%s AND scope=%s",
                (profile, aid, scope),
            )
            db.commit()


def tick(sweep_accounts=True):
    global _heartbeat, _error
    if not capture.enabled():
        return
    credentials = capture.config.required()
    if not sweep_accounts:
        with connect() as probe:
            due = probe.execute(
                """SELECT 1 FROM crm.lead_capture_threads WHERE profile_id=%s
                   AND account_id=ANY(%s) AND checked_marker IS DISTINCT FROM observed_marker
                   AND next_attempt<=now() LIMIT 1""",
                (credentials["profile_id"], list(capture.ACCOUNTS)),
            ).fetchone()
        if not due:
            _heartbeat = monotonic()
            return
    with connect() as access:
        capture.require_connections(access, "zernio")
    accounts = capture.inbox_service.accounts(credentials)
    accounts = {
        a["id"]: a
        for a in accounts
        if a["active"] and capture.ACCOUNTS.get(a["id"]) == a["platform"]
    }
    with connect() as db:
        # Session lock survives per-lead commits and releases on connection close/crash.
        if not db.execute("SELECT pg_try_advisory_lock(%s) AS held", (LOCK,)).fetchone()["held"]:
            return
        db.commit()
        account_error = (
            "capture_account_unavailable" if set(capture.ACCOUNTS) - set(accounts) else None
        )
        for aid, account in list(accounts.items()):
            try:
                capture.require_connections(db, "zernio", account["platform"])
            except HTTPException:
                accounts.pop(aid)
                account_error = "capture_channel_disabled"
        db.commit()
        if sweep_accounts:
            for account in accounts.values():
                sweep(db, credentials, account)
                _heartbeat = monotonic()
        pending = db.execute(
            """SELECT * FROM crm.lead_capture_threads WHERE profile_id=%s
               AND account_id=ANY(%s) AND checked_marker IS DISTINCT FROM observed_marker
               AND next_attempt<=now() ORDER BY next_attempt,updated_at LIMIT 20""",
            (credentials["profile_id"], list(accounts)),
        ).fetchall()
        db.commit()
        for saved in pending:
            if threading.current_thread() is _thread and _stop.is_set():
                break
            key = (saved["profile_id"], saved["account_id"], saved["conversation_id"])
            try:
                query = {"sortOrder": "desc", "limit": 100}
                if saved["scan_cursor"]:
                    query["cursor"] = saved["scan_cursor"]
                result = read(
                    credentials,
                    saved["account_id"],
                    "getInboxConversationMessages",
                    query,
                    {"conversationId": saved["conversation_id"]},
                )
                messages, cursor = page(result, "messages", saved["scan_cursor"])
                row = {
                    "id": saved["conversation_id"],
                    "accountId": saved["account_id"],
                    "platform": saved["platform"],
                    "participantId": saved["participant_id"],
                    "participantName": saved["participant_name"],
                }
                capture.ingest(
                    db,
                    saved["profile_id"],
                    row,
                    messages,
                    complete=cursor is None,
                    cursor=cursor,
                    expected_marker=saved["observed_marker"],
                )
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                db.execute(
                    "UPDATE crm.lead_capture_threads SET reason='capture_read_failed',attempts=attempts+1,next_attempt=now()+interval '60 seconds' WHERE profile_id=%s AND account_id=%s AND conversation_id=%s",
                    key,
                )
                db.commit()
            _heartbeat = monotonic()
        _heartbeat, _error = monotonic(), account_error


def status():
    with connect() as db:
        profile = capture.config.load()
        profile = profile["profile_id"] if profile else ""
        counts = db.execute(
            """SELECT count(*) FILTER(WHERE status='registered') AS registered,
               count(*) FILTER(WHERE status='pending') AS pending,
               count(*) FILTER(WHERE reason='capture_read_failed') AS failed
               FROM crm.lead_capture_threads WHERE profile_id=%s AND account_id=ANY(%s)""",
            (profile, list(capture.ACCOUNTS)),
        ).fetchone()
        scans = db.execute(
            "SELECT account_id,scope,last_success,last_error FROM crm.lead_capture_scans WHERE profile_id=%s AND account_id=ANY(%s)",
            (profile, list(capture.ACCOUNTS)),
        ).fetchall()
    return {
        "enabled": capture.enabled(),
        "worker_alive": bool(_thread and _thread.is_alive() and monotonic() - _heartbeat < 120),
        "interval_seconds": 60,
        "last_error": _error,
        **counts,
        "scans": scans,
    }


def _loop():
    global _heartbeat, _error
    last_sweep = -60.0
    while not _stop.is_set():
        try:
            due = monotonic() - last_sweep >= 60
            tick(sweep_accounts=due)
            if due:
                from . import template_cohorts

                try:
                    template_cohorts.tick()
                except Exception:  # noqa: BLE001, S110 - independent GET-only attribution repair
                    pass
                last_sweep = monotonic()
        except Exception:  # noqa: BLE001 - retry reads only; never log contacts or credentials
            _error = "capture_unavailable"
            _heartbeat = 0
        _wake.wait(5)
        _wake.clear()
    _heartbeat = 0


def wake():
    _wake.set()


def start():
    global _thread
    if capture.enabled() and (_thread is None or not _thread.is_alive()):
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="crm-lead-capture", daemon=True)
        _thread.start()


def stop():
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=2)
