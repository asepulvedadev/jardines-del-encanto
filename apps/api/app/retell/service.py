"""Shared Retell policy. External dispatch happens only after broker reservation commits."""

import json
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from ..crm.database import connect
from . import bridge, models

UNAVAILABLE = {
    "available": False,
    "configured": False,
    "verified": False,
    "revision": 0,
    "key_suffix": None,
    "defaults": models.Defaults().model_dump(),
}
OUTREACH = frozenset({"createPhoneCall", "createSmsChat", "createBatchCall"})


@lru_cache(maxsize=1)
def registry():
    """Load only the packaged, reviewed registry; never trust remote risk labels."""
    try:
        value = json.loads(Path(__file__).with_name("registry.json").read_text())
        if not isinstance(value, dict) or not value:
            raise ValueError
        return {
            key: models.Operation.model_validate(row).model_dump(exclude_none=True)
            for key, row in value.items()
            if row.get("endpoint") == key
        }
    except (OSError, ValueError, TypeError, AttributeError, ValidationError):
        raise HTTPException(503, "retell_registry_unavailable") from None


def operation(endpoint):
    row = registry().get(endpoint)
    if not row:
        raise HTTPException(422, "retell_operation_unreviewed")
    if not row["available"]:
        raise HTTPException(422, row.get("blocked_reason") or "retell_operation_unavailable")
    return row


def requires_consent(endpoint):
    return operation(endpoint)["risk"] != "read"


def state():
    try:
        value = models.GatewayState.model_validate(bridge.request("/state")).model_dump()
        return {**value, "available": True}
    except (HTTPException, ValidationError, ValueError, TypeError):
        return {**UNAVAILABLE}


def settings(db):
    pref = db.execute("SELECT enabled FROM crm.control_connections WHERE key='retell'").fetchone()
    return {**state(), "enabled": bool(pref and pref["enabled"])}


def require_state(revision=None):
    value = state()
    if not value["available"] or not value["configured"] or not value["verified"]:
        raise HTTPException(503, "retell_unavailable")
    if revision is not None and value["revision"] != revision:
        raise HTTPException(409, "retell_provider_changed")
    return value


def configure(data, admin, disconnect=False):
    from ..control import service as control

    with connect() as db:
        control.lock(db)
        body = {"revision": data.revision}
        if not disconnect:
            if data.defaults is not None:
                body["defaults"] = data.defaults.model_dump()
            if data.api_key is not None:
                body["api_key"] = data.api_key.get_secret_value()
        try:
            result = models.GatewayState.model_validate(
                bridge.request("/disconnect" if disconnect else "/configure", body, timeout=65)
            ).model_dump()
        except (ValidationError, ValueError, TypeError):
            raise HTTPException(503, "retell_unavailable") from None
        db.execute(
            "UPDATE crm.control_connections SET enabled=CASE WHEN %s THEN false ELSE enabled END,version=version+1 WHERE key='retell'",
            (disconnect,),
        )
        control.audit(
            db,
            admin,
            "retell.disconnect" if disconnect else "retell.configure",
            {"revision": result["revision"]},
        )
        pref = db.execute(
            "SELECT enabled FROM crm.control_connections WHERE key='retell'"
        ).fetchone()
    return {**result, "available": True, "enabled": bool(pref and pref["enabled"])}


def catalog(db, revision=None):
    value = settings(db)
    if revision is not None and value["revision"] != revision:
        raise HTTPException(409, "retell_provider_changed")
    if not value["available"] or not value["configured"] or not value["verified"]:
        return {
            **value,
            "operations": list(registry().values()),
            "new_operations": [],
            "registry_revision": "local-reviewed",
        }
    require_state(revision)
    try:
        result = models.Catalog.model_validate(
            bridge.request("/catalog", {"revision": value["revision"]}, timeout=65)
        ).model_dump(exclude_none=True)
        if result["revision"] != value["revision"]:
            raise HTTPException(409, "retell_provider_changed")
        approved = registry()
        for row in result["operations"]:
            if row != approved.get(row["endpoint"]):
                raise ValueError
        # Discovery may name future operations, but cannot grant executable capability.
        discovered = []
        for row in result["new_operations"]:
            if isinstance(row.get("endpoint"), str) and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9]{0,79}", row["endpoint"]
            ):
                discovered.append(
                    {
                        "endpoint": row["endpoint"],
                        "available": False,
                        "blocked_reason": "unreviewed_operation",
                    }
                )
        return {**value, **result, "new_operations": discovered}
    except (ValidationError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "retell_catalog_unavailable") from None


def schema(db, args):
    """Return the full reviewed schema to the settings UI, or compact paging to Sara."""
    operation(args.endpoint)
    provider = require_state(getattr(args, "revision", None))
    try:
        result = bridge.request(
            "/schema", {"revision": provider["revision"], "endpoint": args.endpoint}, timeout=65
        )
        if (
            result.get("revision") != provider["revision"]
            or result.get("endpoint") != args.endpoint
            or not re.fullmatch(r"[0-9a-f]{64}", result.get("schema_hash", ""))
            or not isinstance(result.get("input_schema"), dict)
        ):
            raise ValueError
        metadata = models.Operation.model_validate(result["metadata"]).model_dump(exclude_none=True)
        if metadata != operation(args.endpoint):
            raise ValueError
        if isinstance(args, models.SchemaBrowse):
            return {
                "endpoint": args.endpoint,
                "schema_hash": result["schema_hash"],
                **schema_page(result["input_schema"], args),
            }
        return {
            "revision": provider["revision"],
            "endpoint": args.endpoint,
            "schema_hash": result["schema_hash"],
            "metadata": metadata,
            "input_schema": result["input_schema"],
        }
    except (ValidationError, TypeError, ValueError, KeyError):
        raise HTTPException(503, "retell_schema_unavailable") from None


def schema_page(source, args):
    """One JSON Pointer level at a time; never inject a 200KB vendor schema into chat."""
    node = source
    if args.path:
        try:
            for segment in args.path.lstrip("/").split("/"):
                key = segment.replace("~1", "/").replace("~0", "~")
                node = node[int(key)] if isinstance(node, list) else node[key]
        except (KeyError, IndexError, ValueError, TypeError):
            raise HTTPException(422, "retell_schema_path_invalid") from None
    if not isinstance(node, dict):
        raise HTTPException(422, "retell_schema_path_invalid")
    props = node.get("properties", {})
    if not isinstance(props, dict):
        props = {}
    names = list(props)
    fields = []
    for name in names[args.offset : args.offset + 16]:
        field = props[name]
        if not isinstance(field, dict):
            continue
        escaped = name.replace("~", "~0").replace("/", "~1")
        row = {
            "name": name[:120],
            "path": args.path + "/properties/" + escaped,
            "required": name in node.get("required", []),
            "type": str(field.get("type", "composite"))[:80],
            "description": str(field.get("description", ""))[:220],
        }
        if isinstance(field.get("enum"), list):
            row["enum"] = [str(x)[:100] for x in field["enum"][:10]]
        if len(json.dumps(fields + [row]).encode()) > 10500:
            break
        fields.append(row)
    next_offset = args.offset + len(fields) if args.offset + len(fields) < len(names) else None
    return {
        "path": args.path,
        "fields": fields,
        "total": len(names),
        "next_offset": next_offset,
        "branches": [key for key in ("items", "oneOf", "anyOf", "allOf") if key in node],
    }


def destinations(args):
    if args.endpoint not in OUTREACH:
        if args.contacts:
            raise HTTPException(422, "retell_contacts_unexpected")
        return []
    body = args.arguments.get("requestBody", {})
    if not isinstance(body, dict) or body.get("ignore_e164_validation") is True:
        raise HTTPException(422, "retell_recipient_invalid")
    values = (
        [task.get("to_number") for task in body.get("tasks", []) if isinstance(task, dict)]
        if args.endpoint == "createBatchCall"
        else [body.get("to_number")]
    )
    if (
        not values
        or len(values) > 100
        or len(values) != len(set(values))
        or any(
            not isinstance(phone, str) or not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone)
            for phone in values
        )
    ):
        raise HTTPException(422, "retell_recipient_invalid")
    # No verified Colombian origination route is configured in this integration.
    if any(phone.startswith("+57") for phone in values):
        raise HTTPException(409, "retell_route_confirmation_required")
    return values


def validate_contacts(db, args):
    phones = destinations(args)
    if set(phones) != {contact.expected_phone for contact in args.contacts} or len(phones) != len(
        args.contacts
    ):
        raise HTTPException(422, "retell_contact_binding_required")
    for contact in args.contacts:
        row = db.execute(
            "SELECT phone FROM crm.contacts WHERE id=%s FOR SHARE", (contact.contact_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if row["phone"] != contact.expected_phone:
            raise HTTPException(409, "retell_contact_changed")


def preflight(db, args, revision=None):
    from ..control import service as control

    control.require_connections(db, "retell")
    metadata = operation(args.endpoint)
    provider = require_state(revision)
    validate_contacts(db, args)
    result = bridge.request(
        "/prepare",
        {"revision": provider["revision"], "endpoint": args.endpoint, "arguments": args.arguments},
        timeout=65,
    )
    if (
        result.get("revision") != provider["revision"]
        or result.get("endpoint") != args.endpoint
        or result.get("risk") != metadata["risk"]
        or type(result.get("requires_consent")) is not bool
        or result["requires_consent"] != requires_consent(args.endpoint)
        or not re.fullmatch(r"[0-9a-f]{64}", result.get("schema_hash", ""))
    ):
        raise HTTPException(503, "retell_schema_unavailable")
    return provider["revision"], result["schema_hash"]


def freeze(db, args, admin):
    revision, digest = preflight(db, args)
    pref = db.execute("SELECT version FROM crm.control_connections WHERE key='retell'").fetchone()
    return {
        "connection:retell": pref["version"],
        "provider:retell": revision,
        "retell:schema_hash": digest,
        "retell:requires_consent": requires_consent(args.endpoint),
        "retell:risk": operation(args.endpoint)["risk"],
    }


def prepare(db, row, args, admin, consent_confirmed):
    if requires_consent(args.endpoint) and consent_confirmed is not True:
        raise HTTPException(422, "retell_consent_required")
    revision, digest = preflight(db, args, row["revisions"]["provider:retell"])
    if (
        digest != row["revisions"]["retell:schema_hash"]
        or row["revisions"].get("retell:requires_consent") is not requires_consent(args.endpoint)
        or row["revisions"].get("retell:risk") != operation(args.endpoint)["risk"]
    ):
        raise HTTPException(409, "retell_schema_changed")
    return {
        "request_id": str(row["id"]),
        "revision": revision,
        "endpoint": args.endpoint,
        "arguments": args.arguments,
        "expected_schema_hash": digest,
        "consent_confirmed": consent_confirmed is True,
    }


def safe_result(value, depth=0, budget=None):
    """Defense in depth: private provider data must not be persisted by the broker."""
    budget = [16000] if budget is None else budget
    if depth > 12 or budget[0] <= 0:
        return "[truncated]"
    budget[0] -= 12
    if isinstance(value, dict):
        result = {}
        for key, child in list(value.items())[:100]:
            if budget[0] <= 0:
                break
            if models.sensitive(str(key)):
                continue
            label = str(key)[:120]
            budget[0] -= len(json.dumps(label).encode()) + 8
            result[label] = safe_result(child, depth + 1, budget)
        return result
    if isinstance(value, list):
        result = []
        for child in value[:50]:
            if budget[0] <= 0:
                break
            result.append(safe_result(child, depth + 1, budget))
        return result
    if isinstance(value, str):
        text = value[: min(2000, max(0, budget[0] // 6))]
        budget[0] -= len(json.dumps(text).encode())
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("invalid_retell_result")


def execute_reserved(payload, admin):
    value = bridge.request("/execute", payload, timeout=65)
    if payload["endpoint"] == "createWebCall" and value.get("status") == "ready":
        if (
            set(value) - {"status", "session_id", "call_id"}
            or value.get("session_id") != payload["request_id"]
        ):
            raise ValueError("invalid_retell_session")
        result = {"provider": "retell", "status": "ready", "session_id": payload["request_id"]}
        if "call_id" in value:
            if not isinstance(value["call_id"], str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,200}", value["call_id"]
            ):
                raise ValueError("invalid_retell_session")
            result["call_id"] = value["call_id"]
        return result
    if value.get("status") == "external_outcome_unconfirmed":
        return {
            "provider": "retell",
            "status": "external_outcome_unconfirmed",
            "retryable": False,
            "endpoint": payload["endpoint"],
        }
    if (
        set(value) != {"status", "data", "endpoint"}
        or value.get("status") != "completed"
        or value.get("endpoint") != payload["endpoint"]
    ):
        raise ValueError("invalid_retell_result")
    return {
        "provider": "retell",
        "status": "completed",
        "endpoint": payload["endpoint"],
        "data": safe_result(value["data"]),
    }


def claim(proposal_id, admin):
    from ..control import service as control

    with connect() as db:
        control.lock(db)
        row = db.execute(
            "SELECT * FROM crm.hermes_proposals WHERE id=%s AND actor_id=%s AND session_hash=%s FOR UPDATE",
            (proposal_id, admin["id"], admin["token_hash"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if (
            row["status"] != "approved"
            or row["action"] != "retell.execute"
            or row["arguments"].get("endpoint") != "createWebCall"
            or not isinstance(row["result"], dict)
            or row["result"].get("status") != "ready"
            or row["result"].get("session_id") != str(proposal_id)
        ):
            raise HTTPException(409, "retell_session_not_ready")
        if row["created_at"] + timedelta(minutes=15) <= datetime.now(UTC):
            raise HTTPException(410, "retell_session_expired")
        control.check_revisions(db, row["revisions"])
        revision = row["revisions"]["provider:retell"]
        require_state(revision)
        consumed = db.execute(
            "INSERT INTO crm.retell_session_claims(proposal_id,owner_id,session_hash) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING proposal_id",
            (proposal_id, admin["id"], admin["token_hash"]),
        ).fetchone()
        if not consumed:
            raise HTTPException(409, "retell_session_claimed")
    # DB claim commits BEFORE external one-shot retrieval; failure cannot reopen it.
    try:
        value = bridge.request(f"/sessions/{proposal_id}/claim", {"revision": revision}, timeout=5)
        if (
            set(value) != {"access_token"}
            or not isinstance(value["access_token"], str)
            or not 1 <= len(value["access_token"]) <= 16000
            or any(ord(c) < 32 for c in value["access_token"])
        ):
            raise ValueError
        return value
    except (HTTPException, TypeError, ValueError):
        raise HTTPException(503, "retell_session_unavailable") from None
