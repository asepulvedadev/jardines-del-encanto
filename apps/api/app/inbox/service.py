"""Account-scoped reads and persisted, actor-bound, one-shot confirmed actions."""

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control.service import require_connections
from ..crm.database import connect
from ..social import config
from ..social import provider as social_provider
from . import provider
from .models import Execute, validate


def enabled():
    with connect() as db:
        require_connections(db, "zernio")


def accounts(credentials):
    result, cursor, seen = [], None, set()
    # Bounded pagination, never silently treat a partial account list as complete.
    for _ in range(10):
        query = {"profileId": credentials["profile_id"], "limit": 100}
        if cursor:
            query["cursor"] = cursor
        data = social_provider.request(credentials, "GET", "/v1/accounts?" + urlencode(query))
        rows = data.get("accounts")
        if not isinstance(rows, list):
            raise HTTPException(502, "inbox_accounts_invalid")
        for row in rows:
            if (
                not isinstance(row, dict)
                or social_provider.identifier(row.get("profileId")) != credentials["profile_id"]
            ):
                continue
            identifier = social_provider.identifier(row)
            if (
                not isinstance(identifier, str)
                or not 1 <= len(identifier) <= 160
                or identifier in seen
            ):
                raise HTTPException(502, "inbox_accounts_invalid")
            seen.add(identifier)
            result.append(
                {
                    "id": identifier,
                    "platform": social_provider.text(row.get("platform"), 40),
                    "name": social_provider.text(
                        row.get("displayName") or row.get("username") or identifier, 200
                    ),
                    "active": row.get("isActive") is True
                    and row.get("needsReconnection") is not True,
                }
            )
        page = data.get("pagination") or {}
        next_cursor = page.get("nextCursor")
        if not next_cursor and page.get("hasMore") is not True:
            return result
        if not isinstance(next_cursor, str) or next_cursor == cursor:
            break
        cursor = next_cursor
    raise HTTPException(502, "inbox_accounts_incomplete")


def account(credentials, identifier):
    selected = [
        item for item in accounts(credentials) if item["id"] == identifier and item["active"]
    ]
    if len(selected) != 1:
        raise HTTPException(409, "inbox_account_unavailable")
    # Existing channel preferences still govern any implemented social connection.
    if selected[0]["platform"] in social_provider.PLATFORMS:
        with connect() as db:
            require_connections(db, "zernio", selected[0]["platform"])
    return selected[0]


def scope_result(result, identifier):
    # Reject account-bearing records from another tenant, including partial results.
    def visit(value):
        if isinstance(value, dict):
            if "accountId" in value and value["accountId"] != identifier:
                raise HTTPException(502, "inbox_scope_mismatch")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result


def read(command):
    enabled()
    credentials = config.required()
    operation, args = validate(command, credentials)
    if operation["method"] != "GET":
        raise HTTPException(422, "inbox_read_only")
    account(credentials, command.account_id)
    return scope_result(provider.request(credentials, operation, args), command.account_id)


def context(credentials, account_id, args):
    identifier = args["path"].get("conversationId")
    if not identifier:
        return {}
    operation, query = validate(
        Execute(
            operation="getInboxConversation",
            account_id=account_id,
            path={"conversationId": identifier},
        ),
        credentials,
    )
    result = provider.request(credentials, operation, query)
    row = result.get("data")
    if (
        not isinstance(row, dict)
        or row.get("accountId") != account_id
        or not row.get("participantId")
    ):
        raise HTTPException(502, "inbox_scope_mismatch")
    return {
        key: row.get(key) for key in ("participantId", "participantName", "platform", "accountId")
    }


def prepare(command, admin):
    enabled()
    credentials = config.required()
    operation, args = validate(command, credentials)
    if operation["method"] == "GET":
        raise HTTPException(422, "inbox_write_required")
    selected = account(credentials, command.account_id)
    target = context(credentials, command.account_id, args)
    identifier = uuid4()
    with connect() as db:
        # Bounded preparation rate without making any external write.
        count = db.execute(
            "SELECT count(*) AS n FROM crm.inbox_actions WHERE actor_id=%s AND created_at>now()-interval '1 minute'",
            (admin["id"],),
        ).fetchone()["n"]
        if count >= 30:
            raise HTTPException(429, "inbox_rate_limited")
        db.execute(
            "INSERT INTO crm.inbox_actions (id,actor_id,profile_id,account_id,account_label,generation_hash,operation,arguments,context) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                identifier,
                admin["id"],
                credentials["profile_id"],
                command.account_id,
                selected["name"],
                fingerprint(credentials),
                command.operation,
                Jsonb(args),
                Jsonb(target),
            ),
        )
    return action(identifier, admin)


def fingerprint(credentials):
    return hashlib.sha256(
        (credentials.get("generation", "") + credentials["api_key"]).encode()
    ).hexdigest()


def action(identifier, admin):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM crm.inbox_actions WHERE id=%s AND actor_id=%s", (identifier, admin["id"])
        ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    return {k: v for k, v in row.items() if k not in {"actor_id", "generation_hash"}}


def history(admin):
    with connect() as db:
        return {
            "items": db.execute(
                "SELECT id,operation,account_label,state,error,created_at,completed_at FROM crm.inbox_actions WHERE actor_id=%s ORDER BY created_at DESC,id DESC LIMIT 100",
                (admin["id"],),
            ).fetchall()
        }


def confirm(identifier, admin):
    enabled()
    # Rotation cannot replace a key midway through an explicitly confirmed write.
    with config.locked():
        credentials = config.required()
        plan = action(identifier, admin)
        with connect() as db:
            internal = db.execute(
                "SELECT generation_hash FROM crm.inbox_actions WHERE id=%s AND actor_id=%s",
                (identifier, admin["id"]),
            ).fetchone()
        if (
            plan["state"] != "prepared"
            or plan["expires_at"] <= datetime.now(UTC)
            or plan["profile_id"] != credentials["profile_id"]
            or internal["generation_hash"] != fingerprint(credentials)
        ):
            raise HTTPException(409, "inbox_action_stale")
        account(credentials, plan["account_id"])
        operation, args = validate(
            Execute(
                operation=plan["operation"], account_id=plan["account_id"], **plan["arguments"]
            ),
            credentials,
        )
        current_context = context(credentials, plan["account_id"], args)
        if any(
            current_context.get(key) != plan["context"].get(key)
            for key in ("participantId", "accountId", "platform")
        ):
            raise HTTPException(409, "inbox_action_stale")
        with connect() as db:
            row = db.execute(
                "UPDATE crm.inbox_actions SET state='sending' WHERE id=%s AND actor_id=%s AND state='prepared' AND expires_at>now() RETURNING id",
                (identifier, admin["id"]),
            ).fetchone()
            if not row:
                raise HTTPException(409, "inbox_action_stale")
        # Reservation is committed BEFORE network IO. Crash/timeout is never replayed.
        result, error, state = None, None, "sent"
        try:
            result = scope_result(
                provider.request(credentials, operation, args, key=str(identifier)),
                plan["account_id"],
            )
        except HTTPException as cause:
            error = cause.detail if isinstance(cause.detail, str) else "inbox_delivery_unknown"
            state = (
                "unknown"
                if error in {"inbox_delivery_unknown", "inbox_scope_mismatch"}
                else "rejected"
            )
        with connect() as db:
            db.execute(
                "UPDATE crm.inbox_actions SET state=%s,error=%s,completed_at=now() WHERE id=%s AND state='sending'",
                (state, error, identifier),
            )
        return {"id": identifier, "state": state, "error": error, "result": result}


def templates(account_id):
    from ..campaigns import reviews

    enabled()
    credentials = config.required()
    selected = account(credentials, account_id)
    if selected["platform"] != "whatsapp":
        raise HTTPException(422, "inbox_input_invalid")
    result = reviews.request(
        credentials,
        "GET",
        "/v1/whatsapp/templates?" + urlencode({"accountId": account_id, "status": "APPROVED"}),
    )
    items = result.get("templates")
    if not isinstance(items, list) or len(items) > 100:
        raise HTTPException(502, "inbox_provider_unavailable")
    return {
        "items": provider.scrub(
            [item for item in items if isinstance(item, dict) and item.get("status") == "APPROVED"],
            credentials,
        ),
        "pagination": result.get("pagination"),
    }
