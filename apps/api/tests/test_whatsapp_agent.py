"""Specialized agent identity and learning tests; no real provider traffic."""

# ruff: noqa: F811
import hashlib
import hmac
import json
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi import HTTPException
from test_crm import authenticated  # noqa: F401
from test_workflow_social import CONTACT, conversation, vendor  # noqa: F401

from app.control.service import require_connections
from app.social import whatsapp_agent as agent
from app.social import workflow

DOC = {
    "account_id": "b" * 24,
    "phone": "+573001110000",
    "developers": [
        {"name": "Developer One", "phone": "+573001110001"},
        {"name": "Developer Two", "phone": "+573001110002"},
    ],
    "instructions": "Answer briefly in Spanish.",
    "knowledge": "Project reference information.",
}


def payload(phone="573001110001"):
    return {
        "id": "event-1",
        "event": "message.received",
        "profiles": [{"id": "a" * 24}],
        "account": {"id": DOC["account_id"], "platform": "whatsapp"},
        "conversation": {
            "id": "internal-thread",
            "platformConversationId": "wa-thread",
            "participantId": phone,
            "platform": "whatsapp",
        },
        "message": {
            "id": "internal-message",
            "platformMessageId": "wamid.source",
            "platform": "whatsapp",
            "conversationId": "internal-thread",
            "direction": "incoming",
            "sender": {"id": phone, "phoneNumber": "+" + phone},
            "text": "/aprender Verified new fact",
            "sentAt": datetime.now(UTC).isoformat(),
        },
    }


def test_developer_identity_is_exact_e164_not_name_or_substring():
    doc = agent.Document.model_validate(DOC).model_dump()
    assert agent.developer(doc, "573001110001") == "Developer One"
    assert agent.developer(doc, "573001110002") == "Developer Two"
    assert agent.developer(doc, "573001110003") is None
    assert agent.developer(doc, "3001110001") is None
    assert agent.developer(doc, "Developer One") is None
    with pytest.raises(ValueError):
        agent.Document.model_validate({**DOC, "developers": [DOC["developers"][0]] * 2})


def test_signed_payload_parser_never_promotes_display_name_or_other_accounts():
    event = agent.normalize(payload(), "a" * 24)
    assert event["text"] == "/aprender Verified new fact"
    assert event["participant_id"] == "573001110001"
    for key, value in [("test", True), ("metadata", {"standby": True})]:
        assert agent.normalize({**payload(), key: value}, "a" * 24) is None
    altered = payload("573001110003")
    altered["message"]["sender"]["name"] = "Developer One"
    assert agent.developer(DOC, agent.normalize(altered, "a" * 24)["participant_id"]) is None
    altered["message"]["sender"]["phoneNumber"] = "+573001110001"
    assert agent.normalize(altered, "a" * 24) is None
    assert agent.normalize(payload(), "c" * 24) is None
    altered = payload()
    altered["message"]["direction"] = "outgoing"
    assert agent.normalize(altered, "a" * 24) is None


def test_customer_messages_cannot_create_learning_or_execution_commands():
    assert agent.learning_command("/aprender New fact", None) is None
    assert agent.learning_command("/aprender New fact", "Developer One") == "New fact"
    assert agent.learning_command("please learn this", "Developer One") is None
    assert agent.learning_command("/ejecutar rm -rf", "Developer One") is None
    assert agent.learning_command("/aprender " + "a" * 1001, "Developer One") is None


@pytest.fixture
def configured(authenticated, monkeypatch):
    client, owner, _ = authenticated
    with psycopg.connect(owner) as db:
        db.execute(
            "TRUNCATE crm.whatsapp_agent,crm.whatsapp_agent_revisions,crm.whatsapp_agent_jobs,crm.whatsapp_agent_lessons CASCADE"
        )
        db.execute("TRUNCATE crm.social_webhook_events")
        db.execute("TRUNCATE crm.sara_profile,crm.sara_profile_versions")
        db.execute(
            "UPDATE crm.control_connections SET enabled=true WHERE key IN ('hermes','zernio','whatsapp')"
        )
    credentials = {
        "api_key": "fake-private",
        "profile_id": "a" * 24,
        "webhook_secret": "fake-hmac",
        "webhook_registered": True,
    }
    monkeypatch.setattr(agent.config, "required", lambda: credentials)
    monkeypatch.setattr(agent, "readiness", lambda *args, **kwargs: {"ready": True, "reason": None})
    response = client.patch(
        "/crm/social/whatsapp-agent",
        json={**DOC, "version": 0, "enabled": True, "consent_confirmed": True},
    )
    assert response.status_code == 200, response.text
    return client, owner, credentials


def send(client, credentials, event):
    raw = json.dumps(event).encode()
    return client.post(
        "/integrations/zernio/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Zernio-Event-Id": event["id"],
            "X-Zernio-Event": event["event"],
            "X-Zernio-Signature": hmac.new(
                credentials["webhook_secret"].encode(), raw, hashlib.sha256
            ).hexdigest(),
        },
    )


def jobs(owner):
    from psycopg.rows import dict_row

    with psycopg.connect(owner, row_factory=dict_row) as db:
        return db.execute("SELECT * FROM crm.whatsapp_agent_jobs ORDER BY created_at").fetchall()


def mock_dispatch(monkeypatch):
    sent = []
    monkeypatch.setattr(agent, "source_verified", lambda *args: True)
    monkeypatch.setattr(
        workflow,
        "prepare_literal_reply",
        lambda db, job, text: {
            "credential_revision": workflow._digest(agent.config.required()),
            "reply": text,
        },
    )

    def dispatch(plan, key):
        sent.append((plan, key))
        return {"state": "completed", "receipt": {"status": "accepted"}}

    monkeypatch.setattr(workflow, "dispatch", dispatch)
    return sent


def test_auth_csrf_version_and_explicit_activation(configured):
    client, _, _ = configured
    assert (
        client.patch(
            "/crm/social/whatsapp-agent", json={**DOC, "version": 1, "enabled": True}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/crm/social/whatsapp-agent", json={**DOC, "version": 0, "enabled": False}
        ).status_code
        == 409
    )
    client.headers["X-CSRF-Token"] = "wrong"
    assert (
        client.patch(
            "/crm/social/whatsapp-agent", json={**DOC, "version": 1, "enabled": False}
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert client.get("/crm/social/whatsapp-agent").status_code == 401


def test_first_seen_only_matching_new_inbound_enrolls(configured):
    client, owner, c = configured
    event = payload()
    assert send(client, c, event).status_code == 200
    assert send(client, c, event).status_code == 200
    duplicate = {**event, "id": "other-delivery-id"}
    assert send(client, c, duplicate).status_code == 200
    other = payload()
    other["id"] = "foreign"
    other["account"]["id"] = "d" * 24
    assert send(client, c, other).status_code == 200
    outgoing = payload()
    outgoing["id"] = "outgoing"
    outgoing["message"]["direction"] = "outgoing"
    assert send(client, c, outgoing).status_code == 200
    assert len(jobs(owner)) == 1
    invalid = client.post("/integrations/zernio/webhook", json=payload())
    assert invalid.status_code == 401
    assert len(jobs(owner)) == 1


def test_verified_developer_proposes_learning_web_publishes_and_revokes(configured, monkeypatch):
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)
    monkeypatch.setattr(
        agent.bridge,
        "request",
        lambda *args, **kwargs: pytest.fail(
            "Learning cannot invoke an administrative agent or model"
        ),
    )
    assert send(client, c, payload()).status_code == 200
    agent.tick()
    assert len(sent) == 1 and "pendiente" in sent[0][0]["reply"]
    state = client.get("/crm/social/whatsapp-agent").json()
    assert state["knowledge"] == DOC["knowledge"]
    assert state["lessons"][0]["author"] == "Developer One"
    assert state["lessons"][0]["state"] == "pending"
    lesson_id = state["lessons"][0]["id"]
    result = client.post(
        f"/crm/social/whatsapp-agent/lessons/{lesson_id}/approve",
        json={"version": state["version"]},
    )
    assert result.status_code == 200, result.text
    assert "Verified new fact" in result.json()["knowledge"]
    assert not result.json()["enabled"]
    assert result.json()["version"] == 2
    assert (
        client.post(
            f"/crm/social/whatsapp-agent/lessons/{lesson_id}/approve", json={"version": 2}
        ).status_code
        == 409
    )
    assert jobs(owner)[0]["state"] == "completed"


def test_customer_cannot_train_and_has_no_admin_context(configured, monkeypatch):
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)
    captured = []

    def model(path, body, **kwargs):
        assert path == "/public-reply" and set(body) == {"messages", "instructions", "knowledge"}
        captured.append(body)
        return {"ok": True, "tools": 0, "response": "Hola, soy Sara. ¿Cómo puedo ayudarte?"}

    monkeypatch.setattr(agent.bridge, "request", model)
    event = payload("573001110003")
    assert send(client, c, event).status_code == 200
    agent.tick()
    assert len(sent) == 1 and captured[0]["messages"] == [
        {"role": "user", "content": event["message"]["text"]}
    ]
    assert client.get("/crm/social/whatsapp-agent").json()["lessons"] == []
    agent.tick()
    assert len(sent) == 1
    assert jobs(owner)[0]["state"] == "completed"


def test_source_mismatch_never_trains_or_sends(configured, monkeypatch):
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)
    monkeypatch.setattr(agent, "source_verified", lambda *args: False)
    send(client, c, payload())
    agent.tick()
    assert sent == []
    assert client.get("/crm/social/whatsapp-agent").json()["lessons"] == []
    assert jobs(owner)[0]["state"] == "blocked"


def test_revocation_during_model_prevents_reservation_and_send(configured, monkeypatch):
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)

    def model(*args, **kwargs):
        assert (
            client.patch(
                "/crm/social/whatsapp-agent", json={**DOC, "version": 1, "enabled": False}
            ).status_code
            == 200
        )
        return {"ok": True, "tools": 0, "response": "No debe enviarse"}

    monkeypatch.setattr(agent.bridge, "request", model)
    send(client, c, payload("573001110003"))
    agent.tick()
    assert sent == [] and jobs(owner)[0]["state"] == "blocked"


def test_unknown_dispatch_never_replays(configured, monkeypatch):
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)

    def unknown(plan, key):
        sent.append(key)
        return {"state": "unknown", "error": "zernio_submission_unknown"}

    monkeypatch.setattr(workflow, "dispatch", unknown)
    send(client, c, payload())
    agent.tick()
    agent.tick()
    assert len(sent) == 1 and jobs(owner)[0]["state"] == "unknown"


def test_literal_reply_has_no_placeholder_expansion_and_keeps_checks(vendor):
    _, binding = conversation(vendor)
    source = {"id": "job-1", **binding, "participant_id": CONTACT["phone"].lstrip("+")}
    plan = workflow.prepare_literal_reply(None, source, "Literal {{not_a_command}}")
    assert plan["payload"]["message"] == "Literal {{not_a_command}}"
    assert workflow.dispatch(plan, "reserved-public-reply")["state"] == "completed"
    vendor["conversations"][0]["threadControl"] = "human"
    with pytest.raises(HTTPException):
        workflow.prepare_literal_reply(None, source, "No takeover")


def test_disable_hermes_during_generation_revokes_send(configured, vendor, monkeypatch):
    client, owner, creds = configured
    vendor["credentials"] = creds
    conversation(vendor)
    monkeypatch.setattr(workflow, "connect", agent.connect)
    monkeypatch.setattr(workflow, "require_connections", require_connections)
    monkeypatch.setattr(agent, "source_verified", lambda *a: True)
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.control_connections SET enabled=true WHERE key IN ('hermes','zernio','whatsapp')"
        )

    def model(*a, **k):
        with psycopg.connect(owner) as db:
            db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='hermes'")
        return {"ok": True, "tools": 0, "response": "Should not send after revocation"}

    monkeypatch.setattr(agent.bridge, "request", model)
    event = payload("573001234567")
    event["conversation"]["platformConversationId"] = "thread:1"
    assert send(client, creds, event).status_code == 200
    agent.tick()
    posts = [c for c in vendor["calls"] if c[0] == "POST"]
    assert not posts


REAL_READINESS = agent.readiness


def test_first_worker_tick_after_restart_keeps_pending_job(configured, monkeypatch):
    from types import SimpleNamespace

    client, _owner, creds = configured
    event = payload("573001234567")
    assert send(client, creds, event).status_code == 200
    monkeypatch.setattr(agent, "readiness", REAL_READINESS)
    monkeypatch.setattr(agent, "worker_enabled", lambda: True)
    monkeypatch.setattr(
        agent, "_thread", SimpleNamespace(is_alive=lambda: True, join=lambda **k: None)
    )
    monkeypatch.setattr(agent, "_heartbeat", 0.0)
    monkeypatch.setattr(agent, "require_connections", lambda *a: None)
    monkeypatch.setattr(
        agent.bridge, "request", lambda *a, **k: {"available": True, "public_reply_available": True}
    )
    monkeypatch.setattr(
        workflow,
        "_account",
        lambda *a, **k: {
            "platform": "whatsapp",
            "metadata": {"displayPhoneNumber": "+573001110000"},
        },
    )
    monkeypatch.setattr(agent, "source_verified", lambda *a: True)
    monkeypatch.setattr(agent, "generate", lambda *a: "Hola")
    monkeypatch.setattr(
        workflow,
        "prepare_literal_reply",
        lambda *a: {"credential_revision": workflow._digest(creds)},
    )
    sent = []

    def dispatch(*a):
        sent.append(True)
        return {"state": "completed"}

    monkeypatch.setattr(workflow, "dispatch", dispatch)
    agent.tick()
    assert sent


def test_shared_profile_cas_and_published_content_replace_channel_duplicates(configured, monkeypatch):
    from app.crm.database import connect
    from app.sara import profile
    from app.sara.profile_models import ProfileUpdate
    client, owner, c = configured
    state = client.get("/crm/social/whatsapp-agent").json()
    # Missing or stale shared versions cannot silently overwrite newer published facts.
    changed = {**DOC, "knowledge": "Stale channel knowledge", "version": state["version"], "enabled": False}
    assert client.patch("/crm/social/whatsapp-agent", json=changed).status_code == 409
    assert client.patch("/crm/social/whatsapp-agent", json={**changed, "shared_profile_version": state["shared_profile_version"]-1}).status_code == 409
    sent = mock_dispatch(monkeypatch)
    captured = []
    def model(path, body, **kwargs):
        captured.append(body)
        return {"ok": True, "tools": 0, "response": "Published knowledge response"}
    monkeypatch.setattr(agent.bridge, "request", model)
    with connect() as db:
        row = db.execute("SELECT id,username FROM crm.users WHERE username='testadmin'").fetchone()
        profile.update(db, ProfileUpdate(version=state["shared_profile_version"], knowledge="New shared verified knowledge"), row)
    event = payload("573001110003")
    assert send(client, c, event).status_code == 200
    agent.tick()
    assert len(sent) == 1 and captured[0]["knowledge"] == "New shared verified knowledge"
    assert jobs(owner)[0]["shared_profile_version"] == state["shared_profile_version"]+1
    assert client.get("/crm/social/whatsapp-agent").json()["knowledge"] == "New shared verified knowledge"


def test_shared_profile_change_during_public_generation_revokes_send(configured, monkeypatch):
    from app.crm.database import connect
    from app.sara import profile
    from app.sara.profile_models import ProfileUpdate
    client, owner, c = configured
    sent = mock_dispatch(monkeypatch)
    def model(*args, **kwargs):
        with connect() as db:
            actor = db.execute("SELECT id,username FROM crm.users WHERE username='testadmin'").fetchone()
            current = profile.get(db)
            profile.update(db, ProfileUpdate(version=current["version"], knowledge="Changed while generating"), actor)
        return {"ok": True, "tools": 0, "response": "Obsolete response"}
    monkeypatch.setattr(agent.bridge, "request", model)
    assert send(client, c, payload("573001110003")).status_code == 200
    agent.tick()
    assert not sent and jobs(owner)[0]["state"] == "blocked"


def test_history_is_scoped_to_participant_and_shared_published_version(configured, monkeypatch):
    from app.crm.database import connect
    from app.sara import profile
    from app.sara.profile_models import ProfileUpdate
    client, _owner, c = configured
    mock_dispatch(monkeypatch)
    captured = []
    def model(path, body, **kwargs):
        captured.append(body["messages"])
        return {"ok": True, "tools": 0, "response": "Response for this participant"}
    monkeypatch.setattr(agent.bridge, "request", model)
    for index, phone in enumerate(("573001110003", "573001110003", "573001110004", "573001110003")):
        if index == 3:
            with connect() as db:
                actor = db.execute("SELECT id,username FROM crm.users WHERE username='testadmin'").fetchone()
                current = profile.get(db)
                profile.update(db, ProfileUpdate(version=current["version"], greeting="New greeting"), actor)
        event = payload(phone); event["id"] = f"history-{index}"; event["message"]["platformMessageId"] = f"source-{index}"; event["message"]["text"] = f"Message {index}"
        assert send(client, c, event).status_code == 200
        agent.tick()
    assert len(captured[0]) == 1 and len(captured[1]) == 3
    assert captured[1][0]["content"] == "Message 0"
    assert captured[2] == [{"role": "user", "content": "Message 2"}]
    assert captured[3] == [{"role": "user", "content": "Message 3"}]
