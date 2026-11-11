"""OAuth/MCP boundary tests use a fake issuer; no external accounts or tokens."""

import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.social import config


@pytest.fixture
def oauth(monkeypatch, tmp_path):
    from app.social import mcp

    monkeypatch.setenv("ZERNIO_CONFIG_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("ZERNIO_MCP_OAUTH_ENABLED", "1")
    monkeypatch.setenv("CRM_ORIGIN", "http://127.0.0.1:4320")
    monkeypatch.setenv("CRM_ALLOW_INSECURE_HTTP", "1")
    calls = []

    def exchange(host, path, method="GET", payload=None, headers=None):
        calls.append((host, path, method, payload, headers))
        if path == "/.well-known/oauth-authorization-server":
            return (
                200,
                {},
                {
                    "issuer": mcp.ISSUER,
                    "authorization_endpoint": mcp.AUTHORIZE,
                    "token_endpoint": mcp.TOKEN,
                    "registration_endpoint": mcp.REGISTER,
                    "code_challenge_methods_supported": ["S256"],
                    "scopes_supported": ["accounts:read"],
                },
            )
        if path == "/api/oauth/register":
            return 201, {}, {"client_id": "test-client", "token_endpoint_auth_method": "none"}
        if path == "/api/oauth/token":
            return (
                200,
                {},
                {
                    "access_token": "private-access",
                    "refresh_token": "private-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "accounts:read",
                },
            )
        raise AssertionError((host, path))

    monkeypatch.setattr(mcp, "exchange", exchange)
    return mcp, calls


def begin(mcp, admin="session-one"):
    result = mcp.begin({"token_hash": admin, "id": "admin-one"}, False)
    return parse_qs(urlparse(result["auth_url"]).query)


def test_browser_authorization_uses_pkce_and_private_single_use_state(oauth):
    mcp, calls = oauth
    query = begin(mcp)
    assert query["scope"] == ["accounts:read"]
    assert query["resource"] == [mcp.ENDPOINT]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://127.0.0.1:4320/crm?zernio_callback=1"]
    assert "code_verifier" not in query
    pending = mcp.load()["pending"]
    assert pending["state_hash"] == hashlib.sha256(query["state"][0].encode()).hexdigest()
    assert mcp.status()["authorized"] is False
    with pytest.raises(HTTPException) as failure:
        mcp.complete(
            {"token_hash": "another-session", "id": "admin-one"},
            query["state"][0],
            "code",
            mcp.ISSUER,
            None,
        )
    assert failure.value.status_code == 409
    mcp.complete(
        {"token_hash": "session-one", "id": "admin-one"},
        query["state"][0],
        "code",
        mcp.ISSUER,
        None,
    )
    token_call = calls[-1]
    assert token_call[3]["code_verifier"] == pending["verifier"]
    assert "private-access" not in str(mcp.status())
    assert "private-refresh" not in str(mcp.status())
    assert mcp.status()["authorized"] is True
    assert (config.directory() / "mcp.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(HTTPException):
        mcp.complete(
            {"token_hash": "session-one", "id": "admin-one"},
            query["state"][0],
            "code",
            mcp.ISSUER,
            None,
        )


@pytest.mark.parametrize("case", ["expired", "issuer", "state", "denied"])
def test_invalid_callback_does_not_exchange_or_replace_existing_grant(oauth, case):
    mcp, calls = oauth
    query = begin(mcp)
    if case == "expired":
        with config.locked():
            data = mcp.load()
            data["pending"]["expires_at"] = time.time() - 1
            mcp.store(data)
    count = len(calls)
    with pytest.raises(HTTPException):
        mcp.complete(
            {"token_hash": "session-one", "id": "admin-one"},
            "wrong" if case == "state" else query["state"][0],
            "code",
            "https://evil.invalid" if case == "issuer" else mcp.ISSUER,
            "access_denied" if case == "denied" else None,
        )
    assert len(calls) == count
    assert mcp.status()["authorized"] is False


def test_discovery_cannot_redirect_token_or_registration_to_other_hosts(oauth, monkeypatch):
    mcp, calls = oauth
    original = mcp.exchange

    def malicious(*args, **kwargs):
        code, headers, data = original(*args, **kwargs)
        data["token_endpoint"] = "https://evil.invalid/collect"
        return code, headers, data

    monkeypatch.setattr(mcp, "exchange", malicious)
    with pytest.raises(HTTPException):
        begin(mcp)
    assert len(calls) == 1


def test_mcp_read_verification_is_bounded_and_does_not_expose_generic_execution(oauth, monkeypatch):
    mcp, _ = oauth
    query = begin(mcp)
    mcp.complete(
        {"token_hash": "session-one", "id": "admin-one"},
        query["state"][0],
        "code",
        mcp.ISSUER,
        None,
    )
    calls = []

    def rpc(token, method, params=None, session=None, request_id=1):
        calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": "2025-06-18"}, "opaque-session"
        if method == "notifications/initialized":
            return {}, session
        return {
            "content": [
                {
                    "type": "text",
                    "text": "No accounts connected. Connect accounts at https://zernio.com",
                }
            ]
        }, session

    monkeypatch.setattr(mcp, "rpc", rpc)
    assert mcp.check()["verified_at"] is not None
    assert calls[-1] == ("tools/call", {"name": "accounts_list", "arguments": {}})
    with pytest.raises(HTTPException):
        mcp.rpc_allowed("tools/call", {"name": "posts_publish_now", "arguments": {}})
    assert mcp.status()["scope"] == "accounts:read"
    mcp.disconnect()
    assert mcp.status()["authorized"] is False
    assert "private-access" not in (config.directory() / "mcp.json").read_text()


def test_refresh_rotation_is_private_and_failed_refresh_requires_sign_in(oauth, monkeypatch):
    mcp, calls = oauth
    query = begin(mcp)
    mcp.complete(
        {"token_hash": "session-one", "id": "admin-one"},
        query["state"][0],
        "code",
        mcp.ISSUER,
        None,
    )
    with config.locked():
        data = mcp.load()
        data["tokens"]["expires_at"] = 0
        mcp.store(data)
        assert mcp.access_token(data) == "private-access"
    assert calls[-1][3]["grant_type"] == "refresh_token"
    assert calls[-1][3]["refresh_token"] == "private-refresh"
    with config.locked():
        data = mcp.load()
        data["tokens"]["expires_at"] = 0
        mcp.store(data)
        monkeypatch.setattr(mcp, "exchange", lambda *args: (400, {}, {}))
        with pytest.raises(HTTPException) as failure:
            mcp.access_token(data)
        assert failure.value.detail == "zernio_mcp_sign_in_required"
    assert mcp.status()["needs_authorization"] is True


def test_replacement_requires_confirmation_and_cancellation_keeps_previous_grant(oauth):
    mcp, _ = oauth
    admin = {"token_hash": "session-one", "id": "admin-one"}
    query = begin(mcp)
    mcp.complete(admin, query["state"][0], "code", mcp.ISSUER, None)
    original = mcp.load()["tokens"]
    with pytest.raises(HTTPException) as failure:
        begin(mcp)
    assert failure.value.status_code == 409
    result = mcp.begin(admin, True)
    state = parse_qs(urlparse(result["auth_url"]).query)["state"][0]
    with pytest.raises(HTTPException):
        mcp.complete(admin, state, None, None, "access_denied")
    assert mcp.load()["tokens"] == original


def test_rpc_only_sends_resource_tokens_to_pinned_mcp_host(oauth, monkeypatch):
    mcp, _ = oauth
    calls = []

    def exchange(host, path, method, payload, headers):
        calls.append((host, path, payload, headers))
        return (
            200,
            {"session": "session-id"},
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"protocolVersion": mcp.PROTOCOL},
            },
        )

    monkeypatch.setattr(mcp, "exchange", exchange)
    _, session = mcp.rpc("test-token", "initialize", {})
    assert session == "session-id"
    assert calls[0][:2] == ("mcp.zernio.com", "/mcp")
    assert calls[0][3]["Authorization"] == "Bearer test-token"
    for method in ["tools/list", "resources/read", "prompts/get", "anything"]:
        with pytest.raises(HTTPException):
            mcp.rpc("test-token", method, {})
    assert len(calls) == 1


def test_private_store_and_rest_credentials_remain_independent(oauth):
    mcp, _ = oauth
    legacy = {
        "api_key": "legacy-key",
        "profile_id": "a" * 24,
        "profile_name": "Jardines",
        "webhook_secret": "webhook-secret",
    }
    with config.locked():
        config.store(legacy)
    begin(mcp)
    mcp.disconnect()
    assert config.load() == legacy
