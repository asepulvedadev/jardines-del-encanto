"""Fixed vendor routes; bounded IO and no retries of any remote mutation."""

import http.client
import json
import re

from fastapi import HTTPException

from ..social.transport import https_connection

_ALLOWED = re.compile(
    r"^/v1/(?:whatsapp/templates\?accountId=[a-zA-Z0-9_-]{1,160}&status=APPROVED|contacts/bulk|broadcasts(?:/[a-f0-9]{24}(?:/recipients(?:\?limit=100&skip=[0-9]{1,4})?|/send)?)?)$"
)


def request(credentials, method, path, payload=None):
    if not _ALLOWED.fullmatch(path) or method not in {"GET", "POST"}:
        raise HTTPException(422, "broadcast_invalid_route")
    connection = None
    try:
        connection = https_connection("zernio.com", timeout=8)
        headers = {
            "Authorization": "Bearer " + credentials["api_key"],
            "Accept": "application/json",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        connection.request(method, "/api" + path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if not 200 <= response.status < 300:
            code = (
                "broadcast_unknown"
                if method != "GET" and (response.status >= 500 or response.status in (408, 409))
                else "broadcast_provider_rejected"
            )
            raise HTTPException(502, code)
        if len(raw) > 2 * 1024 * 1024 or "application/json" not in response.getheader(
            "Content-Type", ""
        ):
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ValueError
        return data
    except (OSError, ValueError, TypeError, UnicodeError, http.client.HTTPException):
        raise HTTPException(
            502, "broadcast_unknown" if method != "GET" else "broadcast_unavailable"
        ) from None
    finally:
        if connection:
            connection.close()
