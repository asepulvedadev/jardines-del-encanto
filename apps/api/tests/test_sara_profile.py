"""Shared agent configuration and synthetic simulation; isolated state, no real providers."""

# ruff: noqa: F811
import uuid

import psycopg
import pytest
from test_crm import authenticated  # noqa: F401

from app.sara import profile_models


@pytest.fixture
def workspace(authenticated, monkeypatch):
    client, owner, _ = authenticated
    with psycopg.connect(owner) as db:
        db.execute("TRUNCATE crm.sara_profile,crm.sara_profile_versions,crm.sara_simulations")
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='hermes'")
    return client, owner


def test_profile_is_owned_authenticated_versioned_editable_not_runtime(workspace):
    client, _ = workspace
    response = client.get("/crm/sara/config")
    assert response.status_code == 200, response.text
    original = response.json()
    edited = client.patch(
        "/crm/sara/config",
        json={
            "version": original["version"],
            "instructions": "Responde con una pregunta a la vez.",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == original["version"] + 1
    assert (
        client.patch(
            "/crm/sara/config", json={"version": original["version"], "knowledge": "stale"}
        ).status_code
        == 409
    )
    for field in ("api_key", "provider_url", "allowed_tools", "developer_numbers", "source_code"):
        assert (
            client.patch(
                "/crm/sara/config", json={"version": edited.json()["version"], field: "forbidden"}
            ).status_code
            == 422
        )
    versions = client.get("/crm/sara/config/versions").json()["versions"]
    assert len(versions) == 2
    assert versions[0]["document"]["instructions"] == "Responde con una pregunta a la vez."
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.patch("/crm/sara/config", json={"version": 2, "name": "No"}).status_code == 403
    client.cookies.clear()
    assert client.get("/crm/sara/config").status_code == 401


def test_sara_can_use_real_tool_dispatch_to_edit_and_learn(workspace):
    client, _ = workspace
    start = client.get("/crm/sara/config").json()
    result = client.post(
        "/crm/hermes/actions",
        json={
            "action": "sara.config.update",
            "arguments": {"version": start["version"], "response_style": "balanced"},
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["result"]["response_style"] == "balanced"
    result = client.post(
        "/crm/hermes/actions",
        json={
            "action": "sara.learn",
            "arguments": {"version": 2, "content": "Dato confirmado por el desarrollador."},
        },
    )
    assert result.status_code == 200, result.text
    assert "Dato confirmado" in result.json()["result"]["knowledge"]
    assert "proposals" not in result.json()


def test_simulation_is_idempotent_isolated_and_snapshot_based(workspace, monkeypatch):
    from app.crm.database import connect
    from app.sara import simulations

    client, _owner = workspace
    profile_before = client.get("/crm/sara/config").json()
    body = {
        "request_id": str(uuid.uuid4()),
        "title": "Comprador escéptico",
        "customer_turns": ["¿Dónde está el proyecto?", "¿Hay financiación?"],
    }
    created = client.post("/crm/sara/simulations", json=body)
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["status"] == "queued" and record["synthetic"] is True
    assert client.post("/crm/sara/simulations", json=body).json()["id"] == record["id"]
    assert (
        client.post(
            "/crm/sara/simulations", json={**body, "customer_turns": ["changed"]}
        ).status_code
        == 409
    )
    calls = []

    def private(path, payload, **kwargs):
        assert path == "/public-reply" and set(payload) == {"messages", "instructions", "knowledge"}
        calls.append(payload)
        return {
            "ok": True,
            "tools": 0,
            "model": "gpt-6-luna",
            "response": "Respuesta sintética verificada.",
        }

    monkeypatch.setattr(simulations.bridge, "request", private)
    with connect() as db:
        before = db.execute(
            "SELECT (SELECT count(*) FROM crm.contacts) contacts,(SELECT count(*) FROM crm.whatsapp_agent_jobs) jobs"
        ).fetchone()
    simulations.tick()
    after = client.get("/crm/sara/simulations/" + record["id"]).json()
    assert after["status"] == "completed" and len(after["transcript"]) == 4
    assert after["profile_version"] == profile_before["version"] and len(calls) == 2
    assert len(calls[1]["messages"]) == 3
    with connect() as db:
        assert (
            db.execute(
                "SELECT (SELECT count(*) FROM crm.contacts) contacts,(SELECT count(*) FROM crm.whatsapp_agent_jobs) jobs"
            ).fetchone()
            == before
        )
    assert client.get("/crm/sara/config").json() == profile_before


def test_profile_models_deny_secret_fields():
    with pytest.raises(ValueError):
        profile_models.ProfileUpdate.model_validate({"version": 1, "model_api_key": "secret"})
