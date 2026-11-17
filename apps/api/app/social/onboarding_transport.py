"""Fixed supervised welcome operations; routing identity is never the submitted phone."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from ..crm.database import connect
from ..inbox import provider, service
from ..inbox.models import Execute, validate
from . import audio_media, config, consent, media, onboarding, workflow
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
    return _verified_source(db, row, cfg, credentials)


def recovery_source(db, row):
    cfg, credentials = onboarding.guard_scope(db, row)
    return _verified_source(db, row, cfg, credentials)


def _verified_source(db, row, cfg, credentials):
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
    envelope = read(
        credentials, row, "getInboxConversationMessages", {"sortOrder": "desc", "limit": 50}
    )
    messages = envelope.get("messages")
    if not isinstance(messages, list):
        raise TypeError("welcome_messages_invalid")
    if row["platform"] == "tiktok":
        from . import tiktok_intake

        tiktok_intake.history(db, row, envelope)
    recovering = (
        bool(row.get("recovery_event_id")) and row["group_receipt"].get("status") != "accepted"
    )
    if recovering:
        pagination = envelope.get("pagination", {})
        metadata = envelope.get("metadata", {})
        meta = envelope.get("meta", {})
        if (
            len(messages) >= 50
            or not isinstance(pagination, dict)
            or not isinstance(metadata, dict)
            or not isinstance(meta, dict)
            or envelope.get("success") is False
            or any(
                part.get(key)
                for part in (envelope, pagination, metadata, meta)
                for key in (
                    "accountsFailed",
                    "accountsSkipped",
                    "failedAccounts",
                    "hasMore",
                    "nextCursor",
                    "next_cursor",
                    "partialFailure",
                    "partial_failure",
                    "partial",
                    "warning",
                    "warnings",
                )
            )
            or (isinstance(pagination.get("total"), int) and pagination["total"] > len(messages))
        ):
            raise ValueError("welcome_recovery_history_incomplete")
        accepted = {
            row[column].get("message_id")
            for column in ("audio_receipt", "website_receipt", "group_receipt", "question_receipt")
            if row[column].get("status") == "accepted"
        }
        if any(
            message.get("direction") not in {"incoming", "outgoing"}
            or (message.get("direction") == "outgoing" and message.get("id") not in accepted)
            for message in messages
            if isinstance(message, dict)
        ):
            raise ValueError("welcome_recovery_already_answered")
        newest = next(
            (
                message
                for message in messages
                if isinstance(message, dict)
                and message.get("direction") == "incoming"
                and message.get("senderId") == row["participant_id"]
                and message.get("isDeleted") is not True
            ),
            None,
        )
        if not newest or newest.get("id") != row["source"]["message_id"]:
            raise ValueError("welcome_recovery_newer_message")
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
            from . import consent

            consent.remember(db, {**row["source"], "event_id": "history:" + str(message.get("id"))})
            if row["id"] is not None:
                db.execute(
                    "UPDATE crm.social_onboarding SET suppressed=true WHERE id=%s", (row["id"],)
                )
                db.commit()
            raise ValueError("welcome_suppressed")
        if message.get("id") == row["source"]["message_id"]:
            matched = message
    if (
        not matched
        or matched.get("message") != row["source"]["text"]
        or not datetime.now(UTC) - timedelta(hours=48 if row["platform"] == "tiktok" else 24)
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
    if operation not in {
        "welcome_check",
        "welcome_question",
        "welcome_audio",
        "welcome_website",
        "welcome_group",
        "welcome_introduction",
        "welcome_confirmation",
    }:
        raise ValueError("invalid_welcome_operation")
    with connect() as db, config.locked():
        # Serialize welcome submissions; refusal intake deliberately never waits on this lock.
        db.execute("SELECT pg_advisory_xact_lock(9142041)")
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
        if row["platform"] == "tiktok":
            from . import tiktok_intake

            if phase not in {"introduction", "question", "confirmation", "website", "group"}:
                raise ValueError("welcome_tiktok_text_only")
            if not db.execute(
                "SELECT 1 FROM crm.tiktok_reply_reservations WHERE onboarding_id=%s AND phase=%s AND source_message_id=%s AND message_id IS NULL",
                (row["id"], phase, row["source"]["message_id"]),
            ).fetchone():
                raise ValueError("welcome_tiktok_reservation_required")
            if phase != "introduction" and row["introduction_receipt"].get("status") != "accepted":
                raise ValueError("welcome_tiktok_introduction_required")
            if phase in {"confirmation", "website", "group"} and not row["contact_id"]:
                raise ValueError("welcome_tiktok_registration_required")
            if (
                phase in {"website", "group"}
                and row["confirmation_receipt"].get("status") != "accepted"
            ):
                raise ValueError("welcome_tiktok_confirmation_required")
        if not row["welcome_required"] and phase != "question":
            raise ValueError("welcome_already_claimed")
        if (
            phase == "website"
            and row["platform"] != "tiktok"
            and row["audio_receipt"].get("status") != "accepted"
        ):
            raise ValueError("welcome_audio_required")
        if phase == "group" and row["website_receipt"].get("status") != "accepted":
            raise ValueError("welcome_website_required")
        if row["registration_first"]:
            if phase in {"website", "group"} and (
                not row["contact_id"] or not row["identity_confirmed"]
            ):
                raise ValueError("welcome_registration_required")
            if (
                phase == "question"
                and row["welcome_required"]
                and row["audio_receipt"].get("status") != "accepted"
            ):
                raise ValueError("welcome_audio_required")
        if (
            phase == "question"
            and row["platform"] != "tiktok"
            and not row["registration_first"]
            and row["welcome_required"]
            and not any(
                row[column].get("status") == "accepted"
                for column in ("group_receipt", "links_receipt")
            )
        ):
            raise ValueError("welcome_group_required")
        if consent.suppressed(db, row):
            raise ValueError("welcome_suppressed")
        if phase == "audio":
            accepted = transmit_audio(row, credentials)
        else:
            messages = {
                "website": "Aquí puedes ver la página oficial de nuestro proyecto:\n"
                + onboarding.WEBSITE,
                "group": "Para estar al tanto de toda la información previa al evento, "
                "ingresa a nuestro grupo de WhatsApp:\n" + cfg["group_url"],
                "question": "Hola, soy Sara. Para registrarte, envíame tu nombre completo y número de celular. "
                "Puedes escribir: Nombre completo: … Celular: …",
            }
            if row["platform"] == "tiktok":
                messages.update(
                    introduction=tiktok_intake.INTRODUCTION, confirmation=tiktok_intake.CONFIRMATION
                )
            if row["registration_first"] and phase == "question":
                candidate = row["details"]
                if set(candidate) == {"name", "phone"}:
                    messages["question"] = (
                        f"Para registrarte, ¿confirmas que tu nombre completo es {candidate['name']} "
                        f"y tu celular es {candidate['phone']}? Responde Confirmo o corrige los datos: "
                        "Nombre completo: … Celular: …"
                    )
                else:
                    messages["question"] = (
                        "Para registrarte, envíame tu nombre completo y número de celular. Puedes escribir: Nombre completo: … Celular: …"
                    )
            message = messages[phase]
            command = Execute(
                operation="sendInboxMessage",
                account_id=row["account_id"],
                path={"conversationId": row["conversation_id"]},
                body={"message": message},
            )
            spec, args = validate(command, credentials)
            key = "sara-welcome-" + identifier
            if row["platform"] == "tiktok" and phase == "question":
                key += "-" + workflow._digest(row["source"]["message_id"])[:16]
            if consent.suppressed(db, row):
                raise ValueError("welcome_suppressed")
            result = provider.request(credentials, spec, args, key=key + "-" + phase)
            accepted = receipt(result, row["conversation_id"])
        return {"state": "completed", "receipt": accepted}
