"""Bounded fixed-host Zernio adapter. No arbitrary URLs, redirects or vendor errors."""

import http.client
import json
import re
from urllib.parse import urlparse

from fastapi import HTTPException

PLATFORMS = frozenset({"facebook", "instagram", "tiktok", "whatsapp", "telegram"})
MAX_RESPONSE = 1024 * 1024
_ALLOWED = re.compile(
    r"^/v1/(?:profiles/[a-f0-9]{24}|accounts(?:\?[^#]*)?|connect/(?:facebook|instagram|tiktok|whatsapp|telegram)(?:\?[^#]*)?)$"
)


def request(credentials, method, path, payload=None):
    if not _ALLOWED.fullmatch(path) or method not in {"GET", "PATCH"}:
        raise HTTPException(502, "zernio_unavailable")
    connection = http.client.HTTPSConnection("zernio.com", timeout=4)
    try:
        headers = {
            "Authorization": "Bearer " + credentials["api_key"],
            "Accept": "application/json",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        connection.request(method, "/api" + path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if response.status < 200 or response.status >= 300 or len(raw) > MAX_RESPONSE:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError
        return data
    except (OSError, ValueError, TypeError, http.client.HTTPException, UnicodeError):
        raise HTTPException(502, "zernio_unavailable") from None
    finally:
        connection.close()


def auth_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise HTTPException(502, "zernio_invalid_connection")
    try:
        parsed = urlparse(value)
        allowed = ("zernio.com", "facebook.com", "instagram.com", "tiktok.com")
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == root or host.endswith("." + root) for root in allowed)
        ):
            raise ValueError
    except ValueError:
        raise HTTPException(502, "zernio_invalid_connection") from None
    return value


def identifier(value):
    if isinstance(value, dict):
        return value.get("_id") or value.get("id")
    return value


def text(value, maximum=160):
    return value[:maximum] if isinstance(value, str) else ""
