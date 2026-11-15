"""Fixed-host, bounded JSON transport. Never retry an ambiguous external write."""

import http.client
import json
from urllib.parse import quote, urlencode

from fastapi import HTTPException

from ..social.transport import https_connection

MAX_RESPONSE = 2 * 1024 * 1024


def route(operation, args):
    path = operation["path"]
    for name, value in args["path"].items():
        path = path.replace("{" + name + "}", quote(str(value), safe=""))
    if "{" in path or not path.startswith("/v1/inbox/"):
        raise HTTPException(422, "inbox_input_invalid")
    if args["query"]:
        path += "?" + urlencode(
            {k: str(v).lower() if isinstance(v, bool) else v for k, v in args["query"].items()}
        )
    return path


def request(credentials, operation, args, key=None):
    method = operation["method"]
    path = route(operation, args)
    sending = method != "GET"
    connection = None
    try:
        connection = https_connection("zernio.com", timeout=12)
        headers = {
            "Authorization": "Bearer " + credentials["api_key"],
            "Accept": "application/json",
        }
        if key:
            headers["Idempotency-Key"] = str(key)
        body = None
        if args["body"]:
            body = json.dumps(args["body"], allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        connection.request(method, "/api" + path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if not 200 <= response.status < 300:
            # Do not expose raw vendor errors or credentials; only a finite code set.
            code = "inbox_provider_rejected"
            if response.status == 429:
                code = "inbox_rate_limited"
            elif response.status in (401, 402, 403):
                code = "inbox_provider_permission"
            elif response.status >= 500 or response.status in (408, 409):
                code = "inbox_delivery_unknown" if sending else "inbox_provider_unavailable"
            raise HTTPException(502 if code == "inbox_delivery_unknown" else 409, code)
        if response.status == 204:
            return {"success": True}
        if len(raw) > MAX_RESPONSE or "application/json" not in response.getheader(
            "Content-Type", ""
        ):
            raise ValueError
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise TypeError
        if result.get("success") is False or result.get("status") in {"error", "failed"}:
            raise HTTPException(409, "inbox_provider_rejected")
        return scrub(result, credentials)
    except (OSError, http.client.HTTPException, ValueError, TypeError, UnicodeError):
        raise HTTPException(
            502, "inbox_delivery_unknown" if sending else "inbox_provider_unavailable"
        ) from None
    finally:
        if connection is not None:
            connection.close()


def scrub(value, credentials, depth=0):
    if depth > 25:
        return None
    if isinstance(value, dict):
        return {
            k: scrub(v, credentials, depth + 1)
            for k, v in value.items()
            if not any(
                s in k.lower()
                for s in (
                    "access_token",
                    "refresh_token",
                    "api_key",
                    "authorization",
                    "secret",
                    "password",
                )
            )
            and k not in {"error", "platformError", "stack", "headers"}
        }
    if isinstance(value, list):
        return [scrub(item, credentials, depth + 1) for item in value[:1000]]
    if isinstance(value, str):
        return value.replace(credentials["api_key"], "[redacted]")[:32000]
    return value
