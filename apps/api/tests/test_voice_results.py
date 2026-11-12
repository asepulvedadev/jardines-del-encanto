"""Guarded local DB coverage; parent runs serially with the existing isolated test runner."""

# ruff: noqa: F811

from copy import deepcopy

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_crm import ORIGIN, authenticated  # noqa: F401
from test_retell import approve, propose, retelled  # noqa: F401

from app.crm import security
from app.main import app
from app.retell import bridge


def fail_external(*args, **kwargs):
    raise AssertionError("GET results must not call any provider endpoint")


def stored_identity(db, client):
    token_hash = security.digest(client.cookies.get("jardines_session"))
    actor = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()[0]
    version = db.execute(
        "SELECT version FROM crm.control_connections WHERE key='retell'"
    ).fetchone()[0]
    return actor, token_hash, version


def insert_snapshot(db, actor, session, version, **changes):
    row = {
        "actor_id": actor,
        "session_hash": session,
        "action": "retell.execute",
        "status": "approved",
        "arguments": {"endpoint": "listAgents", "arguments": {"never_expose": "private-input"}},
        "revisions": {"connection:retell": version, "provider:retell": 7},
        "result": {
            "provider": "retell",
            "status": "completed",
            "endpoint": "listAgents",
            "data": {"agent_id": "fixture", "access_token": "private-token"},
        },
        **changes,
    }
    return db.execute(
        """INSERT INTO crm.hermes_proposals
        (actor_id,session_hash,action,status,arguments,revisions,result)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (
            row["actor_id"],
            row["session_hash"],
            row["action"],
            row["status"],
            Jsonb(row["arguments"]),
            Jsonb(row["revisions"]),
            Jsonb(row["result"]),
        ),
    ).fetchone()[0]


def test_results_restore_only_explicitly_approved_reads_and_latest_endpoint(retelled, monkeypatch):
    client, _, _, _, calls, _ = retelled
    first = propose(client, "listAgents", {})
    assert client.get("/crm/retell/results").json() == {"snapshots": [], "partial": True}
    assert not any(path == "/execute" for path, _ in calls)
    assert approve(client, first).status_code == 200
    second = propose(client, "listAgents", {})
    assert approve(client, second).status_code == 200
    other = propose(client, "getAgent")
    assert approve(client, other).status_code == 200
    mutation = propose(client, "createAgent", {"requestBody": {"agent_name": "fixture"}})
    assert approve(client, mutation, consent_confirmed=True).status_code == 200
    monkeypatch.setattr(bridge, "request", fail_external)
    result = client.get("/crm/retell/results")
    assert result.status_code == 200, result.text
    assert "no-store" in result.headers["cache-control"]
    assert "private" in result.headers["cache-control"]
    data = result.json()
    assert data["partial"] is True
    assert {row["id"] for row in data["snapshots"]} == {second["id"], other["id"]}
    assert all(row["provider_revision"] == 1 for row in data["snapshots"])
    assert all(
        set(row) == {"id", "endpoint", "created_at", "provider_revision", "data"}
        for row in data["snapshots"]
    )
    assert all(row["data"]["name"] == "Safe result" for row in data["snapshots"])
    assert "never_persist_me" not in result.text


def test_results_sql_guards_actor_session_status_and_frozen_revisions(retelled, monkeypatch):
    client, owner, _, _, _, _ = retelled
    with psycopg.connect(owner) as db:
        actor, session, version = stored_identity(db, client)
        other_actor = db.execute(
            """INSERT INTO crm.users(username,password_hash)
            SELECT 'other-snapshot-admin',password_hash FROM crm.users WHERE id=%s RETURNING id""",
            (actor,),
        ).fetchone()[0]
        valid_id = insert_snapshot(db, actor, session, version)
        for changes in [
            {"actor_id": other_actor},
            {"session_hash": "different-session"},
            {"action": "voice.execute"},
            *[{"status": status} for status in ["pending", "rejected", "expired"]],
            {"arguments": {"endpoint": "getAgent"}},
            {"revisions": {"provider:retell": 7}},
            {"revisions": {"connection:retell": version - 1, "provider:retell": 7}},
            {"revisions": {"connection:retell": str(version), "provider:retell": 7}},
            {"revisions": {"connection:retell": version, "provider:retell": True}},
            {"revisions": {"connection:retell": version, "provider:retell": "7"}},
            {"revisions": []},
            {"result": None},
            {"result": {"status": "external_outcome_unconfirmed", "retryable": False}},
        ]:
            insert_snapshot(db, actor, session, version, **changes)
        for endpoint in ["unknownOperation", "createAgent", "createWebCall"]:
            insert_snapshot(
                db,
                actor,
                session,
                version,
                arguments={"endpoint": endpoint},
                result={
                    "provider": "retell",
                    "status": "completed",
                    "endpoint": endpoint,
                    "data": {},
                },
            )
        source = {"provider": "retell", "status": "completed", "endpoint": "listAgents", "data": {}}
        for changes in [
            {"provider": "other"},
            {"status": "ready"},
            {"status": "dispatch_reserved"},
        ]:
            insert_snapshot(db, actor, session, version, result={**source, **changes})
        missing = deepcopy(source)
        del missing["data"]
        insert_snapshot(db, actor, session, version, result=missing)
    monkeypatch.setattr(bridge, "request", fail_external)
    response = client.get("/crm/retell/results")
    assert response.status_code == 200, response.text
    assert response.json()["snapshots"] == [
        {
            "id": str(valid_id),
            "endpoint": "listAgents",
            "created_at": response.json()["snapshots"][0]["created_at"],
            "provider_revision": 7,
            "data": {"agent_id": "fixture"},
        }
    ]
    assert "private-input" not in response.text and "private-token" not in response.text
    assert "session_hash" not in response.text and "arguments" not in response.text


@pytest.mark.parametrize("change", ["defaults", "key", "disconnect", "toggle"])
def test_settings_changes_invalidate_old_snapshots(retelled, monkeypatch, change):
    client, owner, _, _, _, _ = retelled
    with psycopg.connect(owner) as db:
        actor, session, version = stored_identity(db, client)
        insert_snapshot(db, actor, session, version)
    assert len(client.get("/crm/retell/results").json()["snapshots"]) == 1
    if change == "toggle":
        with psycopg.connect(owner) as db:
            db.execute(
                "UPDATE crm.control_connections SET enabled=false,version=version+1 WHERE key='retell'"
            )
            db.execute(
                "UPDATE crm.control_connections SET enabled=true,version=version+1 WHERE key='retell'"
            )
    else:
        body = {"revision": 1}
        if change == "defaults":
            body["defaults"] = {"agent_id": "changed-agent"}
        elif change == "key":
            body["api_key"] = "fake_key_for_tests_only"
        path = "/crm/retell/disconnect" if change == "disconnect" else "/crm/retell/settings"
        assert client.post(path, json=body).status_code == 200
    monkeypatch.setattr(bridge, "request", fail_external)
    assert client.get("/crm/retell/results").json() == {"snapshots": [], "partial": True}


def test_missing_or_disabled_preference_returns_empty_without_external_calls(retelled, monkeypatch):
    client, owner, _, _, _, _ = retelled
    with psycopg.connect(owner) as db:
        actor, session, version = stored_identity(db, client)
        insert_snapshot(db, actor, session, version)
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='retell'")
    monkeypatch.setattr(bridge, "request", fail_external)
    assert client.get("/crm/retell/results").json() == {"snapshots": [], "partial": True}
    with psycopg.connect(owner, row_factory=dict_row) as db:
        preference = db.execute(
            "DELETE FROM crm.control_connections WHERE key='retell' RETURNING *"
        ).fetchone()
    try:
        assert client.get("/crm/retell/results").json() == {"snapshots": [], "partial": True}
    finally:
        with psycopg.connect(owner) as db:
            db.execute(
                "INSERT INTO crm.control_connections(key,enabled,version) VALUES (%s,%s,%s)",
                (preference["key"], preference["enabled"], preference["version"]),
            )


def test_new_login_cannot_restore_previous_session_results(retelled, monkeypatch):
    client, _, password, _, _, _ = retelled
    proposal = propose(client, "listAgents", {})
    assert approve(client, proposal).status_code == 200
    assert len(client.get("/crm/retell/results").json()["snapshots"]) == 1
    monkeypatch.setattr(bridge, "request", fail_external)
    assert client.post("/crm/auth/logout").status_code == 200
    with TestClient(app) as anonymous:
        assert anonymous.get("/crm/retell/results").status_code == 401
    response = client.post("/crm/auth/login", json={"username": "testadmin", "password": password})
    assert response.status_code == 200
    assert client.get("/crm/retell/results").json() == {"snapshots": [], "partial": True}


def test_scan_bound_is_latest_96_rows_not_an_account_inventory(retelled, monkeypatch):
    client, owner, _, _, _, _ = retelled
    with psycopg.connect(owner) as db:
        actor, session, version = stored_identity(db, client)
        insert_snapshot(
            db,
            actor,
            session,
            version,
            arguments={"endpoint": "listVoices"},
            result={
                "provider": "retell",
                "status": "completed",
                "endpoint": "listVoices",
                "data": [],
            },
        )
        # A transaction's now() timestamp is stable; force this row to be older.
        db.execute("UPDATE crm.hermes_proposals SET created_at=now()-interval '1 hour'")
        for _ in range(96):
            insert_snapshot(db, actor, session, version)
    monkeypatch.setattr(bridge, "request", fail_external)
    result = client.get("/crm/retell/results").json()
    assert result["partial"] is True
    assert [row["endpoint"] for row in result["snapshots"]] == ["listAgents"]
