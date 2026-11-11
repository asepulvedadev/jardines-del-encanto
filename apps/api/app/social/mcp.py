"""Fixed-host OAuth/PKCE client and a read-only, bounded MCP connection probe.

This is deliberately not a general tool gateway. OAuth bearer tokens belong only
to the MCP resource, never to the existing REST adapter or the Hermes runtime.
"""

import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import time
from urllib.parse import urlencode

from fastapi import HTTPException

from ..crm import security
from . import config
from .provider import PLATFORMS
from .transport import https_connection

ISSUER = "https://zernio.com"
ENDPOINT = "https://mcp.zernio.com/mcp"
AUTHORIZE = ISSUER + "/oauth/authorize"
TOKEN = ISSUER + "/api/oauth/token"
REGISTER = ISSUER + "/api/oauth/register"
SCOPE = "accounts:read"
MAX_RESPONSE = 256 * 1024
PROTOCOL = "2025-06-18"
DASHBOARD_URL = "https://zernio.com/dashboard"
# Core account text does not carry project/profile ownership; unsupported app
# channels are counted and validated but never imported into the profile ledger.
KNOWN_PLATFORMS = PLATFORMS | frozenset(
    {
        "twitter",
        "linkedin",
        "bluesky",
        "youtube",
        "pinterest",
        "threads",
        "reddit",
        "snapchat",
        "discord",
        "slack",
        "shopify",
        "wordpress",
        "googlebusiness",
        "google",
        "microsoft",
        "email",
        "imessage",
    }
)
MAX_ACCOUNTS = 100
MAX_ACCOUNT_TEXT = 32768
PATHS = {
    ("zernio.com", "/.well-known/oauth-authorization-server", "GET"),
    ("zernio.com", "/api/oauth/register", "POST"),
    ("zernio.com", "/api/oauth/token", "POST"),
    ("mcp.zernio.com", "/mcp", "POST"),
}


def enabled():
    return os.getenv("ZERNIO_MCP_OAUTH_ENABLED") == "1"


def require_enabled():
    if not enabled():
        raise HTTPException(503, "zernio_mcp_disabled")


def load():
    return config.read_private("mcp.json", 65536) or {}


def store(data):
    config.store_private("mcp.json", data)


def usable_grant(data):
    tokens = data.get("tokens") or {}
    if not isinstance(tokens, dict) or data.get("needs_authorization"):
        return False
    expiry = tokens.get("expires_at", 0)
    valid_expiry = isinstance(expiry, (int, float)) and not isinstance(expiry, bool)
    return bool(
        printable(tokens.get("access_token"))
        and valid_expiry
        and (expiry > time.time() or printable(tokens.get("refresh_token")))
    )


def verified_snapshot(data):
    tokens = data.get("tokens") or {}
    snapshot = data.get("account_observations") or {}
    expiry = tokens.get("expires_at", 0) if isinstance(tokens, dict) else 0
    return bool(
        enabled()
        and usable_grant(data)
        and isinstance(expiry, (int, float))
        and expiry > time.time()
        and isinstance(snapshot, dict)
        and data.get("grant_generation")
        and snapshot.get("generation") == data["grant_generation"]
        and data.get("verified_at")
        and snapshot.get("verified_at") == data["verified_at"]
    )


def status(data=None):
    data = load() if data is None else data
    tokens = data.get("tokens") or {}
    return {
        "available": enabled(),
        "transport": "mcp",
        "authentication": "oauth_pkce",
        "authorized": bool(tokens),
        "scope": SCOPE,
        "verified_at": data.get("verified_at") if verified_snapshot(data) else None,
        "needs_authorization": bool(
            data.get("needs_authorization") or (tokens and not usable_grant(data))
        ),
        "hermes_connected": False,
    }


def channel_state():
    """Sanitized observations of a grant, never ownership of a project profile."""
    try:
        data = load()
    except HTTPException as error:
        if error.detail != "zernio_not_configured":
            raise
        data = {}
    public = status(data)
    oauth = {
        key: public[key]
        for key in ("available", "authorized", "needs_authorization", "verified_at")
    }
    snapshot = data.get("account_observations") or {}
    same_grant = (
        isinstance(snapshot, dict)
        and data.get("grant_generation")
        and snapshot.get("generation") == data["grant_generation"]
    )
    accounts = snapshot.get("accounts", []) if same_grant else []
    if not isinstance(accounts, list) or len(accounts) > MAX_ACCOUNTS:
        raise HTTPException(503, "zernio_configuration_unavailable")
    connected = verified_snapshot(data)
    entries = []
    for account in accounts:
        if (
            not isinstance(account, dict)
            or account.get("platform") not in PLATFORMS
            or not isinstance(account.get("id"), str)
            or not re.fullmatch(r"[a-f0-9]{24}", account["id"])
            or not isinstance(account.get("username"), str)
            or not 1 <= len(account["username"]) <= 160
        ):
            raise HTTPException(503, "zernio_configuration_unavailable")
        entries.append(
            {
                "id": account["id"],
                "platform": account["platform"],
                "username": account["username"],
                "display_name": account["username"],
                "status": "connected" if connected else "unverified",
                "connected_at": None,
                "source": "oauth",
            }
        )
    return {
        "oauth": oauth,
        "connections": entries,
        "can_sync": bool(enabled() and usable_grant(data)),
        "observed_at": snapshot.get("verified_at") if same_grant else None,
        "warning": (
            "oauth_verification_required"
            if accounts and not connected
            else "oauth_unsupported_platforms_filtered"
            if same_grant and snapshot.get("filtered_count")
            else None
        ),
    }


def parse_accounts(result):
    """Accept only the documented core accounts_list text, with exact completeness."""

    def invalid():
        raise HTTPException(502, "zernio_mcp_verification_failed")

    content = result.get("content")
    if (
        result.get("isError")
        or not isinstance(content, list)
        or not 1 <= len(content) <= 8
        or any(
            not isinstance(part, dict)
            or part.get("type") != "text"
            or not isinstance(part.get("text"), str)
            for part in content
        )
    ):
        invalid()
    text = "\n".join(part["text"] for part in content).strip()
    if len(text.encode()) > MAX_ACCOUNT_TEXT:
        invalid()
    if text in (
        "No accounts connected",
        "No accounts connected.",
        "No accounts connected. Connect accounts at https://zernio.com",
    ):
        return [], 0
    lines = [line for line in text.splitlines() if line.strip()]
    header = (
        re.fullmatch(r"Found ([1-9][0-9]{0,2}) connected account(?:\(s\)|s)?:", lines[0])
        if lines
        else None
    )
    if not header or not 1 <= int(header[1]) <= MAX_ACCOUNTS or len(lines) != int(header[1]) + 1:
        invalid()
    seen, accounts, filtered = set(), [], 0
    for line in lines[1:]:
        match = re.fullmatch(
            r"- ([a-z][a-z0-9_]{0,31}): ([^\r\n]{1,160}) \(ID: ([a-fA-F0-9]{24})\)", line
        )
        if not match or match[1] not in KNOWN_PLATFORMS:
            invalid()
        platform, username, account_id = match[1], match[2], match[3].lower()
        if account_id in seen or any(ord(char) < 32 or ord(char) == 127 for char in username):
            invalid()
        seen.add(account_id)
        if platform in PLATFORMS:
            accounts.append({"id": account_id, "platform": platform, "username": username})
        else:
            filtered += 1
    return accounts, filtered


def exchange(host, path, method="GET", payload=None, headers=None):
    """No redirects, arbitrary endpoints, ambient proxy settings or vendor error bodies."""
    if (host, path, method) not in PATHS:
        raise HTTPException(502, "zernio_mcp_unavailable")
    try:
        connection = https_connection(host, timeout=3)
    except (OSError, ValueError, http.client.HTTPException):
        raise HTTPException(502, "zernio_mcp_unavailable") from None
    headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
    body = None
    if payload is not None:
        form = path == "/api/oauth/token"
        body = urlencode(payload).encode() if form else json.dumps(payload).encode()
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        # read1 avoids waiting for a persistent SSE connection to close. Bound
        # both bytes and event count, and stop at the first complete SSE frame.
        raw = b""
        sse = response.getheader("Content-Type", "").startswith("text/event-stream")
        deadline = time.monotonic() + 4
        while len(raw) <= MAX_RESPONSE:
            chunk = response.read1(min(8192, MAX_RESPONSE + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
            if sse and (b"\n\n" in raw or b"\r\n\r\n" in raw):
                break
            if time.monotonic() > deadline:
                raise ValueError
        if len(raw) > MAX_RESPONSE:
            raise ValueError
        result_headers = {"session": response.getheader("Mcp-Session-Id")}
        if response.status not in {200, 201, 202}:
            return response.status, {}, {}
        if response.status == 202:
            return 202, result_headers, {}
        text = raw.decode()
        if sse:
            text = "\n".join(
                line[5:].lstrip() for line in text.splitlines() if line.startswith("data:")
            )
        data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError
        return response.status, result_headers, data
    except (OSError, ValueError, TypeError, UnicodeError, http.client.HTTPException):
        raise HTTPException(502, "zernio_mcp_unavailable") from None
    finally:
        connection.close()


def begin(admin, replace):
    require_enabled()
    callback = security.origin() + "/crm?zernio_callback=1"
    with config.locked():
        data = load()
        if data.get("tokens") and not replace:
            raise HTTPException(409, "zernio_replacement_confirmation_required")
        pending = data.get("pending") or {}
        if pending.get("expires_at", 0) - 540 > time.time():
            raise HTTPException(429, "zernio_mcp_throttled")
        code, _, meta = exchange("zernio.com", "/.well-known/oauth-authorization-server")
        expected = {
            "issuer": ISSUER,
            "authorization_endpoint": AUTHORIZE,
            "token_endpoint": TOKEN,
            "registration_endpoint": REGISTER,
        }
        if (
            code != 200
            or any(meta.get(k) != v for k, v in expected.items())
            or "S256" not in meta.get("code_challenge_methods_supported", [])
            or SCOPE not in meta.get("scopes_supported", [])
        ):
            raise HTTPException(502, "zernio_mcp_metadata_invalid")
        client = data.get("registration") or data.get("client")
        if not client or client.get("redirect_uri") != callback:
            code, _, registered = exchange(
                "zernio.com",
                "/api/oauth/register",
                "POST",
                {
                    "client_name": "Jardines del Encanto CRM",
                    "redirect_uris": [callback],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                    "scope": SCOPE,
                },
            )
            client_id = registered.get("client_id")
            if (
                code not in {200, 201}
                or not printable(client_id, 2048)
                or registered.get("token_endpoint_auth_method", "none") != "none"
            ):
                raise HTTPException(502, "zernio_mcp_registration_failed")
            client = {"id": client_id, "redirect_uri": callback}
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        data["registration"] = client
        data["pending"] = {
            "state_hash": security.digest(state),
            "verifier": verifier,
            "session_hash": admin["token_hash"],
            "actor": str(admin["id"]),
            "expires_at": time.time() + 600,
            "client": client,
        }
        store(data)
    return {
        "auth_url": AUTHORIZE
        + "?"
        + urlencode(
            {
                "client_id": client["id"],
                "redirect_uri": callback,
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge.decode().rstrip("="),
                "code_challenge_method": "S256",
                "resource": ENDPOINT,
            }
        )
    }


def printable(value, maximum=8192):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and all(33 <= ord(c) <= 126 for c in value)
    )


def validated_tokens(result, previous_refresh=None):
    token = result.get("access_token")
    refresh = result.get("refresh_token", previous_refresh)
    expiry = result.get("expires_in")
    if (
        not printable(token)
        or (refresh is not None and not printable(refresh))
        or str(result.get("token_type", "")).lower() != "bearer"
        or not isinstance(expiry, int)
        or isinstance(expiry, bool)
        or not 1 <= expiry <= 604800
        or result.get("scope", SCOPE) != SCOPE
    ):
        raise HTTPException(502, "zernio_mcp_invalid_token")
    return {"access_token": token, "refresh_token": refresh, "expires_at": time.time() + expiry}


def complete(admin, state, code, issuer, error):
    require_enabled()
    with config.locked():
        data = load()
        pending = data.get("pending") or {}
        if (
            not printable(state, 128)
            or not hmac.compare_digest(pending.get("state_hash", ""), security.digest(state))
            or pending.get("session_hash") != admin["token_hash"]
            or pending.get("actor") != str(admin["id"])
            or pending.get("expires_at", 0) <= time.time()
        ):
            raise HTTPException(409, "zernio_mcp_invalid_state")
        # Consume before exchange: failures and retries cannot replay the code.
        del data["pending"]
        store(data)
        if error:
            raise HTTPException(400, "zernio_mcp_denied")
        if issuer != ISSUER or not printable(code, 4096):
            raise HTTPException(400, "zernio_mcp_invalid_callback")
        client = pending["client"]
        status_code, _, result = exchange(
            "zernio.com",
            "/api/oauth/token",
            "POST",
            {
                "grant_type": "authorization_code",
                "client_id": client["id"],
                "code": code,
                "code_verifier": pending["verifier"],
                "redirect_uri": client["redirect_uri"],
                "resource": ENDPOINT,
            },
        )
        if status_code != 200:
            raise HTTPException(502, "zernio_mcp_token_failed")
        data["tokens"] = validated_tokens(result)
        data["grant_generation"] = secrets.token_urlsafe(24)
        data.pop("account_observations", None)
        data["client"] = client
        data.pop("verified_at", None)
        data.pop("needs_authorization", None)
        store(data)
        return status(data)


def access_token(data):
    """Caller holds the shared configuration lock, including refresh rotation."""
    tokens = data.get("tokens") or {}
    if not tokens or data.get("needs_authorization"):
        raise HTTPException(409, "zernio_mcp_sign_in_required")
    if tokens["expires_at"] > time.time() + 60:
        return tokens["access_token"]
    refresh = tokens.get("refresh_token")
    if not refresh:
        data["needs_authorization"] = True
        data.pop("verified_at", None)
        store(data)
        raise HTTPException(409, "zernio_mcp_sign_in_required")
    code, _, result = exchange(
        "zernio.com",
        "/api/oauth/token",
        "POST",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": data["client"]["id"],
            "resource": ENDPOINT,
        },
    )
    if code != 200:
        if code in {400, 401, 403}:
            data["needs_authorization"] = True
            data.pop("verified_at", None)
            store(data)
            raise HTTPException(409, "zernio_mcp_sign_in_required")
        raise HTTPException(502, "zernio_mcp_unavailable")
    data["tokens"] = validated_tokens(result, refresh)
    # A refreshed access token is not a successful new account observation.
    data.pop("verified_at", None)
    store(data)
    return data["tokens"]["access_token"]


def rpc_allowed(method, params):
    allowed = method in {"initialize", "notifications/initialized"} or (
        method == "tools/call" and params == {"name": "accounts_list", "arguments": {}}
    )
    if not allowed:
        raise HTTPException(403, "zernio_mcp_tool_not_allowed")


def rpc(token, method, params=None, session=None, request_id=1):
    rpc_allowed(method, params)
    headers = {"Authorization": "Bearer " + token, "MCP-Protocol-Version": PROTOCOL}
    if session:
        if not printable(session, 256):
            raise HTTPException(502, "zernio_mcp_unavailable")
        headers["Mcp-Session-Id"] = session
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if not method.startswith("notifications/"):
        body["id"] = request_id
    code, returned, result = exchange("mcp.zernio.com", "/mcp", "POST", body, headers)
    if code in {401, 403}:
        raise HTTPException(409, "zernio_mcp_sign_in_required")
    if method.startswith("notifications/") and code in {200, 202}:
        return {}, session
    if (
        code != 200
        or result.get("jsonrpc") != "2.0"
        or result.get("id") != request_id
        or "error" in result
        or not isinstance(result.get("result"), dict)
    ):
        raise HTTPException(502, "zernio_mcp_unavailable")
    return result["result"], returned.get("session") or session


def check():
    require_enabled()
    with config.locked():
        data = load()
        try:
            token = access_token(data)
            result, session = rpc(
                token,
                "initialize",
                {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "jardines-crm", "version": "1.0.0"},
                },
            )
            if result.get("protocolVersion") != PROTOCOL:
                raise HTTPException(502, "zernio_mcp_protocol_unsupported")
            rpc(token, "notifications/initialized", session=session)
            result, _ = rpc(
                token,
                "tools/call",
                {"name": "accounts_list", "arguments": {}},
                session=session,
                request_id=2,
            )
            accounts, filtered = parse_accounts(result)
            verified_at = int(time.time())
            generation = data.get("grant_generation") or secrets.token_urlsafe(24)
            snapshot = {
                "generation": generation,
                "verified_at": verified_at,
                "accounts": accounts,
                "filtered_count": filtered,
            }
            candidate = {
                **data,
                "grant_generation": generation,
                "account_observations": snapshot,
                "verified_at": verified_at,
            }
            # store_private uses JSON ASCII escaping; honor its on-disk read bound too.
            if len(json.dumps(candidate)) > 65536:
                raise HTTPException(502, "zernio_mcp_verification_failed")
            data.update(candidate)
            store(data)
        except HTTPException as error:
            data.pop("verified_at", None)
            if error.detail == "zernio_mcp_sign_in_required":
                data["needs_authorization"] = True
            store(data)
            raise
        return status(data)


def disconnect():
    with config.locked():
        previous = load()
        registration = previous.get("registration") or previous.get("client")
        data = {"registration": registration} if registration else {}
        store(data)
        return status(data)
