"""Shared private voice service. Paid dispatch is invoked only after reservation commits."""

import base64
import re
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from ..crm.database import connect
from ..sara import attachments
from . import bridge, models

UNAVAILABLE = {
    "available": False,
    "configured": False,
    "verified": False,
    "revision": 0,
    "key_suffix": None,
    "defaults": models.Defaults().model_dump(),
}


def state():
    try:
        value = models.GatewayState.model_validate(bridge.request("/state")).model_dump()
        return {**value, "available": True}
    except (HTTPException, ValidationError, ValueError, TypeError):
        return {**UNAVAILABLE}


def settings(db):
    pref = db.execute(
        "SELECT enabled FROM crm.control_connections WHERE key='elevenlabs'"
    ).fetchone()
    return {**state(), "enabled": bool(pref and pref["enabled"])}


def require_state(revision=None):
    value = state()
    if not value["available"] or not value["verified"] or not value["configured"]:
        raise HTTPException(503, "voice_unavailable")
    if revision is not None and value["revision"] != revision:
        raise HTTPException(409, "voice_provider_changed")
    return value


def catalog(db):
    value = settings(db)
    cached = db.execute(
        "SELECT catalog FROM crm.voice_catalog WHERE id=true AND revision=%s", (value["revision"],)
    ).fetchone()
    return {
        **value,
        "catalog": cached["catalog"] if cached and value["available"] else None,
        "operations": {
            name: model.model_json_schema() for name, model in models.OPERATIONS.items()
        },
    }


def refresh(data, admin):
    from ..control import service as control

    with connect() as db:
        control.lock(db)
        require_state(data.revision)
        try:
            result = models.Catalog.model_validate(
                bridge.request("/catalog", data.model_dump(), timeout=65)
            ).model_dump()
        except (ValidationError, ValueError, TypeError):
            raise HTTPException(503, "voice_unavailable") from None
        if result["revision"] != data.revision:
            raise HTTPException(409, "voice_provider_changed")
        db.execute(
            "INSERT INTO crm.voice_catalog(id,revision,catalog) VALUES (true,%s,%s) "
            "ON CONFLICT(id) DO UPDATE SET revision=EXCLUDED.revision,catalog=EXCLUDED.catalog,updated_at=now()",
            (result["revision"], Jsonb(result)),
        )
        control.audit(db, admin, "voice.catalog.refresh", {"revision": result["revision"]})
    return result


def configure(data, admin, disconnect=False):
    from ..control import service as control

    # The shared control lock serializes policy/configuration changes with approval checks.
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
            raise HTTPException(503, "voice_unavailable") from None
        # Every successful provider change also revokes connection-bound pending proposals.
        db.execute(
            "UPDATE crm.control_connections SET enabled=CASE WHEN %s THEN false ELSE enabled END,version=version+1 WHERE key='elevenlabs'",
            (disconnect,),
        )
        control.audit(
            db,
            admin,
            "voice.disconnect" if disconnect else "voice.configure",
            {"revision": result["revision"]},
        )
        pref = db.execute(
            "SELECT enabled FROM crm.control_connections WHERE key='elevenlabs'"
        ).fetchone()
    return {**result, "available": True, "enabled": pref["enabled"]}


def quota(db, owner, size):
    db.execute("SELECT pg_advisory_xact_lock(20261115,hashtext(%s))", (str(owner),))
    row = db.execute(
        "SELECT count(*) AS files,COALESCE(sum(size),0) AS bytes FROM crm.voice_artifacts WHERE owner_id=%s",
        (owner,),
    ).fetchone()
    if row["files"] >= 100 or row["bytes"] + size > 25 * 1024 * 1024:
        raise HTTPException(409, "voice_artifact_quota_exceeded")


def stage(data, admin):
    raw, mime, kind = attachments.decode(data)
    if kind != "audio":
        raise HTTPException(422, "attachment_invalid_type")
    with connect() as db:
        quota(db, admin["id"], len(raw))
        row = db.execute(
            "INSERT INTO crm.voice_artifacts(owner_id,kind,filename,mime_type,size,data) VALUES (%s,'input',%s,%s,%s,%s) RETURNING id,filename,mime_type,size",
            (admin["id"], data.filename, mime, len(raw), raw),
        ).fetchone()
    return {"attachment_id": row["id"], **{k: row[k] for k in ("filename", "mime_type", "size")}}


def audio(db, attachment_id, admin):
    row = db.execute(
        "SELECT data,mime_type,size FROM crm.voice_artifacts WHERE id=%s AND owner_id=%s AND kind='input'",
        (attachment_id, admin["id"]),
    ).fetchone()
    if not row:
        row = db.execute(
            "SELECT data,mime_type,size FROM crm.sara_attachments WHERE id=%s AND owner_id=%s AND kind='audio'",
            (attachment_id, admin["id"]),
        ).fetchone()
    if not row or row["size"] > 512 * 1024 or not row["mime_type"].startswith("audio/"):
        raise HTTPException(404, "not_found")
    return {
        "data_base64": base64.b64encode(bytes(row["data"])).decode(),
        "mime_type": row["mime_type"],
    }


def validate_operation(db, args, admin, revision=None):
    from ..control import service as control

    control.require_connections(db, "elevenlabs")
    provider = require_state(revision)
    cached = db.execute(
        "SELECT catalog FROM crm.voice_catalog WHERE id=true AND revision=%s",
        (provider["revision"],),
    ).fetchone()
    values = args.arguments
    required = {
        "tts": (("voices", "voice_id"), ("models", "model_id")),
        "agent_session": (("agents", "agent_id"),),
        "outbound_call": (("agents", "agent_id"), ("phone_numbers", "phone_number_id")),
    }.get(args.operation, ())
    if required and not cached:
        raise HTTPException(409, "voice_catalog_required")
    for group, key in required:
        if values[key] not in {row["id"] for row in cached["catalog"][group]}:
            raise HTTPException(422, "voice_catalog_id_invalid")
    dispatch = dict(values)
    if args.operation == "stt":
        dispatch = audio(db, values["attachment_id"], admin)
    if args.operation == "tts":
        quota(db, admin["id"], 2 * 1024 * 1024)
    if args.operation == "outbound_call":
        contact = db.execute(
            "SELECT phone FROM crm.contacts WHERE id=%s FOR SHARE", (values["contact_id"],)
        ).fetchone()
        if not contact:
            raise HTTPException(404, "not_found")
        if contact["phone"] != values["expected_phone"]:
            raise HTTPException(409, "voice_contact_changed")
        dispatch = {key: values[key] for key in ("agent_id", "phone_number_id")}
        dispatch["to_number"] = contact["phone"]
    return provider["revision"], dispatch


def freeze(db, args, admin):
    revision, _ = validate_operation(db, args, admin)
    pref = db.execute(
        "SELECT version FROM crm.control_connections WHERE key='elevenlabs'"
    ).fetchone()
    return {"connection:elevenlabs": pref["version"], "provider:elevenlabs": revision}


def prepare(db, row, args, admin, consent_confirmed):
    if args.operation == "outbound_call" and consent_confirmed is not True:
        raise HTTPException(422, "voice_recipient_consent_required")
    revision, arguments = validate_operation(
        db, args, admin, row["revisions"]["provider:elevenlabs"]
    )
    return {
        "id": str(row["id"]),
        "revision": revision,
        "operation": args.operation,
        "arguments": arguments,
    }


def execute_reserved(payload, admin):
    value = bridge.request("/execute", payload, timeout=65)
    operation = payload["operation"]
    if operation == "tts":
        if (
            set(value) != {"status", "mime_type", "data_base64"}
            or value["status"] != "completed"
            or value["mime_type"] != "audio/mpeg"
        ):
            raise ValueError("invalid_voice_result")
        raw = base64.b64decode(value["data_base64"], validate=True)
        if not 12 <= len(raw) <= 2 * 1024 * 1024 or not (
            raw.startswith(b"ID3") or raw[0] == 255 and raw[1] & 224 == 224
        ):
            raise ValueError("invalid_voice_result")
        with connect() as db:
            quota(db, admin["id"], len(raw))
            row = db.execute(
                "INSERT INTO crm.voice_artifacts(owner_id,proposal_id,kind,filename,mime_type,size,data) VALUES (%s,%s,'output','sara-audio.mp3','audio/mpeg',%s,%s) RETURNING id",
                (admin["id"], payload["id"], len(raw), raw),
            ).fetchone()
        return {
            "status": "completed",
            "artifact_id": str(row["id"]),
            "content_path": f"/api/crm/voice/artifacts/{row['id']}/content",
        }
    if operation == "stt":
        if (
            set(value) != {"status", "text"}
            or value["status"] != "completed"
            or not isinstance(value["text"], str)
            or not 1 <= len(value["text"]) <= 16000
            or "\x00" in value["text"]
        ):
            raise ValueError("invalid_voice_result")
        return {"status": "completed", "text": value["text"]}
    if operation == "agent_session":
        if value != {"status": "ready"}:
            raise ValueError("invalid_voice_result")
        return {"status": "ready", "session_id": payload["id"]}
    if set(value) - {"status", "conversation_id", "call_id"} or value.get("status") != "completed":
        raise ValueError("invalid_voice_result")
    for key in ("conversation_id", "call_id"):
        if key in value and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value[key]):
            raise ValueError("invalid_voice_result")
    return value


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
            or row["action"] != "voice.execute"
            or row["arguments"].get("operation") != "agent_session"
            or row["result"] != {"status": "ready", "session_id": str(proposal_id)}
        ):
            raise HTTPException(409, "voice_session_not_ready")
        if row["created_at"] + timedelta(minutes=11) <= datetime.now(UTC):
            raise HTTPException(410, "voice_session_expired")
        control.check_revisions(db, row["revisions"])
        revision = row["revisions"]["provider:elevenlabs"]
        require_state(revision)
        consumed = db.execute(
            "INSERT INTO crm.voice_session_claims(proposal_id,owner_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING proposal_id",
            (proposal_id, admin["id"]),
        ).fetchone()
        if not consumed:
            raise HTTPException(409, "voice_session_claimed")
    # Reservation committed before asking the boundary for one-shot volatile material.
    try:
        value = bridge.request(f"/sessions/{proposal_id}/claim", {"revision": revision}, timeout=5)
        if (
            set(value) - {"token", "conversation_id"}
            or not isinstance(value.get("token"), str)
            or not 1 <= len(value["token"]) <= 16000
            or any(ord(c) < 32 for c in value["token"])
        ):
            raise ValueError
        if "conversation_id" in value and not re.fullmatch(
            r"[A-Za-z0-9_-]{1,200}", value["conversation_id"]
        ):
            raise ValueError
        return value
    except (HTTPException, ValueError, TypeError):
        raise HTTPException(503, "voice_session_unavailable") from None
