"""Owner-scoped deletion, retained audit and revocation through the public Sara API."""

# ruff: noqa: F811
import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
from fastapi.testclient import TestClient
from test_crm import ORIGIN, authenticated  # noqa: F401
from test_sara import conversation, fake_runtime, payload, sara_ready  # noqa: F401

from app.main import app


def erase(client, chat_id, **kwargs):
    return client.request("DELETE", f"/crm/sara/conversations/{chat_id}", json={}, **kwargs)


def document(client, name):
    response = client.post(
        "/crm/sara/attachments",
        json={
            "filename": name,
            "mime_type": "text/plain",
            "data_base64": base64.b64encode(b"Private fixture").decode(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_deletion_requires_live_owner_origin_csrf_and_empty_json(authenticated):
    client, owner, password = authenticated
    chat = conversation(client)
    with TestClient(app, base_url=ORIGIN) as anonymous:
        assert erase(anonymous, chat["id"]).status_code == 401
    for headers in ({"Origin": "https://evil.invalid"}, {"X-CSRF-Token": "bad"}):
        assert erase(client, chat["id"], headers=headers).status_code == 403
    assert (
        client.request(
            "DELETE", f"/crm/sara/conversations/{chat['id']}", json={"owner_id": chat["id"]}
        ).status_code
        == 422
    )
    with psycopg.connect(owner) as db:
        db.execute(
            "INSERT INTO crm.users(username,password_hash) SELECT 'otheradmin',password_hash "
            "FROM crm.users WHERE username='testadmin'"
        )
    with TestClient(app, base_url=ORIGIN) as other:
        login = other.post(
            "/crm/auth/login",
            json={"username": "otheradmin", "password": password},
            headers={"Origin": ORIGIN},
        ).json()
        other.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login["csrf_token"]})
        assert erase(other, chat["id"]).status_code == 404
    assert erase(client, chat["id"]).json() == {"id": chat["id"], "deleted": True}
    assert erase(client, chat["id"]).status_code == 404
    assert client.get("/crm/sara/conversations").json()["conversations"] == []
    assert client.get(f"/crm/sara/conversations/{chat['id']}/messages").status_code == 404
    assert (
        client.post(f"/crm/sara/conversations/{chat['id']}/messages", json=payload()).status_code
        == 404
    )


def test_delete_erases_messages_and_unshared_files_revokes_proposals_retains_audit(
    sara_ready, monkeypatch
):
    client, owner, _ = sara_ready
    chat, other = conversation(client), conversation(client, "Keep")
    private, shared, draft = (
        document(client, name) for name in ("only.txt", "shared.txt", "draft.txt")
    )
    calls = []
    fake_runtime(
        monkeypatch,
        calls,
        action=(
            "crm.contact.create",
            {
                "name": "Must not be created",
                "phone": "3001234567",
                "source": "web",
            },
        ),
    )
    first = client.post(
        f"/crm/sara/conversations/{chat['id']}/messages",
        json=payload(attachments=[private, shared]),
    )
    assert first.status_code == 200, first.text
    proposal = first.json()["assistant_message"]["proposals"][0]
    second = client.post(
        f"/crm/sara/conversations/{other['id']}/messages", json=payload(attachments=[shared])
    )
    assert second.status_code == 200
    with psycopg.connect(owner) as db:
        before_runs = db.execute("SELECT count(*) FROM crm.hermes_runs").fetchone()[0]
        before_calls = db.execute("SELECT count(*) FROM crm.hermes_calls").fetchone()[0]
        old_audit = db.execute("SELECT count(*) FROM crm.control_audit").fetchone()[0]
    assert erase(client, chat["id"]).status_code == 200
    assert client.get(f"/crm/sara/attachments/{private}/content").status_code == 404
    for file_id in (shared, draft):
        assert client.get(f"/crm/sara/attachments/{file_id}/content").status_code == 200
    assert (
        len(client.get(f"/crm/sara/conversations/{other['id']}/messages").json()["messages"]) == 2
    )
    approval = client.post(
        f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": proposal["version"]}
    )
    assert approval.status_code == 409
    with psycopg.connect(owner) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM crm.sara_messages WHERE conversation_id=%s", (chat["id"],)
            ).fetchone()[0]
            == 0
        )
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM crm.hermes_runs").fetchone()[0] == before_runs
        assert db.execute("SELECT count(*) FROM crm.hermes_calls").fetchone()[0] == before_calls
        assert db.execute("SELECT count(*) FROM crm.control_audit").fetchone()[0] == old_audit + 1
        assert (
            db.execute(
                "SELECT status FROM crm.hermes_proposals WHERE id=%s", (proposal["id"],)
            ).fetchone()[0]
            == "expired"
        )
    assert erase(client, other["id"]).status_code == 200
    assert client.get(f"/crm/sara/attachments/{shared}/content").status_code == 404


def test_active_turn_cannot_be_deleted_and_old_bearer_cannot_finish_after_delete(
    sara_ready, monkeypatch
):
    client, _, _ = sara_ready
    chat = conversation(client)
    entered, release = Event(), Event()
    calls, tokens = [], []

    def wait():
        entered.set()
        assert release.wait(5)

    fake_runtime(monkeypatch, calls, wait=wait)
    from app.hermes import bridge

    original = bridge.request

    def capture(path, body, timeout):
        tokens.append(body["token"])
        return original(path, body, timeout)

    monkeypatch.setattr(bridge, "request", capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        turn = pool.submit(
            lambda: client.post(f"/crm/sara/conversations/{chat['id']}/messages", json=payload())
        )
        try:
            assert entered.wait(5)
            blocked = erase(client, chat["id"])
            assert (
                blocked.status_code == 409 and blocked.json()["detail"] == "sara_conversation_busy"
            )
        finally:
            release.set()
        assert turn.result(timeout=5).json()["state"] == "completed"
    assert erase(client, chat["id"]).status_code == 200
    with TestClient(app) as runtime:
        response = runtime.post(
            "/internal/hermes/finish",
            json={"reply": "Late"},
            headers={"Authorization": "Bearer " + tokens[0]},
        )
        assert response.status_code == 401


def test_delete_preserves_already_approved_business_changes(sara_ready, monkeypatch):
    client, owner, _ = sara_ready
    chat = conversation(client)
    fake_runtime(
        monkeypatch,
        [],
        action=(
            "crm.contact.create",
            {
                "name": "Retained client",
                "phone": "3001234567",
                "source": "web",
            },
        ),
    )
    turn = client.post(f"/crm/sara/conversations/{chat['id']}/messages", json=payload()).json()
    proposal = turn["assistant_message"]["proposals"][0]
    assert (
        client.post(
            f"/crm/hermes/proposals/{proposal['id']}/approve", json={"version": proposal["version"]}
        ).status_code
        == 200
    )
    assert erase(client, chat["id"]).status_code == 200
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT status FROM crm.hermes_proposals WHERE id=%s", (proposal["id"],)
            ).fetchone()[0]
            == "approved"
        )


from threading import Lock

import pytest

from app.sara import service


@pytest.mark.parametrize("first_operation", ["send", "delete"])
def test_file_reuse_and_deletion_serialize_without_blob_update_privilege(
    sara_ready, monkeypatch, first_operation
):
    client, owner, _ = sara_ready
    chat, other = conversation(client), conversation(client, "Reusing file")
    file_id = document(client, "race.txt")
    fake_runtime(monkeypatch, [])
    assert (
        client.post(
            f"/crm/sara/conversations/{chat['id']}/messages", json=payload(attachments=[file_id])
        ).status_code
        == 200
    )
    original = service.lock_files
    entered, attempted, release = Event(), Event(), Event()
    count, count_lock = [], Lock()

    def held_lock(db, ids):
        with count_lock:
            index = len(count)
            count.append(True)
        if index == 0:
            original(db, ids)
            entered.set()
            assert release.wait(5)
        else:
            attempted.set()
            original(db, ids)

    monkeypatch.setattr(service, "lock_files", held_lock)
    actions = {
        "send": lambda: client.post(
            f"/crm/sara/conversations/{other['id']}/messages", json=payload(attachments=[file_id])
        ),
        "delete": lambda: erase(client, chat["id"]),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(actions[first_operation])
        try:
            assert entered.wait(5)
            second = pool.submit(actions["delete" if first_operation == "send" else "send"])
            assert attempted.wait(5)
        finally:
            release.set()
        first_response, second_response = first.result(timeout=5), second.result(timeout=5)
    if first_operation == "send":
        assert first_response.status_code == second_response.status_code == 200
        assert client.get(f"/crm/sara/attachments/{file_id}/content").status_code == 200
    else:
        assert first_response.status_code == 200 and second_response.status_code == 404
        assert client.get(f"/crm/sara/attachments/{file_id}/content").status_code == 404
    with psycopg.connect(owner) as db:
        assert not db.execute(
            "SELECT has_table_privilege('jardines_crm_app','crm.sara_attachments','UPDATE')"
        ).fetchone()[0]
        assert db.execute("SELECT count(*) FROM crm.hermes_runs").fetchone()[0] == (
            2 if first_operation == "send" else 1
        )
