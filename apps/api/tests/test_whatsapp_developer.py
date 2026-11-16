"""Verified channel grants, scoped tool dispatch and browser-independent revocation."""
# ruff: noqa: F811
import copy
import json
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from test_crm import authenticated  # noqa: F401
from test_whatsapp_agent import configured, payload, send  # noqa: F401

from app.crm.database import connect
from app.social import whatsapp_agent as agent


def test_developer_scope_is_explicit_and_definitions_cannot_smuggle_crm():
    from app.hermes import developer

    assert "sara.config.update" in developer.ACTIONS
    assert "crm.workspace" not in developer.ACTIONS
    assert "control.connection.update" not in developer.ACTIONS
    assert developer.safe_definition({"kind": "tool", "definition": {"action": "sara.config.get", "defaults": {}}})
    assert not developer.safe_definition({"kind": "tool", "definition": {"action": "crm.contact.create", "defaults": {}}})
    assert not developer.safe_definition({"kind": "plugin", "definition": {"actions": ["control.extension.install"]}})


def issue(configured, monkeypatch, phone="573001110001"):
    from app.hermes import developer

    client, owner, credentials = configured
    event = payload(phone)
    event["message"]["text"] = "Create a useful skill for answering customers"
    assert send(client, credentials, event).status_code == 200
    job, row = agent.claim()
    monkeypatch.setattr(agent, "source_verified", lambda *_: True)
    with connect() as db:
        run_id, token = developer.issue(db, job["id"])
    return client, owner, job, row, run_id, {"Authorization": "Bearer " + token}


def call(client, headers, action, arguments, key=None):
    return client.post("/internal/hermes/call", json={"call_id": key or uuid4().hex, "action": action, "arguments": arguments}, headers=headers)


@pytest.mark.parametrize("phone,name", [("573001110001", "Developer One"), ("573001110002", "Developer Two")])
def test_claim_identifies_only_the_current_verified_developer(configured, monkeypatch, phone, name):
    client, owner, job, _row, _run_id, headers = issue(configured, monkeypatch, phone)
    claim = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert claim.status_code == 200
    context = json.loads(claim.json()["prompt"])
    assert context == {
        "channel": "whatsapp_developer",
        "verified_developer_name": name,
        "message": job["content"],
    }
    assert phone not in claim.json()["prompt"]
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT content FROM crm.whatsapp_agent_jobs WHERE id=%s", (job["id"],)).fetchone()[0] == job["content"]


def test_real_issue_claim_owned_lifecycle_replay_and_no_browser_session(configured, monkeypatch):
    client, owner, job, _row, run_id, headers = issue(configured, monkeypatch)
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT session_hash,authentication FROM crm.hermes_runs WHERE id=%s", (run_id,)).fetchone() == (None, "whatsapp_developer")
        before = db.execute("SELECT count(*) FROM crm.sessions").fetchone()[0]
    claim = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert claim.status_code == 200, claim.text
    actions = claim.json()["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    assert "sara.config.get" in actions and "crm.workspace" not in actions
    assert claim.json()["configuration"]["version"] >= 1
    data = {"kind": "tool", "name": "Published preferences", "definition": {"action": "sara.config.get", "defaults": {}}}
    created = call(client, headers, "control.extension.create", data, "create-once")
    assert created.status_code == 200, created.text
    assert created.json() == call(client, headers, "control.extension.create", data, "create-once").json()
    item = created.json()["result"]
    assert item["origin"] == "sara" and not item["enabled"]
    args = {"id": item["id"], "version": item["version"]}
    assert call(client, headers, "control.extension.test", args).json()["result"]["side_effects"] is False
    installed = call(client, headers, "control.extension.install", args).json()["result"]
    assert installed["enabled"]
    assert call(client, headers, "crm.workspace", {}).json()["result"]["error"] == "capability_not_in_run"
    assert call(client, headers, "control.extension.create", {"kind": "tool", "name": "Unsafe", "definition": {"action": "crm.workspace", "defaults": {}}}).json()["result"]["error"] == "developer_action_denied"
    catalog = call(client, headers, "control.catalog", {}).json()["result"]
    assert {item["id"] for item in catalog["items"]} == {installed["id"]}
    assert client.post("/internal/hermes/finish", json={"reply": "Installed."}, headers=headers).status_code == 200
    # Fresh turn exposes and executes the safe owned custom tool; no fake sessions exist.
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.whatsapp_agent_jobs SET state='completed' WHERE id=%s", (job["id"],))
    event = payload(); event["id"] = "next-turn"; event["message"]["platformMessageId"] = "wamid.next"
    assert send(client, configured[2], event).status_code == 200
    next_job, _ = agent.claim()
    from app.hermes import developer
    with connect() as db:
        _, next_token = developer.issue(db, next_job["id"])
    next_headers = {"Authorization": "Bearer " + next_token}
    claim2 = client.post("/internal/hermes/claim", json={}, headers=next_headers)
    assert "custom." + installed["id"] in claim2.json()["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    assert call(client, next_headers, "custom." + installed["id"], {}).json()["result"]["version"] >= 1
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.sessions").fetchone()[0] == before
        assert db.execute("SELECT count(*) FROM crm.control_items WHERE name='Published preferences'").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["developer", "owner", "credential", "job", "agent"])
def test_live_authority_revocation_blocks_claim(configured, monkeypatch, mutation):
    client, owner, job, row, _, headers = issue(configured, monkeypatch)
    with psycopg.connect(owner) as db:
        if mutation == "developer":
            doc = copy.deepcopy(row["document"]); doc["developers"] = []
            from psycopg.types.json import Jsonb
            db.execute("UPDATE crm.whatsapp_agent SET document=%s", (Jsonb(doc),))
        elif mutation == "owner":
            db.execute("UPDATE crm.users SET enabled=false WHERE username='testadmin'")
        elif mutation == "credential":
            configured[2]["api_key"] = "rotated"
        elif mutation == "job":
            db.execute("UPDATE crm.whatsapp_agent_jobs SET state='blocked' WHERE id=%s", (job["id"],))
        else:
            db.execute("UPDATE crm.whatsapp_agent SET enabled=false")
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 401


@pytest.mark.parametrize("phone,verified", [("573001110003", True), ("573001110001", False)])
def test_customer_and_unverified_source_cannot_issue(configured, monkeypatch, phone, verified):
    from app.hermes import developer
    client, _, c = configured
    assert send(client, c, payload(phone)).status_code == 200
    job, _ = agent.claim()
    monkeypatch.setattr(agent, "source_verified", lambda *_: verified)
    with pytest.raises(HTTPException), connect() as db:
        developer.issue(db, job["id"])


def test_revocation_after_claim_blocks_calls_and_finish(configured, monkeypatch):
    client, owner, _job, _row, _, headers = issue(configured, monkeypatch)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    assert call(client, headers, "sara.config.get", {}, "read").status_code == 200
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.whatsapp_agent SET version=version+1")
    assert call(client, headers, "sara.config.get", {}, "read").status_code == 401
    assert client.post("/internal/hermes/finish", json={"reply": "No authority"}, headers=headers).status_code == 401


def test_issuer_refuses_legacy_unowned_configuration_and_source_replay(configured, monkeypatch):
    from app.hermes import developer
    _client, owner, job, _, _, _ = issue(configured, monkeypatch)
    with pytest.raises(HTTPException) as error, connect() as db:
        developer.issue(db, job["id"])
    assert error.value.detail == "developer_source_already_used"
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.whatsapp_agent SET owner_id=NULL")
    with pytest.raises(HTTPException), connect() as db:
        developer.issue(db, job["id"])


def test_catalog_skills_and_lifecycle_never_leak_another_owner(configured, monkeypatch):
    from psycopg.types.json import Jsonb
    client, owner, _, _, _, headers = issue(configured, monkeypatch)
    with psycopg.connect(owner) as db:
        other = db.execute("INSERT INTO crm.users(username,password_hash) VALUES('otherdeveloper','not-a-login-hash') RETURNING id").fetchone()[0]
        foreign = db.execute("INSERT INTO crm.control_items(actor_id,kind,name,definition,enabled,origin) VALUES(%s,'skill','Private other skill',%s,true,'sara') RETURNING id,version", (other, Jsonb({"content": "Private other owner information"}))).fetchone()
    response = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert response.status_code == 200
    assert "Private other" not in str(response.json())
    assert call(client, headers, "control.catalog", {}).json()["result"]["items"] == []
    result = call(client, headers, "control.extension.install", {"id": str(foreign[0]), "version": foreign[1]})
    assert result.json()["result"]["error"] == "not_found"
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT enabled,version FROM crm.control_items WHERE id=%s", (foreign[0],)).fetchone() == (True, foreign[1])


def test_full_worker_developer_learns_through_real_scoped_broker(configured, monkeypatch):
    from test_whatsapp_agent import jobs, mock_dispatch
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)
    captured = []

    def private_bridge(path, body, **kwargs):
        assert path == "/run" and set(body) == {"token"}
        headers = {"Authorization": "Bearer " + body["token"]}
        claim = client.post("/internal/hermes/claim", json={}, headers=headers)
        assert claim.status_code == 200, claim.text
        captured.append(claim.json())
        version = call(client, headers, "sara.config.get", {}).json()["result"]["version"]
        result = call(client, headers, "sara.learn", {"version": version, "content": "Authorized developer lesson"}, "teach-once")
        captured[-1]["learning_receipt"] = result.json()
        assert "Authorized developer lesson" in result.json()["result"]["knowledge"]
        # Idempotent call receipt does not add the lesson twice.
        assert call(client, headers, "sara.learn", {"version": version, "content": "Authorized developer lesson"}, "teach-once").json() == result.json()
        finished = client.post("/internal/hermes/finish", json={"reply": "Conocimiento publicado."}, headers=headers)
        captured[-1]["finish_status"] = finished.status_code
        assert finished.status_code == 200, finished.text
        return finished.json()

    monkeypatch.setattr(agent.bridge, "request", private_bridge)
    event = payload(); event["message"]["text"] = "Learn this approved fact and use it in your future replies"
    assert send(client, c, event).status_code == 200
    agent.tick()
    assert len(captured) == 1 and len(sent) == 1, {"learning": captured[0].get("learning_receipt"), "finish": captured[0].get("finish_status"), "jobs": [(j["state"], j["error"]) for j in jobs(owner)]}
    assert jobs(owner)[0]["state"] == "completed"
    state = client.get("/crm/social/whatsapp-agent").json()
    assert state["knowledge"].count("Authorized developer lesson") == 1
    assert jobs(owner)[0]["shared_profile_version"] == state["shared_profile_version"]
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT source FROM crm.sara_profile_versions ORDER BY version DESC LIMIT 1").fetchone()[0] == "whatsapp_developer"
