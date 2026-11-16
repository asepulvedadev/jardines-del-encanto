"""Fixed supervised welcome operations; routing identity is never the submitted phone."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from ..crm.database import connect
from ..inbox import provider, service
from ..inbox.models import Execute, validate
from . import audio_media, config, media, onboarding, workflow
from .transport import https_connection


def read(credentials, row, operation, query=None):
    command = Execute(
        operation=operation,
        account_id=row["account_id"],
        path={"conversationId": row["conversation_id"]},
        query=query or {},
    )
    spec, args = validate(command, credentials)
    result = provider.request(credentials, spec, args)
    service.scope_result(result, row["account_id"])
    return result


def source(db, row):
    cfg, credentials = onboarding.guard(db, row)
    account = service.account(credentials, row["account_id"])
    if account["platform"] != row["platform"]:
        raise ValueError("welcome_account_changed")
    thread = read(credentials, row, "getInboxConversation").get("data")
    if not isinstance(thread, dict) or any(
        thread.get(remote) != row[local]
        for remote, local in (
            ("id", "conversation_id"),
            ("accountId", "account_id"),
            ("platform", "platform"),
            ("participantId", "participant_id"),
        )
    ):
        raise ValueError("welcome_thread_changed")
    meta = thread.get("metadata") or {}
    if not isinstance(meta, dict) or meta.get("standby"):
        raise ValueError("welcome_thread_standby")
    # The owner specifically approved implicit vendor takeover ONLY for this configured
    # Facebook account. An explicit human/other owner or standby still wins.
    if "threadControl" in thread and thread["threadControl"] != "app":
        raise ValueError("welcome_thread_control_changed")
    if row["platform"] == "facebook" and cfg["facebook_takeover"] is not True:
        raise ValueError("welcome_takeover_not_authorized")
    messages = read(
        credentials, row, "getInboxConversationMessages", {"sortOrder": "desc", "limit": 50}
    ).get("messages")
    if not isinstance(messages, list):
        raise TypeError("welcome_messages_invalid")
    matched = None
    for message in messages:
        if not isinstance(message, dict):
            raise TypeError("welcome_messages_invalid")
        if any(
            message.get(remote) != row[local]
            for remote, local in (
                ("conversationId", "conversation_id"),
                ("accountId", "account_id"),
                ("platform", "platform"),
            )
        ):
            raise ValueError("welcome_message_scope_changed")
        if message.get("direction") != "incoming":
            continue
        if message.get("senderId") != row["participant_id"] or message.get("isDeleted") is True:
            continue
        metadata = message.get("metadata") or {}
        if not isinstance(metadata, dict) or metadata.get("standby"):
            raise ValueError("welcome_message_standby")
        if onboarding.opted_out(message.get("message") or ""):
            db.execute("UPDATE crm.social_onboarding SET suppressed=true WHERE id=%s", (row["id"],))
            db.commit()
            raise ValueError("welcome_suppressed")
        if message.get("id") == row["source"]["message_id"]:
            matched = message
    if (
        not matched
        or matched.get("message") != row["source"]["text"]
        or not datetime.now(UTC) - timedelta(hours=24)
        < workflow._time(matched.get("createdAt"))
        <= datetime.now(UTC)
    ):
        raise ValueError("welcome_source_unverified")
    return (
        cfg,
        credentials,
        {
            "name": matched.get("senderName"),
            "phoneNumber": matched.get("senderPhoneNumber")
            if row["platform"] == "whatsapp"
            else None,
        },
    )


def receipt(result, conversation_id):
    body = result.get("data")
    if (
        result.get("success") is not True
        or not isinstance(body, dict)
        or result.get("partialFailure")
        or body.get("partialFailure")
        or body.get("conversationId", conversation_id) != conversation_id
    ):
        raise ValueError("welcome_delivery_unconfirmed")
    return {"status": "accepted", "message_id": workflow._identifier(body.get("messageId"))}


def transmit_audio(row, credentials):
    data = bytes(row["audio"] or b"")
    audio_media.validate(data)
    boundary = "jardines-welcome-" + str(row["id"])
    marker = boundary.encode()
    if marker in data:
        raise ValueError("welcome_audio_framing")
    body = (
        b"--"
        + marker
        + b'\r\nContent-Disposition: form-data; name="accountId"\r\n\r\n'
        + row["account_id"].encode()
        + b"\r\n--"
        + marker
        + b'\r\nContent-Disposition: form-data; name="attachment"; filename="sara-bienvenida.mp3"'
        + b"\r\nContent-Type: audio/mpeg\r\n\r\n"
        + data
        + b"\r\n--"
        + marker
        + b"--\r\n"
    )
    connection = None
    try:
        connection = https_connection("zernio.com", timeout=media.SEND_TIMEOUT)
        connection.request(
            "POST",
            "/api/v1/inbox/conversations/" + quote(row["conversation_id"], safe="") + "/messages",
            body=body,
            headers={
                "Authorization": "Bearer " + credentials["api_key"],
                "Content-Type": "multipart/form-data; boundary=" + boundary,
                "Accept": "application/json",
                "Idempotency-Key": "sara-welcome-" + str(row["id"]) + "-audio",
            },
        )
        response = connection.getresponse()
        raw = response.read(provider.MAX_RESPONSE + 1)
        if not 200 <= response.status < 300 or len(raw) > provider.MAX_RESPONSE:
            raise ValueError("welcome_audio_unconfirmed")
        return receipt(json.loads(raw), row["conversation_id"])
    finally:
        if connection:
            connection.close()


def execute(operation, identifier):
    identifier = str(UUID(identifier))
    if operation not in {"welcome_check", "welcome_question", "welcome_audio", "welcome_links"}:
        raise ValueError("invalid_welcome_operation")
    with connect() as db, config.locked():
        # Serialize the final source check and bounded send with authenticated opt-outs.
        row = db.execute(
            "SELECT * FROM crm.social_onboarding WHERE id=%s FOR UPDATE", (identifier,)
        ).fetchone()
        if not row:
            raise ValueError("welcome_not_found")
        cfg, credentials, sender = source(db, row)
        if operation == "welcome_check":
            return {"sender": sender}
        phase = operation.removeprefix("welcome_")
        if row["state"] != phase + "_reserved":
            raise ValueError("welcome_reservation_changed")
        if phase != "question" and (not row["contact_id"] or not row["deal_id"]):
            raise ValueError("welcome_registration_required")
        if phase == "audio":
            accepted = transmit_audio(row, credentials)
        else:
            if phase == "links" and row["audio_receipt"].get("status") != "accepted":
                raise ValueError("welcome_audio_required")
            message = (
                "Página web: " + onboarding.WEBSITE + "\nGrupo del proyecto: " + cfg["group_url"]
                if phase == "links"
                else "Hola, soy Sara. Para registrarte, envíame tu nombre completo y número de celular. "
                "Puedes escribir: Nombre completo: … Celular: …"
            )
            command = Execute(
                operation="sendInboxMessage",
                account_id=row["account_id"],
                path={"conversationId": row["conversation_id"]},
                body={"message": message},
            )
            spec, args = validate(command, credentials)
            result = provider.request(
                credentials, spec, args, key="sara-welcome-" + identifier + "-" + phase
            )
            accepted = receipt(result, row["conversation_id"])
        return {"state": "completed", "receipt": accepted}
