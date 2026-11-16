"""Fixed-host, sealed PNG attachment submission; no public upload or blind retry."""

import base64
import hashlib
import hmac
import http.client
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from ..images.png import validate_png
from . import config, workflow
from .transport import https_connection

MAX_ATTACHMENT = 5_000_000  # Conservative interpretation of the documented WhatsApp 5 MB cap.
SEND_TIMEOUT = 12
CAPTION = (
    "Concepto generado con IA para Jardines del Encanto. No representa el estado actual de obra."
)


def _validate(data, size):
    if not isinstance(data, bytes) or len(data) > MAX_ATTACHMENT:
        raise HTTPException(409, "image_exceeds_whatsapp_limit")
    try:
        validate_png(data, size)
    except ValueError:
        raise HTTPException(409, "image_delivery_content_changed") from None


def prepare(db, source, image):
    data = bytes(image["data"])
    _validate(data, image["image_size"])
    source = {
        key: str(source[key]) for key in ("id", "account_id", "conversation_id", "participant_id")
    }
    with config.locked():
        reply = _isolated({"operation": "prepare", "source": source})
        credentials = config.required()
        return _prepared(reply, image, data, credentials)


def _prepared(reply, image, data, credentials):
    plan = {
        "reply": reply,
        "image_id": str(UUID(str(image["id"]))),
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "image_size": image["image_size"],
        "mime_type": "image/png",
    }
    plan["seal"] = workflow._seal(plan, credentials)
    return plan


def _check(plan, data, credentials, *, remote=True):
    _validate(data, plan["image_size"])
    unsigned = {key: value for key, value in plan.items() if key != "seal"}
    if (
        set(plan) != {"reply", "image_id", "sha256", "byte_size", "image_size", "mime_type", "seal"}
        or not isinstance(plan.get("seal"), str)
        or not hmac.compare_digest(plan["seal"], workflow._seal(unsigned, credentials))
        or plan["sha256"] != hashlib.sha256(data).hexdigest()
        or plan["byte_size"] != len(data)
        or plan["mime_type"] != "image/png"
        or str(UUID(plan["image_id"])) != plan["image_id"]
    ):
        raise HTTPException(409, "image_delivery_plan_changed")
    reply = plan["reply"]
    if (
        reply["kind"] != "social_message"
        or reply["platform"] != "whatsapp"
        or reply["payload"] != {"accountId": reply["account_id"], "message": CAPTION}
    ):
        raise HTTPException(409, "image_delivery_plan_changed")
    if remote:
        workflow._check(reply, credentials)


def _multipart(plan, data):
    # Stable framing supports vendor idempotency. No bytes are modified or hosted publicly.
    boundary = "jardines-" + plan["image_id"] + "-" + plan["sha256"][:16]
    marker = boundary.encode("ascii")
    if marker in data:
        raise HTTPException(409, "image_delivery_framing_invalid")
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
        + b'\r\nContent-Disposition: form-data; name="attachment"; filename="jardines-'
        + plan["image_id"].encode("ascii")
        + b'.png"\r\nContent-Type: image/png\r\n\r\n'
        + data
        + b"\r\n--"
        + marker
        + b"--\r\n"
    )
    body = b"".join(chunks)
    if len(body) > MAX_ATTACHMENT + 2048:
        raise HTTPException(409, "image_delivery_framing_invalid")
    return body, "multipart/form-data; boundary=" + boundary


def _isolated(frame):
    """Exec a fixed trusted module; kill+wait bounds DNS, TLS, reads and late sends."""
    root = Path(__file__).resolve().parents[2]
    bootstrap = (
        "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
        "runpy.run_module('app.social.media_process',run_name='__main__')"
    )
    payload = json.dumps(frame, separators=(",", ":")).encode()
    if len(payload) > MAX_ATTACHMENT * 4 // 3 + 65536:
        raise HTTPException(409, "image_delivery_frame_invalid")
    # No inherited Python hooks, OpenAI key or arbitrary proxy destinations.
    env = {
        key: os.environ[key]
        for key in ("CRM_DATABASE_URL", "ZERNIO_CONFIG_DIR", "ZERNIO_HTTPS_PROXY")
        if key in os.environ
    }
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", bootstrap, str(root)],
            cwd=root,
            env=env,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=SEND_TIMEOUT,
            check=False,
        )
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError
        reply = json.loads(result.stdout)
        if not isinstance(reply, dict) or set(reply) != {"ok", "result"} or reply["ok"] is not True:
            raise ValueError
        if not isinstance(reply["result"], dict):
            raise TypeError
        return reply["result"]
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        # subprocess.run kills and waits for a timed-out child before raising.
        # The caller therefore releases authority guards only once no late send can run.
        raise HTTPException(502, "image_delivery_unknown") from None


def submit(plan, data, request_id):
    """Caller has committed its once-only reservation and holds final identity guards."""
    workflow._identifier(request_id, 200)
    with config.locked():
        credentials = config.required()
        _check(plan, data, credentials, remote=False)
        try:
            result = _isolated(
                {
                    "operation": "submit",
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
            return {"state": "unknown", "receipt": {}, "error": "image_delivery_unknown"}


def _transmit(plan, data, credentials, request_id):
    """Runs only inside the supervised process; it never acquires parent file locks."""
    _check(plan, data, credentials)
    body, content_type = _multipart(plan, data)
    path = workflow._route(
        "reply", plan["reply"]["account_id"], conversation_id=plan["reply"]["conversation_id"]
    )
    connection = None
    response = None
    try:
        connection = https_connection("zernio.com", timeout=SEND_TIMEOUT)
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
        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or not isinstance(message, dict)
        ):
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
        return {"state": "unknown", "receipt": {}, "error": "image_delivery_unknown"}
    finally:
        if response:
            response.close()
        if connection:
            connection.close()
