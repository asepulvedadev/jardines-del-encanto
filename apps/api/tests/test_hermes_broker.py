"""Broker auth, replay, bounded calls and deterministic private bridge integration."""

# ruff: noqa: F811
import psycopg
from fastapi.testclient import TestClient
from test_control_plane import controlled, item  # noqa: F401
from test_crm import authenticated  # noqa: F401

from app.crm import security
from app.crm.database import connect
from app.hermes import bridge, broker
from app.main import app


def issue(client, owner):
    digest = security.digest(client.cookies.get("jardines_session"))
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='hermes'")
    with connect() as db:
        admin = db.execute(
            "SELECT u.id,s.token_hash FROM crm.sessions s JOIN crm.users u ON u.id=s.user_id WHERE s.token_hash=%s",
            (digest,),
        ).fetchone()
        run_id, token = broker.issue(db, admin, "Revisar clientes")
    return run_id, token, {"Authorization": "Bearer " + token}


def test_internal_requires_bearer_not_admin_cookie_and_single_claim(controlled):
    client, owner, _ = controlled
    run_id, token, headers = issue(client, owner)
    assert len(token) >= 43
    assert client.post("/internal/hermes/claim", json={}).status_code == 401
    assert (
        client.post(
            "/internal/hermes/claim", json={}, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    response = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert response.status_code == 200
    claim = response.json()
    assert claim["run_id"] == str(run_id)
    schema = claim["tools"][0]["function"]
    assert schema["name"] == "jardines_app"
    assert schema["parameters"]["required"] == ["action", "arguments"]
    assert schema["parameters"]["additionalProperties"] is False
    assert "shell.run" not in schema["parameters"]["properties"]["action"]["enum"]
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 409
    with psycopg.connect(owner) as db:
        stored = db.execute(
            "SELECT token_hash FROM crm.hermes_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
    assert stored == security.digest(token) and token not in stored


def test_call_id_dedup_tamper_budget_and_finish(controlled):
    client, owner, _ = controlled
    _, _, headers = issue(client, owner)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    call = {
        "call_id": "1",
        "action": "crm.contact.create",
        "arguments": {"name": "Propuesta", "phone": "3001234567", "source": "web"},
    }
    first = client.post("/internal/hermes/call", json=call, headers=headers)
    second = client.post("/internal/hermes/call", json=call, headers=headers)
    assert first.status_code == 200 and first.json() == second.json()
    assert (
        client.post(
            "/internal/hermes/call", json={**call, "arguments": {}}, headers=headers
        ).status_code
        == 409
    )
    for count in range(2, 13):
        response = client.post(
            "/internal/hermes/call",
            json={"call_id": str(count), "action": "shell.run", "arguments": {}},
            headers=headers,
        )
        assert (
            response.status_code == 200
            and response.json()["result"]["error"] == "capability_not_in_run"
        )
    assert (
        client.post(
            "/internal/hermes/call",
            json={"call_id": "13", "action": "crm.workspace", "arguments": {}},
            headers=headers,
        ).status_code
        == 429
    )
    finished = client.post(
        "/internal/hermes/finish",
        json={"reply": "Se preparó una propuesta pendiente."},
        headers=headers,
    )
    assert finished.status_code == 200 and len(finished.json()["proposals"]) == 1
    assert client.post("/internal/hermes/call", json=call, headers=headers).status_code == 409
    assert (
        client.post(
            "/internal/hermes/finish", json={"reply": "Replay"}, headers=headers
        ).status_code
        == 409
    )
    assert client.get("/crm/workspace").json()["contacts"] == []


def test_run_expiry_revocation_and_user_disable(controlled):
    client, owner, _ = controlled
    run_id, _, headers = issue(client, owner)
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.hermes_runs SET expires_at=now()-interval '1 second' WHERE id=%s", (run_id,)
        )
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 401
    _, _, headers = issue(client, owner)
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.users SET enabled=false WHERE username='testadmin'")
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 401
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.users SET enabled=true WHERE username='testadmin'")
    _, _, headers = issue(client, owner)
    assert client.post("/crm/auth/logout").status_code == 200
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 401


def test_claim_includes_effective_skills_plugins_and_disabled_tool_removed(controlled):
    client, owner, _ = controlled
    item(client, "skill", {"content": "# Contexto verificado"}, enabled=True)
    item(
        client,
        "plugin",
        {"actions": ["crm.workspace"], "instructions": "No inventar clientes."},
        enabled=True,
    )
    item(client, definition={"action": "crm.note.create"}, enabled=False)
    _, _, headers = issue(client, owner)
    claim = client.post("/internal/hermes/claim", json={}, headers=headers).json()
    assert len(claim["skills"]) == 2
    assert (
        "crm.note.create"
        not in claim["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    )
    denied = client.post(
        "/internal/hermes/call",
        json={
            "call_id": "disabled",
            "action": "crm.note.create",
            "arguments": {"deal_id": "00000000-0000-0000-0000-000000000001", "body": "No ejecutar"},
        },
        headers=headers,
    )
    assert denied.json()["result"]["error"] == "capability_not_in_run"


def test_chat_requires_real_bridge_completion_and_never_exposes_token(controlled, monkeypatch):
    client, _owner, _ = controlled
    monkeypatch.setattr(
        bridge, "health", lambda: {"configured": True, "available": True, "model": "fixture"}
    )
    pref = client.patch("/crm/control/connections/hermes", json={"version": 1, "enabled": True})
    assert pref.status_code == 200
    seen = []

    def run(path, body, timeout):
        assert path == "/run" and timeout == 90
        seen.append(body["token"])
        headers = {"Authorization": "Bearer " + body["token"]}
        with TestClient(app) as runtime:
            claim = runtime.post("/internal/hermes/claim", json={}, headers=headers)
            assert claim.status_code == 200
            result = runtime.post(
                "/internal/hermes/call",
                json={"call_id": "read", "action": "crm.workspace", "arguments": {}},
                headers=headers,
            )
            assert result.status_code == 200
            return runtime.post(
                "/internal/hermes/finish",
                json={"reply": "Hay 0 clientes en el CRM."},
                headers=headers,
            ).json()

    monkeypatch.setattr(bridge, "request", run)
    response = client.post("/crm/hermes/chat", json={"message": "¿Cuántos clientes hay?"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Hay 0 clientes en el CRM."
    assert response.json()["results"][0]["counts"]["contacts"] == 0
    assert seen[0] not in response.text
    monkeypatch.setattr(
        bridge, "request", lambda *args, **kwargs: {"reply": "Canned without finish"}
    )
    assert client.post("/crm/hermes/chat", json={"message": "No simular"}).status_code == 503


def test_bridge_urls_are_fixed_and_unavailable_is_honest(controlled, monkeypatch):
    client, _, _ = controlled
    for url in [
        "https://attacker.invalid",
        "http://api:8000",
        "http://localhost:8081/path",
        "http://user@localhost:8081",
        "http://hermes-bridge:8081?x=1",
    ]:
        monkeypatch.setenv("HERMES_BRIDGE_URL", url)
        assert bridge.bridge_url() is None
    monkeypatch.delenv("HERMES_BRIDGE_URL", raising=False)
    status = client.get("/crm/hermes/status").json()
    assert status["configured"] is False and status["available"] is False
    assert client.post("/crm/hermes/chat", json={"message": "Hola"}).status_code == 503
    assert (
        client.patch(
            "/crm/control/connections/hermes", json={"version": 1, "enabled": True}
        ).status_code
        == 503
    )


def test_logout_retains_durable_run_proposals_and_audit_but_revokes_token(controlled):
    client, owner, _ = controlled
    run_id, _, headers = issue(client, owner)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    response = client.post(
        "/internal/hermes/call",
        json={
            "call_id": "pending",
            "action": "crm.contact.create",
            "arguments": {"name": "Pendiente", "phone": "3001234567", "source": "web"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert client.post("/crm/auth/logout").status_code == 200
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 401
    with psycopg.connect(owner) as db:
        assert (
            db.execute("SELECT count(*) FROM crm.hermes_runs WHERE id=%s", (run_id,)).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT count(*) FROM crm.hermes_proposals WHERE run_id=%s", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT count(*) FROM crm.control_audit WHERE action='proposal.create'"
            ).fetchone()[0]
            == 1
        )


def test_cumulative_output_budget_rolls_back_proposals_and_keeps_explicit_error(
    controlled, monkeypatch
):
    import json

    client, owner, _ = controlled
    _, _, headers = issue(client, owner)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    real_dispatch = broker.dispatch

    def large_dispatch(*args, **kwargs):
        result = real_dispatch(*args, **kwargs)
        result["result"] = {"body": "x" * 40000}
        return result

    monkeypatch.setattr(broker, "dispatch", large_dispatch)
    first = client.post(
        "/internal/hermes/call",
        json={"call_id": "read", "action": "crm.workspace", "arguments": {}},
        headers=headers,
    )
    assert first.status_code == 200 and len(first.content) > 40000
    second = client.post(
        "/internal/hermes/call",
        json={
            "call_id": "too-large",
            "action": "crm.contact.create",
            "arguments": {"name": "Rollback", "phone": "3001234567", "source": "web"},
        },
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json() == {"result": {"error": "run_output_limit"}}
    finished = client.post("/internal/hermes/finish", json={"reply": "😀" * 16000}, headers=headers)
    assert finished.status_code == 200 and len(finished.content) < 128 * 1024
    assert finished.json()["proposals"] == []
    with psycopg.connect(owner) as db:
        responses = db.execute("SELECT response FROM crm.hermes_calls").fetchall()
    assert (
        sum(
            len(json.dumps(row[0], ensure_ascii=False, separators=(",", ":")).encode())
            for row in responses
        )
        <= 65536
    )


def test_claim_scope_cannot_expand_or_use_changed_custom_items(controlled):
    client, owner, _ = controlled
    toggle = item(client, definition={"action": "crm.note.create"}, enabled=False)
    custom = item(client, "plugin", {"actions": ["crm.workspace"]}, enabled=True)
    _, _, headers = issue(client, owner)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    assert (
        client.patch(
            f"/crm/control/items/{toggle['id']}", json={"version": 1, "enabled": True}
        ).status_code
        == 200
    )
    denied = client.post(
        "/internal/hermes/call",
        json={"call_id": "expanded", "action": "crm.note.create", "arguments": {}},
        headers=headers,
    )
    assert denied.json()["result"]["error"] == "capability_not_in_run"
    assert (
        client.patch(
            f"/crm/control/items/{custom['id']}", json={"version": 1, "name": "Nueva revisión"}
        ).status_code
        == 200
    )
    denied = client.post(
        "/internal/hermes/call",
        json={
            "call_id": "changed",
            "action": "custom." + custom["id"],
            "arguments": {"action": "crm.workspace", "arguments": {}},
        },
        headers=headers,
    )
    assert denied.json()["result"]["error"] == "definition_changed"


def test_oversized_effective_manifest_fails_closed_instead_of_omitting_tools(controlled):
    client, owner, _ = controlled
    item(
        client,
        "script",
        {
            "steps": [
                {
                    "action": "control.item.create",
                    "arguments": {
                        "kind": "skill",
                        "name": "Contexto",
                        "definition": {"content": "x" * 16000},
                    },
                }
            ]
        },
        enabled=True,
    )
    _, _, headers = issue(client, owner)
    response = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert response.status_code == 503 and response.json()["detail"] == "hermes_catalog_too_large"


def test_missing_service_identity_rejected_before_database_configuration(monkeypatch):
    monkeypatch.delenv("CRM_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        for path in ("claim", "call", "finish"):
            body = (
                {}
                if path == "claim"
                else {"call_id": "x", "action": "crm.workspace", "arguments": {}}
                if path == "call"
                else {"reply": "Sin autoridad"}
            )
            assert client.post("/internal/hermes/" + path, json=body).status_code == 401
