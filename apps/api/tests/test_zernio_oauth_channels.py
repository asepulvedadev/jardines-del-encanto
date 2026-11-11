"""Keyless channel observations use fake grants/provider responses and isolated CRM data."""

# ruff: noqa: F811
import json
import time
from urllib.parse import parse_qs, urlparse

import psycopg
import pytest
from fastapi import HTTPException
from test_social import client, configured  # noqa: F401
from test_zernio_mcp import begin, oauth  # noqa: F401

from app.social import config, mcp, routes


def authorized(oauth):
    mcp, _ = oauth
    query = begin(mcp)
    mcp.complete(
        {"token_hash": "session-one", "id": "admin-one"},
        query["state"][0],
        "code",
        mcp.ISSUER,
        None,
    )
    return mcp


def account_probe(monkeypatch, mcp, text=None):
    calls = []

    def rpc(token, method, params=None, session=None, request_id=1):
        calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": mcp.PROTOCOL}, "fixture-session"
        if method == "notifications/initialized":
            return {}, session
        return {
            "content": [
                {
                    "type": "text",
                    "text": text
                    or (
                        "Found 1 connected account(s):\n\n- whatsapp: Jardines (ID: "
                        + "a" * 24
                        + ")"
                    ),
                }
            ]
        }, session

    monkeypatch.setattr(mcp, "rpc", rpc)
    return calls


def test_oauth_only_whatsapp_observation_appears_without_rest_key(oauth, monkeypatch):
    mcp = authorized(oauth)
    account_probe(monkeypatch, mcp)
    mcp.check()
    state = routes.settings()
    assert state["configured"] is False
    assert state["oauth"]["authorized"] is True
    assert state["can_sync"] is True and state["connect_mode"] == "vendor_dashboard"
    assert state["connections"][0]["platform"] == "whatsapp"
    assert state["connections"][0]["status"] == "connected"
    assert state["connections"][0]["source"] == "oauth"
    assert state["profile"] is None
    assert "private-access" not in str(state) and "private-refresh" not in str(state)


def test_oauth_sync_does_not_require_rest_credentials(oauth, monkeypatch):
    mcp = authorized(oauth)
    calls = account_probe(monkeypatch, mcp)
    monkeypatch.setattr("app.control.service.require_social_enabled", lambda *args: None)
    state = routes.sync_settings(routes.EmptyInput(), {"id": "admin-one"})
    assert state["connections"][0]["platform"] == "whatsapp"
    assert calls[-1] == ("tools/call", {"name": "accounts_list", "arguments": {}})


@pytest.mark.parametrize(
    "text",
    [
        "Found 2 connected account(s):\n- whatsapp: Jardines (ID: " + "a" * 24 + ")",
        "Found 1 connected account(s):\n- unsupported: Jardines (ID: " + "a" * 24 + ")",
        "Found 1 connected account(s):\n- whatsapp: Jardines (ID: invalid)",
        "Found 0 connected account(s):",
        "Found 1 connected account(s):\n- whatsapp: Jardines (ID: "
        + "a" * 24
        + ")\nNext page available",
        "Found 2 connected account(s):\n- whatsapp: Jardines (ID: "
        + "a" * 24
        + ")\n- facebook: Other (ID: "
        + "a" * 24
        + ")",
        "Found 101 connected account(s):",
    ],
)
def test_strict_account_parser_rejects_partial_unknown_and_duplicate_rows(text):
    with pytest.raises(HTTPException) as error:
        mcp.parse_accounts({"content": [{"type": "text", "text": text}]})
    assert error.value.detail == "zernio_mcp_verification_failed"


def test_structured_or_oversized_unverified_payload_is_not_guessed():
    for result in (
        {"structuredContent": {"accounts": []}},
        {"isError": True, "content": [{"type": "text", "text": "No accounts connected"}]},
        {"content": [{"type": "image", "data": "ignored"}]},
        {"content": [{"type": "text", "text": "ó" * 20000}]},
    ):
        with pytest.raises(HTTPException):
            mcp.parse_accounts(result)


@pytest.mark.parametrize("vendor_platform", ["linkedin", "phone", "tiktokads"])
def test_supported_rows_are_filtered_only_after_complete_vendor_count_validation(vendor_platform):
    entries, filtered = mcp.parse_accounts(
        {
            "content": [
                {
                    "type": "text",
                    "text": f"Found 2 connected account(s):\n- {vendor_platform}: Fixture (ID: "
                    + "b" * 24
                    + ")\n- whatsapp: Jardines (ID: "
                    + "a" * 24
                    + ")",
                }
            ]
        }
    )
    assert len(entries) == 1 and entries[0]["platform"] == "whatsapp" and filtered == 1


def test_failed_probe_preserves_snapshot_but_cannot_claim_connected(oauth, monkeypatch):
    agent = authorized(oauth)
    account_probe(monkeypatch, agent)
    agent.check()
    before = agent.load()["account_observations"]
    account_probe(
        monkeypatch,
        agent,
        "Found 2 connected account(s):\n- whatsapp: Jardines (ID: " + "a" * 24 + ")",
    )
    with pytest.raises(HTTPException):
        agent.check()
    assert agent.load()["account_observations"] == before
    state = routes.settings()
    assert state["oauth"]["verified_at"] is None
    assert state["connections"][0]["status"] == "unverified"
    assert state["sync_warning"] == "oauth_verification_required"


@pytest.mark.parametrize("case", ["disabled", "expired", "revoked", "changed_grant"])
def test_inactive_or_different_grant_cannot_reuse_verified_observations(oauth, monkeypatch, case):
    agent = authorized(oauth)
    account_probe(monkeypatch, agent)
    agent.check()
    with config.locked():
        data = agent.load()
        if case == "expired":
            data["tokens"]["expires_at"] = time.time() - 1
            data["tokens"].pop("refresh_token")
        elif case == "revoked":
            data["needs_authorization"] = True
        elif case == "changed_grant":
            data["grant_generation"] = "different-grant"
        agent.store(data)
    if case == "disabled":
        monkeypatch.setenv("ZERNIO_MCP_OAUTH_ENABLED", "0")
    state = routes.settings()
    assert state["oauth"]["verified_at"] is None
    assert not any(row["status"] == "connected" for row in state["connections"])
    if case != "changed_grant":
        assert state["can_sync"] is False


def test_revoked_probe_marks_authorization_required_and_unlink_clears_observations(
    oauth, monkeypatch
):
    agent = authorized(oauth)
    account_probe(monkeypatch, agent)
    agent.check()

    def revoked(*args, **kwargs):
        raise HTTPException(409, "zernio_mcp_sign_in_required")

    monkeypatch.setattr(agent, "rpc", revoked)
    with pytest.raises(HTTPException):
        agent.check()
    assert routes.settings()["oauth"]["needs_authorization"] is True
    assert routes.settings()["connections"][0]["status"] == "unverified"
    agent.disconnect()
    assert routes.settings()["connections"] == []
    assert routes.settings()["can_sync"] is False
    assert "private-access" not in json.dumps(agent.load())


def test_empty_account_reply_is_verified_but_does_not_invent_a_connection(oauth, monkeypatch):
    agent = authorized(oauth)
    account_probe(monkeypatch, agent, "No accounts connected")
    agent.check()
    state = routes.settings()
    assert state["oauth"]["verified_at"] is not None
    assert state["connections"] == [] and state["profile"] is None


def test_successful_replacement_discards_previous_grant_observations(oauth, monkeypatch):
    agent = authorized(oauth)
    account_probe(monkeypatch, agent)
    agent.check()
    generation = agent.load()["grant_generation"]
    grant = agent.begin({"token_hash": "session-one", "id": "admin-one"}, True)

    state = parse_qs(urlparse(grant["auth_url"]).query)["state"][0]
    agent.complete(
        {"token_hash": "session-one", "id": "admin-one"}, state, "new-code", agent.ISSUER, None
    )
    assert agent.load()["grant_generation"] != generation
    assert routes.settings()["connections"] == []


@pytest.fixture
def oauth_http(client, oauth):
    session, owner = client
    # Workspace preferences are global, so restore independently of user truncation.
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=(key!='hermes'),version=1")
    try:
        yield session, owner, authorized(oauth)
    finally:
        with psycopg.connect(owner) as db:
            db.execute("UPDATE crm.control_connections SET enabled=(key!='hermes'),version=1")


def test_oauth_http_refresh_control_status_and_vendor_handoff_do_not_write_profile_ledger(
    oauth_http, monkeypatch
):
    session, owner, agent = oauth_http
    account_probe(monkeypatch, agent)
    with psycopg.connect(owner) as db:
        before = db.execute("SELECT count(*) FROM crm.social_connections").fetchone()[0]
    response = session.post("/crm/social/sync", json={})
    assert response.status_code == 200
    assert response.json()["connections"][0]["platform"] == "whatsapp"
    handoff = session.post("/crm/social/connect/whatsapp", json={})
    assert handoff.status_code == 200 and handoff.json() == {
        "mode": "vendor_dashboard",
        "platform": "whatsapp",
        "url": "https://zernio.com/dashboard",
    }
    catalog = session.get("/crm/control/catalog").json()["connections"]
    assert next(row for row in catalog if row["key"] == "zernio")["effective"]
    assert next(row for row in catalog if row["key"] == "whatsapp")["effective"]
    action = session.post("/crm/hermes/actions", json={"action": "social.status"}).json()["result"]
    assert action["connections"][0]["source"] == "oauth"
    proposal = session.post(
        "/crm/hermes/actions",
        json={"action": "social.connect", "arguments": {"platform": "whatsapp"}},
    ).json()["proposals"][0]
    approved = session.post(f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": 1})
    assert approved.json()["result"] == handoff.json()
    assert "intent_id" not in handoff.json()
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.social_connections").fetchone()[0] == before
        assert db.execute("SELECT count(*) FROM crm.social_connection_intents").fetchone()[0] == 0
    assert "private-access" not in response.text and "private-refresh" not in response.text


def test_oauth_pause_csrf_and_revocation_are_enforced(oauth_http, monkeypatch):
    session, _, agent = oauth_http
    account_probe(monkeypatch, agent)
    assert (
        session.post("/crm/social/sync", json={}, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert session.post("/crm/social/sync", json={}).status_code == 200
    assert (
        session.patch(
            "/crm/control/connections/zernio", json={"version": 1, "enabled": False}
        ).status_code
        == 200
    )
    assert session.post("/crm/social/sync", json={}).status_code == 409
    assert session.post("/crm/social/mcp/check", json={}).status_code == 409
    assert session.post("/crm/social/connect/whatsapp", json={}).status_code == 409
    assert session.get("/crm/social/settings").status_code == 200
    assert not next(
        row
        for row in session.get("/crm/control/catalog").json()["connections"]
        if row["key"] == "whatsapp"
    )["effective"]
    assert (
        session.patch(
            "/crm/control/connections/zernio", json={"version": 2, "enabled": True}
        ).status_code
        == 200
    )
    with config.locked():
        data = agent.load()
        data["needs_authorization"] = True
        agent.store(data)
    assert session.post("/crm/social/connect/whatsapp", json={}).status_code == 409
    catalog = session.get("/crm/control/catalog").json()["connections"]
    assert not next(row for row in catalog if row["key"] == "whatsapp")["effective"]


def test_rest_profile_channel_flows_remain_primary_even_with_oauth_observations(
    oauth_http, monkeypatch
):
    session, _, agent = oauth_http
    account_probe(monkeypatch, agent)
    agent.check()
    session, calls = configured(
        (session, None),
        monkeypatch,
        [
            {
                "_id": "rest-facebook",
                "profileId": "a" * 24,
                "platform": "facebook",
                "username": "Perfil de Jardines",
                "isActive": True,
            }
        ],
    )
    state = session.post("/crm/social/sync", json={}).json()
    assert state["configured"] is True and state["connect_mode"] == "api"
    assert state["profile"]["id"] == "a" * 24
    assert len(state["connections"]) == 1 and state["connections"][0]["source"] == "rest"
    assert state["connections"][0]["platform"] == "facebook"
    assert any(path.startswith("/v1/accounts") for _, path, _ in calls)
    intent = session.post("/crm/social/connect/facebook", json={}).json()
    assert "intent_id" in intent and "mode" not in intent


def test_refreshing_expired_access_does_not_revive_snapshot_before_new_probe(oauth, monkeypatch):
    agent = authorized(oauth)
    account_probe(monkeypatch, agent)
    agent.check()
    with config.locked():
        data = agent.load()
        data["tokens"]["expires_at"] = time.time() - 1
        agent.store(data)
        assert agent.access_token(data) == "private-access"
    assert agent.status()["verified_at"] is None
    assert routes.settings()["connections"][0]["status"] == "unverified"
