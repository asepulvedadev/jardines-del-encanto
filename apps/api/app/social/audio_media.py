"""Sealed MP3 replies only; PNG transport and its validation remain unchanged."""

import base64
import hashlib
import hmac
import http.client
import json
from uuid import UUID

from fastapi import HTTPException

from ..voice.service import tts_audio
from . import config, media, workflow
from .transport import https_connection

CAPTION = "Respuesta en audio de Sara IA."
MAX_AUDIO = 2 * 1024 * 1024


def validate(data):
    if not isinstance(data, bytes):
        raise TypeError("invalid_audio")
    tts_audio(
        {
            "status": "completed",
            "mime_type": "audio/mpeg",
            "data_base64": base64.b64encode(data).decode("ascii"),
        }
    )


def prepare_reply(source):
    source = {
        key: str(source[key]) for key in ("id", "account_id", "conversation_id", "participant_id")
    }
    with config.locked():
        return media._isolated({"operation": "prepare_audio", "source": source})


def prepare(source, data):
    validate(data)
    reply = prepare_reply(source)
    with config.locked():
        plan = {
            "reply": reply,
            "audio_id": str(UUID(str(source["id"]))),
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_size": len(data),
            "mime_type": "audio/mpeg",
        }
        plan["seal"] = workflow._seal(plan, config.required())
        return plan


def check(plan, data, credentials, *, remote=True):
    validate(data)
    unsigned = {k: v for k, v in plan.items() if k != "seal"}
    if (
        set(plan) != {"reply", "audio_id", "sha256", "byte_size", "mime_type", "seal"}
        or not isinstance(plan.get("seal"), str)
        or not hmac.compare_digest(plan["seal"], workflow._seal(unsigned, credentials))
        or plan["sha256"] != hashlib.sha256(data).hexdigest()
        or plan["byte_size"] != len(data)
        or plan["mime_type"] != "audio/mpeg"
        or str(UUID(plan["audio_id"])) != plan["audio_id"]
    ):
        raise ValueError("audio_plan_changed")
    reply = plan["reply"]
    if (
        reply["kind"] != "social_message"
        or reply["platform"] != "whatsapp"
        or reply["payload"] != {"accountId": reply["account_id"], "message": CAPTION}
    ):
        raise ValueError("audio_plan_changed")
    if remote:
        workflow._check(reply, credentials)


def multipart(plan, data):
    boundary = "jardines-audio-" + plan["audio_id"] + "-" + plan["sha256"][:16]
    marker = boundary.encode("ascii")
    if marker in data:
        raise ValueError("audio_framing_invalid")
    chunks = []
    for name, value in (("accountId", plan["reply"]["account_id"]), ("message", CAPTION)):
        chunks.append(
            b"--"
            + marker
            + b'\r\nContent-Disposition: form-data; name="'
            + name.encode()
            + b'"\r\n\r\n'
            + value.encode("utf-8")
            + b"\r\n"
        )
    chunks.append(
        b"--"
        + marker
        + b'\r\nContent-Disposition: form-data; name="attachment"; filename="sara-'
        + plan["audio_id"].encode("ascii")
        + b'.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
        + data
        + b"\r\n--"
        + marker
        + b"--\r\n"
    )
    body = b"".join(chunks)
    if len(body) > MAX_AUDIO + 2048:
        raise ValueError("audio_framing_invalid")
    return body, "multipart/form-data; boundary=" + boundary


def submit(plan, data, request_id):
    from . import consent

    workflow._identifier(request_id, 200)
    with config.locked(), consent.sending(plan["reply"]):
        credentials = config.required()
        check(plan, data, credentials, remote=False)
        try:
            result = media._isolated(
                {
                    "operation": "submit_audio",
                    "plan": plan,
                    "credentials": credentials,
                    "data_base64": base64.b64encode(data).decode("ascii"),
                    "request_id": request_id,
                }
            )
            if result.get("state") not in {"completed", "unknown"}:
                raise ValueError
            return result
        except (HTTPException, ValueError):
            return {"state": "unknown", "receipt": {}, "error": "audio_delivery_unknown"}


def transmit(plan, data, credentials, request_id):
    """Only the supervised fixed-module child performs this external submission."""
    check(plan, data, credentials)
    body, content_type = multipart(plan, data)
    path = workflow._route(
        "reply", plan["reply"]["account_id"], conversation_id=plan["reply"]["conversation_id"]
    )
    connection = response = None
    try:
        connection = https_connection("zernio.com", timeout=media.SEND_TIMEOUT)
        connection.request(
            "POST",
            "/api" + path,
            body=body,
            headers={
                "Authorization": "Bearer " + credentials["api_key"],
                "Accept": "application/json",
                "Content-Type": content_type,
                "Idempotency-Key": workflow._identifier(request_id, 200),
            },
        )
        response = connection.getresponse()
        raw = response.read(workflow.MAX_RESPONSE + 1)
        if not 200 <= response.status < 300 or len(raw) > workflow.MAX_RESPONSE:
            raise ValueError
        result = json.loads(raw)
        message = result.get("data") if isinstance(result, dict) else None
        if not isinstance(message, dict) or result.get("success") is not True:
            raise ValueError
        receipt = {
            "status": "accepted",
            "message_id": workflow._identifier(message.get("messageId")),
        }
        if message.get("conversationId") is not None:
            if message["conversationId"] != plan["reply"]["conversation_id"]:
                raise ValueError
            receipt["conversation_id"] = workflow._identifier(message["conversationId"])
        return {"state": "completed", "receipt": receipt}
    except (HTTPException, OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
        return {"state": "unknown", "receipt": {}, "error": "audio_delivery_unknown"}
    finally:
        if response:
            response.close()
        if connection:
            connection.close()
