"""Explicitly authorized fixed automatic reads; never broker approvals or provider writes."""

import json
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from threading import BoundedSemaphore, Lock
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from ..control import service as control
from ..crm.database import connect
from . import models, service

TTL = 30
MAX_KEYS = 128
_slots = BoundedSemaphore(3)
_queue_slots = BoundedSemaphore(33)
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retell-read")
_lock = Lock()
_cache = OrderedDict()
_flights = {}


def clear_cache():
    """Clear completed process-local snapshots, primarily for isolated tests."""
    with _lock:
        _cache.clear()


def cache_size():
    with _lock:
        return len(_cache) + len(_flights)


@contextmanager
def _slot():
    if not _slots.acquire(timeout=0.5):
        raise HTTPException(429, "retell_read_busy")
    try:
        yield
    finally:
        _slots.release()


def _current(db, admin, version=None):
    live = db.execute(
        """SELECT u.id FROM crm.sessions s JOIN crm.users u ON u.id=s.user_id
        WHERE s.token_hash=%s AND u.id=%s AND u.enabled AND u.role='admin'
          AND s.expires_at>now() AND s.last_seen>now()-interval '30 minutes'""",
        (admin["token_hash"], admin["id"]),
    ).fetchone()
    if not live:
        raise HTTPException(401, "authentication_required")
    pref = db.execute(
        "SELECT enabled,version FROM crm.control_connections WHERE key='retell'"
    ).fetchone()
    if not pref or not pref["enabled"]:
        raise HTTPException(409, "connection_disabled")
    if version is not None and pref["version"] != version:
        raise HTTPException(409, "connection_changed")
    return pref["version"]


def _watermark(db, admin):
    reads = [key for key, row in service.registry().items() if row["risk"] == "read"]
    row = db.execute(
        """SELECT count(*) AS completed,max(p.created_at) AS newest
        FROM crm.hermes_proposals p WHERE p.actor_id=%s AND p.session_hash=%s
          AND p.action='retell.execute' AND p.status='approved'
          AND p.result->>'provider'='retell' AND p.result->>'status'='completed'
          AND NOT (p.arguments->>'endpoint'=ANY(%s))""",
        (admin["id"], admin["token_hash"], reads),
    ).fetchone()
    # Count also detects a previously created proposal completing out of order.
    return row["completed"], row["newest"]


def _reviewed(endpoint):
    if endpoint not in models.AUTOMATIC_READ_ENDPOINTS:
        raise HTTPException(422, "retell_automatic_read_denied")
    operation = service.operation(endpoint)
    if operation["risk"] != "read" or operation["available"] is not True:
        raise HTTPException(422, "retell_automatic_read_denied")


def _verify(revision, admin, version=None, watermark=None):
    with connect() as db:
        current = _current(db, admin, version)
    with _slot():
        service.require_state(revision)
    with connect() as db:
        _current(db, admin, current)
        if watermark is not None and _watermark(db, admin) != watermark:
            raise HTTPException(409, "retell_inventory_changed")
    return current


def _metadata_timeout(deadline):
    # Existing provider-state checks have their own 3s transport timeout.
    remaining = deadline - monotonic() - 3
    if remaining <= 0:
        raise HTTPException(503, "retell_read_timeout")
    return min(1.5, remaining)


def _execute_timeout(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise HTTPException(503, "retell_read_timeout")
    return min(8, remaining)


def read(data, admin, *, connection_version=None, deadline=None):
    _reviewed(data.endpoint)
    try:
        return _read(data, admin, connection_version=connection_version, deadline=deadline)
    except HTTPException as error:
        if error.detail in {
            "authentication_required",
            "connection_disabled",
            "connection_changed",
            "retell_provider_changed",
            "retell_schema_changed",
            "retell_read_timeout",
            "retell_automatic_read_denied",
            "retell_read_busy",
            "retell_unavailable",
            "retell_schema_unavailable",
        }:
            raise
        raise HTTPException(503, "retell_read_unavailable") from None
    except Exception:  # noqa: BLE001 - never reflect arbitrary transport errors
        raise HTTPException(503, "retell_read_unavailable") from None


def _read(data, admin, *, connection_version=None, deadline=None):
    """One fixed reviewed read, with schema binding and before/after state checks."""
    _reviewed(data.endpoint)  # Deny arbitrary endpoints BEFORE any provider call.
    deadline = min(deadline or monotonic() + 18, monotonic() + 18)
    if deadline <= monotonic():
        raise HTTPException(503, "retell_read_timeout")
    args = models.Execute(endpoint=data.endpoint, arguments=data.arguments)
    with _slot():
        with connect() as db:
            version = _current(db, admin, connection_version)
            revision, digest = service.preflight(
                db, args, data.revision, timeout=_metadata_timeout(deadline)
            )
            row = {
                "id": uuid4(),
                "revisions": {
                    "provider:retell": revision,
                    "retell:schema_hash": digest,
                    "retell:requires_consent": False,
                    "retell:risk": "read",
                },
            }
            payload = service.prepare(
                db, row, args, admin, False, timeout=_metadata_timeout(deadline)
            )
            _reviewed(data.endpoint)
            _current(db, admin, version)
            metadata = {
                "endpoint": data.endpoint,
                "provider_revision": revision,
                "connection_version": version,
            }
            control.audit(db, admin, "retell.automatic_read", {**metadata, "stage": "prepared"})
        # The audit commits before external dispatch. No proposal is created or approved.
        try:
            result = service.execute_reserved(payload, admin, timeout=_execute_timeout(deadline))
            if (
                result.get("provider") != "retell"
                or result.get("status") != "completed"
                or result.get("endpoint") != data.endpoint
            ):
                raise HTTPException(503, "retell_read_unavailable")
            sanitized = service.safe_result(result["data"])
            if len(json.dumps(sanitized, allow_nan=False).encode()) > 16384:
                raise ValueError("result_too_large")
            with connect() as db:
                _current(db, admin, version)
                _, current_digest = service.preflight(
                    db, args, revision, timeout=_metadata_timeout(deadline)
                )
                if current_digest != digest:
                    raise HTTPException(409, "retell_schema_changed")
                _reviewed(data.endpoint)
                _current(db, admin, version)
                control.audit(
                    db, admin, "retell.automatic_read", {**metadata, "stage": "completed"}
                )
            return {
                "provider": "retell",
                "status": "completed",
                "endpoint": data.endpoint,
                "data": sanitized,
            }
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - never disclose raw provider/serialization errors
            raise HTTPException(503, "retell_read_unavailable") from None


def _submit(function, *args, **kwargs):
    if not _queue_slots.acquire(blocking=False):
        future = Future()
        future.set_exception(HTTPException(429, "retell_read_busy"))
        return future
    try:
        future = _pool.submit(function, *args, **kwargs)
    except BaseException:
        _queue_slots.release()
        raise
    future.add_done_callback(lambda done: _queue_slots.release())
    return future


def _inventory_rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise HTTPException(503, "retell_read_unavailable")


def _test_case_inventory(revision, admin, version, snapshots, deadline):
    # Retell requires an engine type AND its identifier; there is no global list.
    _reviewed("listTestCaseDefinitions")
    sources = []
    for endpoint, kind, key in (
        ("listRetellLLM", "retell-llm", "llm_id"),
        ("listConversationFlows", "conversation-flow", "conversation_flow_id"),
    ):
        if endpoint not in snapshots:
            raise HTTPException(503, "retell_read_unavailable")
        for row in _inventory_rows(snapshots[endpoint]["data"]):
            if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]:
                raise HTTPException(503, "retell_read_unavailable")
            arguments = {"type": kind, key: row[key]}
            if arguments not in sources:
                sources.append(arguments)
    items = []
    # Inventory is explicitly partial; cap linked contexts as well as provider rows.
    for arguments in sources[:10]:
        result = read(
            models.AutomaticRead(
                revision=revision, endpoint="listTestCaseDefinitions", arguments=arguments
            ),
            admin,
            connection_version=version,
            deadline=deadline,
        )
        items.extend(_inventory_rows(result["data"]))
    return {"data": service.safe_result({"items": items})}


def _collect(revision, admin, version, seed):
    snapshots = {row["endpoint"]: row for row in seed.get("snapshots", [])}
    pending = [
        endpoint
        for endpoint in models.INVENTORY_ENDPOINTS
        if endpoint not in snapshots and endpoint != "listTestCaseDefinitions"
    ]
    deadline = monotonic() + 64
    work = {
        endpoint: _submit(
            read,
            models.AutomaticRead(revision=revision, endpoint=endpoint, arguments={}),
            admin,
            connection_version=version,
            deadline=deadline,
        )
        for endpoint in pending
    }
    errors = []
    for endpoint, future in work.items():
        try:
            result = future.result(timeout=max(0, deadline - monotonic()))
            snapshots[endpoint] = {
                "endpoint": endpoint,
                "provider_revision": revision,
                "created_at": datetime.now(UTC).isoformat(),
                "data": result["data"],
            }
        except TimeoutError:
            future.cancel()
            errors.append({"endpoint": endpoint, "code": "retell_read_timeout"})
        except Exception:  # noqa: BLE001 - bounded codes only, never provider exception text
            errors.append({"endpoint": endpoint, "code": "retell_read_unavailable"})
    if "listTestCaseDefinitions" not in snapshots:
        endpoint = "listTestCaseDefinitions"
        future = _submit(_test_case_inventory, revision, admin, version, snapshots, deadline)
        try:
            result = future.result(timeout=max(0, deadline - monotonic()))
            snapshots[endpoint] = {
                "endpoint": endpoint,
                "provider_revision": revision,
                "created_at": datetime.now(UTC).isoformat(),
                "data": result["data"],
            }
        except TimeoutError:
            future.cancel()
            errors.append({"endpoint": endpoint, "code": "retell_read_timeout"})
        except Exception:  # noqa: BLE001 - never expose provider data
            errors.append({"endpoint": endpoint, "code": "retell_read_unavailable"})
    return {
        "snapshots": [
            snapshots[endpoint] for endpoint in models.INVENTORY_ENDPOINTS if endpoint in snapshots
        ],
        "partial": True,
        "errors": errors,
    }


def synchronize(data, admin):
    """One bounded inventory load; same-key callers share a single in-process flight."""
    with connect() as db:
        version = _current(db, admin)
        watermark = _watermark(db, admin)
    key = (str(admin["id"]), admin["token_hash"], version, data.revision, watermark)
    seed = {}
    cached = None
    seed_expiry = None
    with _lock:
        now = monotonic()
        for old_key in list(_cache):
            if _cache[old_key][0] <= now:
                del _cache[old_key]
        entry = _cache.get(key)
        if entry:
            _cache.move_to_end(key)
            # A new explicit load retries missing resources once, retaining good snapshots.
            seed = deepcopy(entry[1])
            retained = []
            for row in seed["snapshots"]:
                try:
                    _reviewed(row["endpoint"])
                    retained.append(row)
                except HTTPException:
                    seed["errors"].append(
                        {"endpoint": row["endpoint"], "code": "retell_read_unavailable"}
                    )
            seed["snapshots"] = retained
            if not seed["errors"]:
                cached = deepcopy(seed)
            seed_expiry = entry[0]
        future = _flights.get(key)
        owner = future is None and cached is None
        if owner:
            _cache.pop(key, None)
            while len(_cache) + len(_flights) >= MAX_KEYS and _cache:
                _cache.popitem(last=False)
            if len(_flights) >= MAX_KEYS:
                raise HTTPException(429, "retell_read_busy")
            future = Future()
            _flights[key] = future
    if cached is not None:
        # Never hold the cache lock over a database or gateway call.
        for row in cached["snapshots"]:
            _reviewed(row["endpoint"])
        _verify(data.revision, admin, version, watermark)
        return {**cached, "cached": True}
    if not owner:
        try:
            result = future.result(timeout=70)
        except TimeoutError:
            raise HTTPException(503, "retell_read_timeout") from None
        _verify(data.revision, admin, version, watermark)
        return {**deepcopy(result), "cached": True}
    try:
        result = _collect(data.revision, admin, version, seed)
        _verify(data.revision, admin, version, watermark)
        with _lock:
            expiry = seed_expiry if seed_expiry is not None else monotonic() + TTL
            _cache[key] = (expiry, deepcopy(result))
            _flights.pop(key, None)
            future.set_result(deepcopy(result))
        return {**result, "cached": False}
    except BaseException as error:
        with _lock:
            _flights.pop(key, None)
            future.set_exception(error)
        raise
