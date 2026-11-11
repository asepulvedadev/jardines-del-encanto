"""Control plane tests exclusively use the guarded CRM test database."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_crm import authenticated, customer  # noqa: F401

from app.main import app


@pytest.fixture
def controlled(authenticated):
    client, owner, password = authenticated
    # Global workspace preferences are not owned by individual users. Restore them on both sides.
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=(key!='hermes'),version=1")
    try:
        yield client, owner, password
    finally:
        with psycopg.connect(owner) as db:
            db.execute("UPDATE crm.control_connections SET enabled=(key!='hermes'),version=1")


def item(client, kind="tool", definition=None, enabled=False):
    response = client.post(
        "/crm/control/items",
        json={
            "kind": kind,
            "name": "Extensión de prueba",
            "definition": definition or {"action": "crm.workspace"},
            "enabled": enabled,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def propose(client, action, arguments=None):
    response = client.post(
        "/crm/hermes/actions", json={"action": action, "arguments": arguments or {}}
    )
    assert response.status_code == 200, response.text
    return response.json()["proposals"][0]


def test_catalog_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/crm/control/catalog").status_code == 401
        assert client.get("/crm/hermes/status").status_code == 401
        response = client.post("/internal/hermes/claim", json={})
        assert response.status_code == 401
        assert "no-store" in response.headers["cache-control"]


def test_definitions_are_bounded_strict_and_unsupported_cannot_be_active(controlled):
    client, _, _ = controlled
    assert client.get("/crm/control/catalog").status_code == 200
    unknown = item(client, definition={"action": "shell.run"})
    assert unknown["effective"] is False
    path = f"/crm/control/items/{unknown['id']}"
    assert client.patch(path, json={"version": 1, "enabled": True}).status_code == 422
    assert (
        client.patch(
            path, json={"version": 1, "definition": {"action": "crm.workspace", "url": "x"}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/crm/control/items",
            json={"kind": "script", "name": "No Python", "definition": {"code": "print(1)"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/crm/control/items",
            json={
                "kind": "script",
                "name": "Muy largo",
                "definition": {"steps": [{"action": "crm.workspace"}] * 9},
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/crm/control/items",
            json={
                "kind": "connection",
                "name": "No proxy",
                "definition": {"adapter": "http", "url": "https://example.com"},
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/crm/control/items",
            json={
                "kind": "tool",
                "name": "Defaults inválidos",
                "enabled": True,
                "definition": {
                    "action": "crm.contact.create",
                    "defaults": {"phone": "not a phone"},
                },
            },
        ).status_code
        == 422
    )
    skill = item(client, "skill", {"content": "ó" * 16000}, enabled=True)
    assert skill["effective"]
    assert client.post(f"/crm/control/items/{skill['id']}/run", json={}).status_code == 409
    assert (
        client.post(
            "/crm/control/items", content=b" " * 65537, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/crm/hermes/actions",
            content=b" " * 16385,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_item_versions_and_csrf_are_enforced(controlled):
    client, _, _ = controlled
    record = item(client)
    path = f"/crm/control/items/{record['id']}"
    assert (
        client.patch(
            path, json={"version": 1, "enabled": True}, headers={"X-CSRF-Token": "invalid"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            path,
            json={"version": 1, "enabled": True},
            headers={"Origin": "https://attacker.invalid"},
        ).status_code
        == 403
    )
    updated = client.patch(path, json={"version": 1, "enabled": True}).json()
    assert updated["effective"] and updated["version"] == 2
    assert client.patch(path, json={"version": 1, "enabled": False}).status_code == 409
    assert client.patch(path, json={"version": 2, "definition": None}).status_code == 422


def test_mutation_is_proposed_and_only_applied_once(controlled):
    client, _, _ = controlled
    customer(client)
    deal = client.get("/crm/workspace").json()["deals"][0]
    proposal = propose(
        client, "crm.note.create", {"deal_id": deal["id"], "body": "Confirmación exacta"}
    )
    assert not any(
        a["body"] == "Confirmación exacta"
        for a in client.get("/crm/workspace").json()["activities"]
    )
    path = f"/crm/hermes/proposals/{proposal['id']}/approve"
    assert (
        client.post(path, json={"version": 1, "arguments": {"body": "tampered"}}).status_code == 422
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda _: client.post(path, json={"version": 1}).status_code, range(2))
        )
    assert sorted(outcomes) == [200, 409]
    notes = [
        a
        for a in client.get("/crm/workspace").json()["activities"]
        if a["body"] == "Confirmación exacta"
    ]
    assert len(notes) == 1


def test_optimistic_contact_edit_is_shared_with_human_crud(controlled):
    client, _, _ = controlled
    contact = customer(client)
    arguments = {
        "contact_id": contact["id"],
        "name": "Por Hermes",
        "phone": "3001234567",
        "source": "web",
        "version": 1,
    }
    proposal = propose(client, "crm.contact.update", arguments)
    assert proposal["arguments"]["phone"] == "+573001234567"
    assert (
        client.patch(
            f"/crm/contacts/{contact['id']}",
            json={
                key: value
                for key, value in {**arguments, "name": "Cambio humano"}.items()
                if key != "contact_id"
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": 1}
        ).status_code
        == 409
    )
    assert client.get("/crm/workspace").json()["contacts"][0]["name"] == "Cambio humano"


def test_builtin_toggle_blocks_automation_not_humans_and_revokes_pending(controlled):
    client, _, _ = controlled
    proposal = propose(
        client, "crm.contact.create", {"name": "Pendiente", "phone": "3001234567", "source": "web"}
    )
    item(client, definition={"action": "crm.contact.create"}, enabled=False)
    assert (
        client.post(
            f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/crm/hermes/actions",
            json={"action": "crm.contact.create", "arguments": proposal["arguments"]},
        ).status_code
        == 409
    )
    assert customer(client)["name"] == "Cliente de prueba"


def test_custom_script_plugin_tool_and_revision_invalidation(controlled):
    client, _, _ = controlled
    tool = item(
        client,
        definition={"action": "crm.contact.create", "defaults": {"source": "web"}},
        enabled=True,
    )
    response = client.post(
        f"/crm/control/items/{tool['id']}/run",
        json={"arguments": {"name": "Cliente", "phone": "3001234567"}},
    )
    proposal = response.json()["proposals"][0]
    assert (
        client.patch(
            f"/crm/control/items/{tool['id']}", json={"version": 1, "name": "Nueva revisión"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": 1}
        ).status_code
        == 409
    )
    script = item(
        client,
        "script",
        {
            "steps": [
                {"action": "crm.workspace"},
                {
                    "action": "crm.task.create",
                    "arguments": {
                        "contact_id": str(uuid4()),
                        "title": "Seguimiento",
                        "due_date": "2026-11-11",
                    },
                },
            ]
        },
        enabled=True,
    )
    result = client.post(f"/crm/control/items/{script['id']}/run", json={}).json()
    assert len(result["result"]["steps"]) == 1 and len(result["proposals"]) == 1
    plugin = item(
        client,
        "plugin",
        {"actions": ["crm.workspace"], "instructions": "Solo lectura"},
        enabled=True,
    )
    assert (
        client.post(
            f"/crm/control/items/{plugin['id']}/run",
            json={"arguments": {"action": "crm.workspace", "arguments": {}}},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/crm/control/items/{plugin['id']}/run",
            json={"arguments": {"action": "crm.note.create", "arguments": {}}},
        ).status_code
        == 422
    )


def test_reject_expire_and_session_binding(controlled):
    client, owner, password = controlled
    proposal = propose(
        client,
        "crm.contact.create",
        {"name": "Sin aplicar", "phone": "3001234567", "source": "web"},
    )
    path = f"/crm/hermes/proposals/{proposal['id']}"
    assert (
        client.post(path + "/reject", json={"version": 1}).json()["proposal"]["status"]
        == "rejected"
    )
    assert client.post(path + "/approve", json={"version": 1}).status_code == 409
    proposal = propose(client, "crm.contact.create", proposal["arguments"])
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.hermes_proposals SET expires_at=now()-interval '1 second' WHERE id=%s",
            (proposal["id"],),
        )
    assert (
        client.post(
            f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": 1}
        ).status_code
        == 410
    )
    with TestClient(app, base_url="http://127.0.0.1:4320") as other:
        login = other.post(
            "/crm/auth/login",
            headers={"Origin": "http://127.0.0.1:4320"},
            json={"username": "testadmin", "password": password},
        ).json()
        other.headers.update(
            {"Origin": "http://127.0.0.1:4320", "X-CSRF-Token": login["csrf_token"]}
        )
        assert (
            other.post(
                f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": 1}
            ).status_code
            == 404
        )


def test_social_pause_blocks_new_work_but_not_status_or_callback(controlled):
    client, _, _ = controlled
    result = client.patch("/crm/control/connections/zernio", json={"version": 1, "enabled": False})
    assert result.status_code == 200 and result.json()["version"] == 2
    assert client.post("/crm/social/sync", json={}).status_code == 409
    assert client.post("/crm/social/connect/facebook", json={}).status_code == 409
    assert client.post("/crm/social/mcp/start", json={}).status_code == 409
    assert client.get("/crm/social/settings").status_code == 200
    assert client.post("/crm/social/complete", json={"intent_id": str(uuid4())}).status_code != 409
    assert client.post("/crm/hermes/actions", json={"action": "social.sync"}).status_code == 409
    assert (
        client.patch(
            "/crm/control/connections/zernio", json={"version": 1, "enabled": True}
        ).status_code
        == 409
    )


def test_external_approval_is_reserved_once_even_with_uncertain_outcome(controlled, monkeypatch):
    from app.social import routes

    client, _, _ = controlled
    calls = []

    def unavailable(*args):
        calls.append(True)
        raise OSError("private transport detail")

    monkeypatch.setattr(routes, "sync_settings", unavailable)
    proposal = propose(client, "social.sync")
    path = f"/crm/hermes/proposals/{proposal['id']}/approve"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: client.post(path, json={"version": 1}), range(2)))
    assert sorted(response.status_code for response in outcomes) == [200, 409]
    success = next(response for response in outcomes if response.status_code == 200)
    assert success.json()["result"] == {
        "status": "external_outcome_unconfirmed",
        "retryable": False,
    }
    assert len(calls) == 1


def test_workspace_operator_paging_and_no_credentials(controlled):
    client, _, _ = controlled
    customer(client)
    payload = client.post(
        "/crm/hermes/actions",
        json={"action": "crm.workspace", "arguments": {"limit": 1, "query": "prueba"}},
    ).json()["result"]
    assert len(payload["contacts"]) == 1 and payload["paging"]["limit"] == 1
    assert "snapshot_limit" in payload["paging"]
    assert (
        client.post(
            "/crm/hermes/actions", json={"action": "crm.workspace", "arguments": {"limit": 101}}
        ).status_code
        == 422
    )
    catalog = client.get("/crm/control/catalog").text
    assert (
        "password_hash" not in catalog and "api_key" not in catalog and "csrf_token" not in catalog
    )


def test_paused_zernio_parent_marks_available_children_ineffective(controlled, monkeypatch):
    from app.social import config, routes

    client, _, _ = controlled
    monkeypatch.setattr(config, "load", lambda: {"profile_id": "fixture"})
    monkeypatch.setattr(
        routes,
        "settings",
        lambda *_: {
            "configured": True,
            "connections": [{"platform": "facebook", "status": "connected"}],
        },
    )
    before = client.get("/crm/control/catalog").json()["connections"]
    assert next(row for row in before if row["key"] == "facebook")["effective"]
    assert (
        client.patch(
            "/crm/control/connections/zernio", json={"version": 1, "enabled": False}
        ).status_code
        == 200
    )
    after = client.get("/crm/control/catalog").json()["connections"]
    facebook = next(row for row in after if row["key"] == "facebook")
    assert facebook["available"] is True and facebook["enabled"] is True
    assert facebook["effective"] is False and facebook["status"] == "paused"


def test_unsupported_social_platform_preserves_original_not_found(controlled):
    client, _, _ = controlled
    assert client.post("/crm/social/connect/unsupported", json={}).status_code == 404
