"""Guarded API/DB automatic reads; run serially with the existing isolated CRM runner."""

# ruff: noqa: F811

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_crm import authenticated  # noqa: F401
from test_retell import approve, propose, retelled  # noqa: F401

from app.retell import inventory, models


@pytest.fixture(autouse=True)
def empty_inventory_cache():
    inventory.clear_cache()
    yield
    inventory.clear_cache()


def execute_count(calls):
    return sum(path == "/execute" for path, _ in calls)


def test_inventory_auth_csrf_and_fixed_read_workflow_without_proposals(retelled):
    client, owner, _, _, calls, _ = retelled
    assert (
        client.post(
            "/crm/retell/inventory", json={"revision": 1}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/crm/retell/inventory",
            json={"revision": 1},
            headers={"Origin": "https://other.invalid"},
        ).status_code
        == 403
    )
    assert (
        client.post("/crm/retell/inventory?endpoint=createAgent", json={"revision": 1}).status_code
        == 422
    )
    assert calls == []
    response = client.post("/crm/retell/inventory", json={"revision": 1})
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    result = response.json()
    assert result["partial"] is True and result["cached"] is False and result["errors"] == []
    assert [row["endpoint"] for row in result["snapshots"]] == list(models.INVENTORY_ENDPOINTS)
    assert all(row["provider_revision"] == 1 for row in result["snapshots"])
    assert execute_count(calls) == 11
    assert client.post("/crm/retell/inventory", json={"revision": 1}).json()["cached"] is True
    assert execute_count(calls) == 11
    assert client.get("/crm/retell/results").json() == {"snapshots": [], "partial": True}
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0
        audits = db.execute(
            "SELECT action,arguments FROM crm.control_audit WHERE action='retell.automatic_read'"
        ).fetchall()
        assert len(audits) == 22
        for _, metadata in audits:
            assert set(metadata) == {"endpoint", "provider_revision", "connection_version", "stage"}
        assert "Safe result" not in str(audits) and "never_persist_me" not in str(audits)


def test_direct_read_has_no_paid_security_or_arbitrary_operation_escape(retelled):
    client, owner, _, _, calls, _ = retelled
    for body in [
        {"endpoint": "createAgent", "arguments": {}},
        {"endpoint": "createWebCall", "arguments": {}},
        {"endpoint": "deleteAgent", "arguments": {}},
        {"endpoint": "listenLiveCall", "arguments": {}},
        {"endpoint": "listAppUsages", "arguments": {}},
        {"endpoint": "getAgent", "arguments": {"url": "https://other.invalid"}},
        {"endpoint": "getAgent", "arguments": {"access_token": "private"}},
        {"endpoint": "getAgent", "arguments": {}, "consent_confirmed": True},
    ]:
        assert client.post("/crm/retell/read", json={"revision": 1, **body}).status_code == 422
    assert calls == []
    response = client.post(
        "/crm/retell/read",
        json={"revision": 1, "endpoint": "getAgent", "arguments": {"agent_id": "fixture"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert response.json()["endpoint"] == "getAgent"
    assert "never_persist_me" not in response.text
    assert execute_count(calls) == 1
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0


def test_completed_actor_session_mutation_and_connection_change_invalidate_cache(retelled):
    client, owner, _, _, calls, _ = retelled
    assert client.post("/crm/retell/inventory", json={"revision": 1}).json()["cached"] is False
    mutation = propose(client, "createAgent", {"requestBody": {"agent_name": "fixture"}})
    assert approve(client, mutation, consent_confirmed=True).status_code == 200
    assert client.post("/crm/retell/inventory", json={"revision": 1}).json()["cached"] is False
    assert execute_count(calls) == 23
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET version=version+1 WHERE key='retell'")
    assert client.post("/crm/retell/inventory", json={"revision": 1}).json()["cached"] is False
    assert execute_count(calls) == 34
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='retell'")
    assert client.post("/crm/retell/inventory", json={"revision": 1}).status_code == 409
    assert execute_count(calls) == 34


def test_foreign_actor_or_session_mutations_do_not_invalidate_an_admin_cache(retelled):
    client, owner, _, _, calls, _ = retelled
    assert client.post("/crm/retell/inventory", json={"revision": 1}).status_code == 200
    with psycopg.connect(owner) as db:
        actor = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()[0]
        other = db.execute(
            "INSERT INTO crm.users(username,password_hash) SELECT 'other-inventory-admin',password_hash FROM crm.users WHERE id=%s RETURNING id",
            (actor,),
        ).fetchone()[0]
        for owner_id in [actor, other]:
            db.execute(
                """INSERT INTO crm.hermes_proposals(actor_id,session_hash,action,status,arguments,revisions,result)
                VALUES (%s,'another-session','retell.execute','approved',%s,'{}',%s)""",
                (
                    owner_id,
                    Jsonb({"endpoint": "createAgent"}),
                    Jsonb({"provider": "retell", "status": "completed"}),
                ),
            )
    assert client.post("/crm/retell/inventory", json={"revision": 1}).json()["cached"] is True
    assert execute_count(calls) == 11


def test_new_login_and_provider_revision_cannot_reuse_old_inventory(retelled):
    client, _, password, state, calls, _ = retelled
    assert client.post("/crm/retell/inventory", json={"revision": 1}).status_code == 200
    assert client.post("/crm/auth/logout").status_code == 200
    login = client.post("/crm/auth/login", json={"username": "testadmin", "password": password})
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    state["revision"] = 2
    assert client.post("/crm/retell/inventory", json={"revision": 1}).status_code == 409
    assert execute_count(calls) == 11
    response = client.post("/crm/retell/inventory", json={"revision": 2})
    assert response.status_code == 200, response.text
    assert response.json()["cached"] is False
    assert execute_count(calls) == 22
