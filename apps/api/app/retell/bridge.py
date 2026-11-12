"""Fixed private authenticated transport, without redirects or ambient proxies."""

import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import HTTPException


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def base_url():
    value = os.getenv("RETELL_GATEWAY_URL", "").rstrip("/")
    try:
        p = urlparse(value)
        loopback = (
            os.getenv("CRM_ALLOW_INSECURE_HTTP") == "1"
            and p.scheme == "http"
            and p.hostname in ("127.0.0.1", "localhost")
            and p.port
            and not any((p.path, p.query, p.fragment, p.username, p.password))
        )
        return value if value == "http://retell-gateway:8093" or loopback else None
    except ValueError:
        return None


def request(path, body=None, timeout=3):
    if path not in {
        "/state",
        "/configure",
        "/disconnect",
        "/catalog",
        "/execute",
        "/schema",
        "/prepare",
    } and not re.fullmatch(r"/sessions/[0-9a-f-]{36}/claim", path):
        raise HTTPException(503, "retell_unavailable")
    if (path == "/state") != (body is None):
        raise HTTPException(503, "retell_unavailable")
    try:
        base = base_url()
        if not base:
            raise ValueError
        token = Path(os.environ["RETELL_GATEWAY_TOKEN_FILE"]).read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ValueError
        raw = json.dumps(body, allow_nan=False).encode() if body is not None else None
        if raw and len(raw) > 128 * 1024:
            raise ValueError
        req = Request(
            base + path,
            data=raw,
            method="POST" if body is not None else "GET",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
            content = response.read(3 * 1024 * 1024 + 1)
            if len(content) > 3 * 1024 * 1024:
                raise ValueError
            value = json.loads(content)
            if not isinstance(value, dict):
                raise TypeError
            return value
    except HTTPError as error:
        if error.code == 409:
            raise HTTPException(409, "retell_provider_changed") from None
        raise HTTPException(503, "retell_unavailable") from None
    except (URLError, OSError, ValueError, TypeError, KeyError, TimeoutError):
        raise HTTPException(503, "retell_unavailable") from None
