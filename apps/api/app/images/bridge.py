"""The dedicated image channel is larger than the text bridge, never arbitrary HTTP."""

import base64
import binascii
import json
import os
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from fastapi import HTTPException

from ..hermes.bridge import NoRedirect
from .png import MAX_IMAGE, validate_png

MAX_REQUEST = 4 * 1024 * 1024
MAX_REPLY = 12 * 1024 * 1024


def bridge_url():
    value = os.getenv("HERMES_IMAGE_BRIDGE_URL", "http://image-bridge:8082")
    if not isinstance(value, str) or not value.isascii() or any(char.isspace() for char in value):
        return None
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "http"
        or not port
        or parts.path
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or parts.netloc != f"{host}:{port}"
        or value != f"http://{host}:{port}"
    ):
        return None
    return (
        value if value == "http://image-bridge:8082" or host in {"127.0.0.1", "localhost"} else None
    )


def generate(payload):
    try:
        base = bridge_url()
        if not base:
            raise ValueError
        raw = json.dumps(payload, allow_nan=False).encode()
        if len(raw) > MAX_REQUEST:
            raise ValueError
        req = Request(
            base + "/generate-image",
            data=raw,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=110) as response:
            body = response.read(MAX_REPLY + 1)
        if len(body) > MAX_REPLY:
            raise ValueError
        result = json.loads(body)
        if not isinstance(result, dict) or set(result) != {"ok", "data_base64", "mime_type"}:
            raise ValueError
        if result["ok"] is not True or result["mime_type"] != "image/png":
            raise ValueError
        encoded = result["data_base64"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE + 2) // 3):
            raise ValueError
        data = base64.b64decode(encoded, validate=True)
        return validate_png(data, payload["size"])
    except (OSError, ValueError, TypeError, KeyError, binascii.Error, TimeoutError):
        raise HTTPException(503, "image_outcome_unknown") from None
