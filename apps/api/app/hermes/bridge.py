"""Fixed private Hermes transport. Never accepts user-selected destinations."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import HTTPException


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bridge_url():
    value = os.getenv("HERMES_BRIDGE_URL", "").rstrip("/")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    fixed = value == "http://hermes-bridge:8081"
    loopback = (
        parsed.scheme == "http"
        and parsed.hostname in ("127.0.0.1", "localhost")
        and port
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )
    return value if fixed or loopback else None


def request(path, body=None, timeout=3):
    base = bridge_url()
    if not base:
        raise HTTPException(503, "hermes_unavailable")
    raw = json.dumps(body).encode() if body is not None else None
    req = Request(
        base + path,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
            data = response.read(262145)
            if len(data) > 262144:
                raise ValueError
            result = json.loads(data)
            if not isinstance(result, dict):
                raise TypeError
            return result
    except (HTTPError, URLError, OSError, ValueError, TypeError, TimeoutError):
        raise HTTPException(503, "hermes_unavailable") from None


def health():
    configured = bool(bridge_url())
    result = {"configured": configured, "available": False, "model": None}
    if configured:
        try:
            state = request("/health", timeout=2)
            result["available"] = state.get("available") is True
            model = state.get("model")
            result["model"] = model[:100] if isinstance(model, str) else None
            if type(state.get("history_available")) is bool:
                result["history_available"] = result["available"] and state["history_available"]
            if type(state.get("transcription_available")) is bool:
                result["transcription_available"] = (
                    result["available"] and state["transcription_available"]
                )
        except HTTPException:
            pass
    return result
