"""Persistent Sara API uses only the guarded isolated CRM database."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_crm import authenticated  # noqa: F401

from app.hermes import bridge
from app.main import app


def test_sara_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/crm/sara/conversations").status_code == 401


def test_conversation_and_failed_message_are_persistent_and_idempotent(authenticated):
    client, _, _ = authenticated
    response = client.post("/crm/sara/conversations", json={})
    assert response.status_code == 201
    conversation = response.json()
    path = f"/crm/sara/conversations/{conversation['id']}/messages"
    body = {"request_id": str(uuid4()), "message": "Hola Sara", "attachment_ids": []}
    first = client.post(path, json=body)
    assert first.status_code == 200 and first.json()["state"] == "failed"
    assert first.json()["assistant_message"] is None
    assert client.post(path, json=body).json() == first.json()
    history = client.get(path).json()["messages"]
    assert len(history) == 1 and history[0]["content"] == "Hola Sara"


@pytest.fixture
def sara_ready(authenticated, monkeypatch):
    client, owner, password = authenticated
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='hermes'")
    monkeypatch.setattr(
        bridge,
        "health",
        lambda: {
            "configured": True,
            "available": True,
            "history_available": True,
            "transcription_available": False,
            "model": "fixture",
        },
    )
    try:
        yield client, owner, password
    finally:
        with psycopg.connect(owner) as db:
            db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='hermes'")


def conversation(client, title="Prueba Sara"):
    result = client.post("/crm/sara/conversations", json={"title": title})
    assert result.status_code == 201, result.text
    return result.json()


def payload(message="Hola Sara", attachments=None, request_id=None):
    return {
        "request_id": request_id or str(uuid4()),
        "message": message,
        "attachment_ids": attachments or [],
    }


def fake_runtime(monkeypatch, calls, reply="Respuesta real de la fixture", action=None, wait=None):
    def request(path, body, timeout):
        assert path == "/run" and timeout == 90
        with TestClient(app) as runtime:
            headers = {"Authorization": "Bearer " + body["token"]}
            claim = runtime.post("/internal/hermes/claim", json={}, headers=headers)
            assert claim.status_code == 200, claim.text
            calls.append(claim.json())
            if wait:
                wait()
            if action:
                response = runtime.post(
                    "/internal/hermes/call",
                    json={"call_id": "one", "action": action[0], "arguments": action[1]},
                    headers=headers,
                )
                assert response.status_code == 200, response.text
            response = runtime.post(
                "/internal/hermes/finish", json={"reply": reply}, headers=headers
            )
            assert response.status_code == 200, response.text
            return response.json()

    monkeypatch.setattr(bridge, "request", request)


def test_successful_turn_history_and_idempotent_retry(sara_ready, monkeypatch):
    client, _, _ = sara_ready
    chat = conversation(client)
    path = f"/crm/sara/conversations/{chat['id']}/messages"
    calls = []
    fake_runtime(monkeypatch, calls)
    body = payload()
    response = client.post(path, json=body)
    assert response.status_code == 200 and response.json()["state"] == "completed"
    assert response.json()["assistant_message"]["content"] == "Respuesta real de la fixture"
    assert "history" not in calls[0]
    assert client.post(path, json=body).json() == response.json()
    assert len(calls) == 1
    assert client.post(path, json={**body, "message": "Otro texto"}).status_code == 409
    second = client.post(path, json=payload("¿Qué dijimos?"))
    assert second.json()["state"] == "completed"
    assert calls[1]["history"] == [
        {"role": "user", "content": "Hola Sara"},
        {"role": "assistant", "content": "Respuesta real de la fixture"},
    ]
    assert len(client.get(path).json()["messages"]) == 4
    other = conversation(client)
    assert (
        client.post(f"/crm/sara/conversations/{other['id']}/messages", json=body).status_code == 409
    )


def test_only_one_provider_run_for_concurrent_duplicates(sara_ready, monkeypatch):
    client, _, _ = sara_ready
    chat = conversation(client)
    path = f"/crm/sara/conversations/{chat['id']}/messages"
    entered, release = Event(), Event()

    def wait():
        entered.set()
        assert release.wait(5)

    calls = []
    fake_runtime(monkeypatch, calls, wait=wait)
    body = payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lambda: client.post(path, json=body))
        try:
            assert entered.wait(5)
            pending = client.post(path, json=body)
            assert pending.status_code == 200 and pending.json()["state"] == "pending"
            assert pending.json()["assistant_message"] is None
            assert client.post(path, json=payload("Otro turno")).status_code == 409
        finally:
            release.set()
        assert first.result(timeout=5).json()["state"] == "completed"
    assert len(calls) == 1


def test_failed_bridge_does_not_fabricate_reply_or_repeat_run(sara_ready, monkeypatch):
    client, owner, _ = sara_ready
    path = f"/crm/sara/conversations/{conversation(client)['id']}/messages"
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise HTTPException(503, "private provider error")

    monkeypatch.setattr(bridge, "request", unavailable)
    body = payload()
    response = client.post(path, json=body)
    assert response.json()["state"] == "failed" and response.json()["assistant_message"] is None
    assert "private provider error" not in response.text
    assert client.post(path, json=body).json() == response.json()
    assert len(calls) == 1
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_runs").fetchone()[0] == 1


def test_expired_pending_lease_recovers_once_without_rerunning(sara_ready, monkeypatch):
    client, owner, _ = sara_ready
    chat = conversation(client)
    path = f"/crm/sara/conversations/{chat['id']}/messages"
    monkeypatch.setattr(bridge, "request", lambda *args, **kwargs: {})
    body = payload()
    first = client.post(path, json=body).json()
    user_id = first["user_message"]["id"]
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.sara_messages SET state='pending' WHERE id=%s", (user_id,))
        db.execute(
            "UPDATE crm.sara_conversations SET active_message_id=%s,lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (user_id, chat["id"]),
        )
    assert client.get(path).json()["messages"][0]["state"] == "failed"
    assert client.post(path, json=body).json()["state"] == "failed"
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_runs").fetchone()[0] == 1


def test_durable_finished_run_recovers_after_lost_http_ack(sara_ready, monkeypatch):
    client, owner, _ = sara_ready
    chat = conversation(client)
    path = f"/crm/sara/conversations/{chat['id']}/messages"
    calls = []
    fake_runtime(monkeypatch, calls)
    original = bridge.request

    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise HTTPException(503, "ack lost")

    monkeypatch.setattr(bridge, "request", lost_ack)
    response = client.post(path, json=payload()).json()
    assert response["state"] == "completed"
    with psycopg.connect(owner) as db:
        db.execute("DELETE FROM crm.sara_messages WHERE role='assistant'")
        db.execute("UPDATE crm.sara_messages SET state='pending'")
        db.execute(
            "UPDATE crm.sara_conversations SET active_message_id=%s,lease_expires_at=now()-interval '1 second' WHERE id=%s",
            (response["user_message"]["id"], chat["id"]),
        )
    history = client.get(path).json()["messages"]
    assert len(history) == 2 and history[1]["role"] == "assistant"
    assert len(calls) == 1


def test_logout_keeps_history_without_reviving_proposal_authority(sara_ready, monkeypatch):
    client, _, password = sara_ready
    chat = conversation(client)
    path = f"/crm/sara/conversations/{chat['id']}/messages"
    calls = []
    fake_runtime(
        monkeypatch,
        calls,
        action=(
            "crm.contact.create",
            {"name": "Propuesta Sara", "phone": "3001234567", "source": "web"},
        ),
    )
    response = client.post(path, json=payload()).json()
    proposal = response["assistant_message"]["proposals"][0]
    assert proposal["resolvable"] is True
    assert client.post("/crm/auth/logout").status_code == 200
    login = client.post(
        "/crm/auth/login", json={"username": "testadmin", "password": password}
    ).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    history = client.get(path).json()["messages"]
    assert len(history) == 2 and history[1]["proposals"][0]["resolvable"] is False
    assert (
        client.post(
            f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": proposal["version"]}
        ).status_code
        == 404
    )


def test_owner_acl_csrf_rename_and_conversation_paging(sara_ready):
    client, owner, password = sara_ready
    chat = conversation(client)
    assert (
        client.patch(f"/crm/sara/conversations/{chat['id']}", json={"title": "Renombrada"}).json()[
            "title"
        ]
        == "Renombrada"
    )
    assert (
        client.post("/crm/sara/conversations", json={}, headers={"X-CSRF-Token": "bad"}).status_code
        == 403
    )
    assert (
        client.post(
            "/crm/sara/conversations", json={}, headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    with psycopg.connect(owner) as db:
        db.execute(
            "INSERT INTO crm.users(username,password_hash) SELECT 'otheradmin',password_hash FROM crm.users WHERE username='testadmin'"
        )
        db.execute(
            "INSERT INTO crm.sara_conversations(owner_id,title) SELECT id,'Página' FROM crm.users,generate_series(1,31) WHERE username='testadmin'"
        )
    first = client.get("/crm/sara/conversations").json()
    assert len(first["conversations"]) == 30 and first["next_cursor"]
    second = client.get("/crm/sara/conversations", params={"before": first["next_cursor"]}).json()
    assert len(second["conversations"]) == 2
    assert not (
        {row["id"] for row in first["conversations"]}
        & {row["id"] for row in second["conversations"]}
    )
    with TestClient(app, base_url="http://127.0.0.1:4320") as other:
        login = other.post(
            "/crm/auth/login",
            json={"username": "otheradmin", "password": password},
            headers={"Origin": "http://127.0.0.1:4320"},
        ).json()
        other.headers.update(
            {"Origin": "http://127.0.0.1:4320", "X-CSRF-Token": login["csrf_token"]}
        )
        assert other.get(f"/crm/sara/conversations/{chat['id']}/messages").status_code == 404
        assert (
            other.patch(f"/crm/sara/conversations/{chat['id']}", json={"title": "No"}).status_code
            == 404
        )
        assert (
            other.post(f"/crm/sara/conversations/{chat['id']}/messages", json=payload()).status_code
            == 404
        )
        assert (
            other.get("/crm/sara/conversations", params={"before": chat["id"]}).status_code == 404
        )


def test_history_is_bounded_text_only_and_claim_compatibility(sara_ready, monkeypatch):
    client, _, _ = sara_ready
    path = f"/crm/sara/conversations/{conversation(client)['id']}/messages"
    calls = []
    fake_runtime(monkeypatch, calls, reply="r" * 5000)
    for _ in range(5):
        assert client.post(path, json=payload("u" * 4000)).json()["state"] == "completed"
    history = calls[-1]["history"]
    assert len(history) <= 8 and sum(len(row["content"]) for row in history) <= 16000
    assert all(set(row) == {"role", "content"} and len(row["content"]) <= 4096 for row in history)
    assert client.post("/crm/hermes/chat", json={"message": "Legacy"}).status_code == 200
    assert "history" not in calls[-1]


def test_message_pagination_has_byte_budget_and_exact_results(sara_ready):
    client, owner, _ = sara_ready
    chat = conversation(client)
    with psycopg.connect(owner) as db:
        db.execute(
            """INSERT INTO crm.sara_messages(conversation_id,owner_id,request_id,role,content,state,results)
            SELECT %s,id,gen_random_uuid(),'assistant','Página','completed',
            jsonb_build_array(jsonb_build_object('body',repeat('x',60000))) FROM crm.users,generate_series(1,30)
            WHERE username='testadmin'""",
            (chat["id"],),
        )
    path = f"/crm/sara/conversations/{chat['id']}/messages"
    page = client.get(path)
    assert len(page.content) < 1100000
    data = page.json()
    assert 1 <= len(data["messages"]) < 30 and data["next_cursor"]
    assert len(data["messages"][0]["results"][0]["body"]) == 60000
    next_page = client.get(path, params={"before": data["next_cursor"]}).json()
    assert not (
        {row["id"] for row in data["messages"]} & {row["id"] for row in next_page["messages"]}
    )


def test_status_requires_new_history_protocol_and_registry_skills_only(sara_ready, monkeypatch):
    client, _, _ = sara_ready
    assert client.get("/crm/sara/status").json()["available"] is True
    monkeypatch.setattr(bridge, "health", lambda: {"available": True, "model": "old"})
    assert client.get("/crm/sara/status").json()["available"] is False
    assert client.get("/crm/hermes/status").json()["available"] is True
    skill = client.post(
        "/crm/control/items",
        json={
            "kind": "skill",
            "name": "Skill aprobada",
            "definition": {"content": "# Contexto del proyecto"},
            "enabled": True,
        },
    ).json()
    rows = client.get("/crm/sara/skills").json()["skills"]
    assert (
        len(rows) == 1
        and rows[0]["id"] == skill["id"]
        and rows[0]["content"] == "# Contexto del proyecto"
    )
    assert rows[0]["effective"] is True
    assert (
        client.post(
            "/crm/sara/conversations",
            content=b" " * 16385,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_late_first_request_never_consumes_a_newer_active_turn(sara_ready, monkeypatch):
    client, _, _ = sara_ready
    path = f"/crm/sara/conversations/{conversation(client)['id']}/messages"
    first_finished, first_release, second_started, second_release = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    count = []

    def request(endpoint, body, timeout):
        with TestClient(app) as runtime:
            headers = {"Authorization": "Bearer " + body["token"]}
            assert (
                runtime.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
            )
            count.append(True)
            turn = len(count)
            if turn == 1:
                result = runtime.post(
                    "/internal/hermes/finish", json={"reply": "Primera respuesta"}, headers=headers
                )
                first_finished.set()
                assert first_release.wait(5)
            else:
                second_started.set()
                assert second_release.wait(5)
                result = runtime.post(
                    "/internal/hermes/finish", json={"reply": "Segunda respuesta"}, headers=headers
                )
            assert result.status_code == 200
            return result.json()

    monkeypatch.setattr(bridge, "request", request)
    second_body = payload("Segundo turno")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lambda: client.post(path, json=payload("Primer turno")))
        second = None
        try:
            assert first_finished.wait(5)
            assert len(client.get(path).json()["messages"]) == 2
            second = pool.submit(lambda: client.post(path, json=second_body))
            assert second_started.wait(5)
            first_release.set()
            assert first.result(timeout=5).json()["state"] == "completed"
            assert client.post(path, json=second_body).json()["state"] == "pending"
        finally:
            first_release.set()
            second_release.set()
        assert second.result(timeout=5).json()["state"] == "completed"
    assert len(count) == 2


def test_broker_history_rejects_tool_replay_and_oversized_context():
    from app.hermes import broker

    for history in (
        [{"role": "tool", "content": "old tool result"}],
        [{"role": "user", "content": "text", "tool_calls": []}],
        [{"role": "user", "content": "x" * 4097}],
        [{"role": "user", "content": "x" * 4096}] * 4,
        [{"role": "assistant", "content": "a"}] * 9,
    ):
        with pytest.raises(HTTPException):
            broker.validated_history(history)
    assert broker.validated_history(None) == []
