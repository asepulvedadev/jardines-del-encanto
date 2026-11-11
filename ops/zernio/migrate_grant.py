"""Owner-run, stdin-only import of one existing project OAuth grant.

Never route this module through HTTP, Hermes, deployment CI or an MCP tool.
Run inside the destination API container; input must be an encrypted SSH pipe.
"""

import json
import math
import secrets
import sys
import time
from urllib.parse import urlsplit

MAXIMUM = 65536


def printable(value, maximum=8192):
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and all(33 <= ord(char) <= 126 for char in value)
    )


def durable_grant(data):
    if not isinstance(data, dict) or data.get("needs_authorization"):
        raise ValueError("Invalid source grant")
    client, tokens = data.get("client"), data.get("tokens")
    if not isinstance(client, dict) or not isinstance(tokens, dict):
        raise ValueError("Missing source grant")
    callback = client.get("redirect_uri")
    try:
        url = urlsplit(callback) if isinstance(callback, str) else None
        callback_valid = (
            url
            and (
                (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"})
                or (
                    url.scheme == "https"
                    and url.hostname == "jardines.2.24.111.40.sslip.io"
                )
            )
            and url.path == "/crm"
            and url.query == "zernio_callback=1"
            and not (url.username or url.password or url.fragment)
        )
    except ValueError:
        callback_valid = False
    expiry = tokens.get("expires_at")
    refresh = tokens.get("refresh_token")
    if not (
        printable(client.get("id"), 2048)
        and callback_valid
        and printable(tokens.get("access_token"))
        and (refresh is None or printable(refresh))
        and isinstance(expiry, (int, float))
        and not isinstance(expiry, bool)
        and math.isfinite(expiry)
        and expiry > 0
        and (expiry > time.time() + 60 or refresh)
    ):
        raise ValueError("Invalid source grant")
    return {
        "client": {"id": client["id"], "redirect_uri": callback},
        "tokens": {
            "access_token": tokens["access_token"],
            "refresh_token": refresh,
            "expires_at": expiry,
        },
    }


def import_grant(raw, config):
    if len(raw) > MAXIMUM:
        raise ValueError("Oversized grant")
    data = durable_grant(json.loads(raw))
    with config.locked():
        existing = config.read_private("mcp.json", MAXIMUM) or {}
        if existing.get("tokens") or existing.get("pending"):
            raise ValueError("Destination already has authorization")
        data["grant_generation"] = secrets.token_urlsafe(24)
        config.store_private("mcp.json", data)
    return {"imported": True, "requires_verification": True}


def main():
    from app.social import config

    try:
        result = import_grant(sys.stdin.buffer.read(MAXIMUM + 1), config)
    except Exception:
        print("OAuth grant import refused", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
