"""Guarded API/broker Retell regression suite; fake gateway only, serial database runner."""

# ruff: noqa: F811

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_crm import ORIGIN, authenticated, customer  # noqa: F401

from app.main import app
from app.retell import bridge, service


def test_retell_anonymous_and_body_limit():
    with TestClient(app) as client:
        assert client.get("/crm/retell/settings").status_code == 401
        assert client.post("/crm/retell/catalog", json={"revision": 0}).status_code == 401
        response = client.post("/crm/retell/settings", content=b"x" * 17000)
        assert response.status_code == 413
        assert "no-store" in response.headers["cache-control"]


@pytest.fixture
def retelled(authenticated, monkeypatch):
    client, owner, password = authenticated
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='retell'")
    state = {
        "configured": True,
        "verified": True,
        "revision": 1,
        "key_suffix": "abcd",
        "defaults": {"agent_id": "agent1", "chat_agent_id": "chat1", "from_number": "+15550000000"},
    }
    calls = []
    control = {"hash": "a" * 64, "fail_execute": False, "fail_claim": False}

    def request(path, body=None, timeout=3):
        calls.append((path, body))
        if path == "/state":
            return state.copy()
        if path in ("/configure", "/disconnect"):
            state["revision"] += 1
            if path == "/disconnect":
                state.update(configured=False, verified=False)
            return state.copy()
        if path == "/catalog":
            return {
                "revision": state["revision"],
                "registry_revision": "test-reviewed",
                "operations": list(service.registry().values()),
                "new_operations": [],
            }
        if path == "/schema":
            return {
                "revision": state["revision"],
                "endpoint": body["endpoint"],
                "schema_hash": control["hash"],
                "metadata": service.operation(body["endpoint"]),
                "input_schema": {
                    "type": "object",
                    "properties": {"agent_id": {"type": "string"}},
                    "required": ["agent_id"],
                },
            }
        if path == "/prepare":
            return {
                "revision": state["revision"],
                "endpoint": body["endpoint"],
                "schema_hash": control["hash"],
                "risk": service.operation(body["endpoint"])["risk"],
                "requires_consent": service.requires_consent(body["endpoint"]),
            }
        if path == "/execute":
            if control["fail_execute"]:
                raise HTTPException(503, "fake_sensitive_vendor_error")
            if body["endpoint"] == "createWebCall":
                return {"status": "ready", "session_id": body["request_id"], "call_id": "call1"}
            return {
                "status": "completed",
                "endpoint": body["endpoint"],
                "data": {
                    "name": "Safe result",
                    "access_token": "never_persist_me",
                    "nested": {"headers": {"Authorization": "private"}},
                },
            }
        if path.endswith("/claim"):
            if control["fail_claim"]:
                raise HTTPException(503, "fake_sensitive_vendor_error")
            return {"access_token": "ephemeral_retell_session_material"}
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "request", request)
    yield client, owner, password, state, calls, control
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='retell'")


def propose(client, endpoint="getAgent", arguments=None, contacts=None):
    data = {
        "endpoint": endpoint,
        "arguments": arguments if arguments is not None else {"agent_id": "agent1"},
    }
    if contacts is not None:
        data["contacts"] = contacts
    response = client.post(
        "/crm/hermes/actions", json={"action": "retell.execute", "arguments": data}
    )
    assert response.status_code == 200, response.text
    return response.json()["proposals"][0]


def approve(client, proposal, **extra):
    return client.post(
        "/crm/hermes/proposals/" + proposal["id"] + "/approve",
        json={"version": proposal["version"], **extra},
    )


def test_retell_csrf_origin_and_disabled(retelled):
    client, owner, _, _, calls, _ = retelled
    assert (
        client.post(
            "/crm/retell/settings",
            json={"revision": 1, "api_key": "fake_key_for_tests_only"},
            headers={"X-CSRF-Token": "wrong"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/crm/retell/catalog", json={"revision": 1}, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='retell'")
    response = client.post(
        "/crm/hermes/actions",
        json={
            "action": "retell.execute",
            "arguments": {"endpoint": "getAgent", "arguments": {"agent_id": "agent1"}},
        },
    )
    assert response.status_code == 409
    assert not any(path == "/execute" for path, _ in calls)


def test_retell_all_reads_are_proposals_once_only_and_redacted(retelled):
    client, owner, _, _, calls, _ = retelled
    proposal = propose(client)
    assert proposal["requirements"]["consent"] is False
    assert not any(path == "/execute" for path, _ in calls)
    response = approve(client, proposal)
    assert response.status_code == 200, response.text
    assert "never_persist_me" not in response.text
    assert approve(client, proposal).status_code == 409
    assert len([path for path, _ in calls if path == "/execute"]) == 1
    with psycopg.connect(owner) as db:
        assert "never_persist_me" not in str(
            db.execute("SELECT result FROM crm.hermes_proposals").fetchall()
        )


@pytest.mark.parametrize("endpoint", ["createAgent", "deleteAgent", "createWebCall", "createApp"])
def test_retell_mutating_paid_security_destructive_consent(retelled, endpoint):
    client, _, _, _, calls, _ = retelled
    proposal = propose(client, endpoint, {"requestBody": {"agent_id": "agent1"}})
    assert proposal["requirements"]["consent"] is True
    assert approve(client, proposal).status_code == 422
    assert approve(client, proposal, consent_confirmed="true").status_code == 422
    assert not any(path == "/execute" for path, _ in calls)
    assert approve(client, proposal, consent_confirmed=True).status_code == 200


@pytest.mark.parametrize("change", ["provider", "schema", "connection"])
def test_retell_stale_revisions_never_dispatch(retelled, change):
    client, owner, _, state, calls, control = retelled
    proposal = propose(client)
    if change == "provider":
        state["revision"] += 1
    elif change == "schema":
        control["hash"] = "b" * 64
    else:
        with psycopg.connect(owner) as db:
            db.execute("UPDATE crm.control_connections SET version=version+1 WHERE key='retell'")
    assert approve(client, proposal).status_code == 409
    assert not any(path == "/execute" for path, _ in calls)


def test_retell_unknown_uploads_secrets_and_raw_recipients_never_persist(retelled):
    client, owner, _, _, calls, _ = retelled
    for endpoint, arguments in [
        ("futureOperation", {}),
        ("cloneVoice", {}),
        ("createAgent", {"requestBody": {"auth_config": {"api_key": "secret"}}}),
        (
            "createPhoneCall",
            {"requestBody": {"from_number": "+15550000000", "to_number": "+15550000001"}},
        ),
    ]:
        response = client.post(
            "/crm/hermes/actions",
            json={
                "action": "retell.execute",
                "arguments": {"endpoint": endpoint, "arguments": arguments},
            },
        )
        assert response.status_code == 422, response.text
    assert not any(path == "/execute" for path, _ in calls)
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0


def test_retell_contact_exact_recheck_and_colombian_route_guard(retelled):
    client, _, _, _, calls, _ = retelled
    contact = customer(client, "+15550000001")
    contacts = [{"contact_id": contact["id"], "expected_phone": contact["phone"]}]
    proposal = propose(
        client,
        "createPhoneCall",
        {"requestBody": {"from_number": "+15550000000", "to_number": contact["phone"]}},
        contacts,
    )
    changed = client.patch(
        "/crm/contacts/" + contact["id"],
        json={
            "name": contact["name"],
            "phone": "+15550000002",
            "source": "web",
            "version": contact["version"],
        },
    )
    assert changed.status_code == 200
    assert approve(client, proposal, consent_confirmed=True).status_code == 409
    assert not any(path == "/execute" for path, _ in calls)
    colombia = customer(client)
    response = client.post(
        "/crm/hermes/actions",
        json={
            "action": "retell.execute",
            "arguments": {
                "endpoint": "createPhoneCall",
                "arguments": {
                    "requestBody": {"from_number": "+15550000000", "to_number": colombia["phone"]}
                },
                "contacts": [{"contact_id": colombia["id"], "expected_phone": colombia["phone"]}],
            },
        },
    )
    assert (
        response.status_code == 409
        and response.json()["detail"] == "retell_route_confirmation_required"
    )


def test_retell_uncertain_dispatch_consumed_never_retried(retelled):
    client, _, _, _, calls, control = retelled
    proposal = propose(client)
    control["fail_execute"] = True
    response = approve(client, proposal)
    assert response.status_code == 200
    assert response.json()["result"] == {
        "status": "external_outcome_unconfirmed",
        "retryable": False,
    }
    assert approve(client, proposal).status_code == 409
    assert len([path for path, _ in calls if path == "/execute"]) == 1


def test_retell_session_owner_session_once_only_and_private(retelled):
    client, owner, password, _, calls, _ = retelled
    proposal = propose(client, "createWebCall", {"requestBody": {"agent_id": "agent1"}})
    path = "/crm/retell/sessions/" + proposal["id"] + "/claim"
    assert client.post(path, json={}).status_code == 409
    assert approve(client, proposal, consent_confirmed=True).status_code == 200
    with TestClient(app, base_url=ORIGIN) as other:
        login = other.post(
            "/crm/auth/login",
            json={"username": "testadmin", "password": password},
            headers={"Origin": ORIGIN},
        )
        other.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]})
        assert other.post(path, json={}).status_code == 404
    response = client.post(path, json={})
    assert (
        response.status_code == 200
        and response.json()["access_token"] == "ephemeral_retell_session_material"
    )
    assert "no-store" in response.headers["cache-control"]
    assert client.post(path, json={}).status_code == 409
    assert len([route for route, _ in calls if route.endswith("/claim")]) == 1
    with psycopg.connect(owner) as db:
        for table in (
            "hermes_proposals",
            "hermes_runs",
            "hermes_calls",
            "control_audit",
            "retell_session_claims",
        ):
            assert "ephemeral_retell_session_material" not in str(
                db.execute(f"SELECT row_to_json(x)::text FROM crm.{table} x").fetchall()
            )


def test_retell_claim_failure_does_not_reopen(retelled):
    client, owner, _, _, calls, control = retelled
    proposal = propose(client, "createWebCall", {"requestBody": {"agent_id": "agent1"}})
    assert approve(client, proposal, consent_confirmed=True).status_code == 200
    control["fail_claim"] = True
    path = "/crm/retell/sessions/" + proposal["id"] + "/claim"
    assert client.post(path, json={}).status_code == 503
    assert client.post(path, json={}).status_code == 409
    assert len([route for route, _ in calls if route.endswith("/claim")]) == 1
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.retell_session_claims").fetchone()[0] == 1


def test_retell_catalog_schema_and_compact_manifest(retelled):
    client, _, _, _, _, _ = retelled
    response = client.post("/crm/retell/catalog", json={"revision": 1})
    assert response.status_code == 200 and len(response.json()["operations"]) == 112
    schema = client.post("/crm/retell/schema", json={"revision": 1, "endpoint": "getAgent"})
    assert schema.status_code == 200 and "input_schema" in schema.json()
    result = client.post(
        "/crm/hermes/actions",
        json={"action": "retell.schema", "arguments": {"endpoint": "getAgent"}},
    )
    assert result.status_code == 200, result.text
    assert "input_schema" not in result.text and len(result.content) < 12 * 1024


def test_retell_provider_key_never_audited_or_read_back(retelled):
    client, owner, _, _, _, _ = retelled
    response = client.post(
        "/crm/retell/settings", json={"revision": 1, "api_key": "fake_test_key_not_real_1234"}
    )
    assert response.status_code == 200 and "fake_test_key" not in response.text
    with psycopg.connect(owner) as db:
        assert "fake_test_key" not in str(
            db.execute("SELECT arguments FROM crm.control_audit").fetchall()
        )
    assert client.post("/crm/retell/disconnect", json={"revision": 2}).json()["enabled"] is False
