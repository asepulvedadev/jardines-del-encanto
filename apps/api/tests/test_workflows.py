"""Guarded workflow integration; fake adapters and isolated test database only."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_crm import ORIGIN, authenticated, customer  # noqa: F401

from app.main import app
from app.workflows import service, worker


def node(key, kind, settings=None, next_id=None, **edges):
    return {
        "id": key,
        "kind": kind,
        "label": key,
        "position": {"x": 0, "y": 0},
        "settings": settings or {},
        "next_id": next_id,
        **edges,
    }


def document(nodes=None, daily_limit=20):
    return {
        "entry_id": "one",
        "nodes": nodes
        or [node("one", "crm_note", {"body": "Hola {{nombre}}"}, "two"), node("two", "end")],
        "schedule": {
            "timezone": "America/Bogota",
            "days": [1, 2, 3, 4, 5, 6, 7],
            "start_time": "00:00",
            "end_time": "23:59",
            "daily_limit": daily_limit,
        },
        "stop_on_reply": True,
    }


@pytest.fixture
def workflows(authenticated, monkeypatch):
    client, owner, password = authenticated
    monkeypatch.setattr(worker, "available", lambda: True)
    # All tests run in a deterministic allowed Colombian schedule instant.
    monkeypatch.setattr(service, "now", lambda: datetime(2026, 11, 16, 15, tzinfo=UTC))
    return client, owner, password


def prepare_run(client, doc=None, phone="3001234567"):
    person = customer(client, phone)
    definition = client.post(
        "/crm/workflows/definitions", json={"name": "Seguimiento", "document": doc or document()}
    )
    assert definition.status_code == 201, definition.text
    definition = definition.json()
    review = client.post(
        f"/crm/workflows/definitions/{definition['id']}/prepare",
        json={"version": 1, "contact_ids": [person["id"]], "consent_confirmed": True},
    )
    assert review.status_code == 200, review.text
    return person, definition, review.json()


def activate(client, review):
    response = client.post(
        f"/crm/workflows/runs/{review['run']['id']}/activate",
        json={"fingerprint": review["fingerprint"], "consent_confirmed": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_workflows_anonymous_and_limits():
    with TestClient(app) as client:
        assert client.get("/crm/workflows/definitions").status_code == 401
        assert client.post("/crm/workflows/definitions", content=b"x" * 65537).status_code == 413
        assert (
            client.post(
                "/crm/workflows/runs/00000000-0000-0000-0000-000000000000/activate",
                content=b"x" * 16385,
            ).status_code
            == 413
        )


def test_review_consent_stale_versions_and_no_side_effects(workflows):
    client, owner, _ = workflows
    _person, definition, review = prepare_run(client)
    path = f"/crm/workflows/runs/{review['run']['id']}/activate"
    assert (
        client.post(path, json={"fingerprint": "a" * 64, "consent_confirmed": True}).status_code
        == 409
    )
    assert (
        client.post(
            path, json={"fingerprint": review["fingerprint"], "consent_confirmed": False}
        ).status_code
        == 422
    )
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.workflow_steps").fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM crm.activities WHERE kind='note'").fetchone()[0] == 0
        )
        assert db.execute("SELECT count(*) FROM crm.workflow_grants").fetchone()[0] == 0
    updated = client.patch(
        f"/crm/workflows/definitions/{definition['id']}",
        json={"version": 1, "name": "Nueva versión"},
    )
    assert updated.status_code == 200
    assert (
        client.patch(
            f"/crm/workflows/definitions/{definition['id']}", json={"version": 1, "name": "Vieja"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            path, json={"fingerprint": review["fingerprint"], "consent_confirmed": True}
        ).status_code
        == 409
    )


def test_snapshot_expiry_and_contact_changes(workflows):
    client, owner, _ = workflows
    _person, _, review = prepare_run(client)
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.workflow_runs SET review_expires_at='2020-01-01' WHERE id=%s",
            (review["run"]["id"],),
        )
    assert (
        client.post(
            f"/crm/workflows/runs/{review['run']['id']}/activate",
            json={"fingerprint": review["fingerprint"], "consent_confirmed": True},
        ).status_code
        == 410
    )
    person2, _, review2 = prepare_run(client, phone="3001234568")
    client.patch(
        f"/crm/contacts/{person2['id']}",
        json={"name": "Cambio", "phone": person2["phone"], "source": "web", "version": 1},
    )
    assert (
        client.post(
            f"/crm/workflows/runs/{review2['run']['id']}/activate",
            json={"fingerprint": review2["fingerprint"], "consent_confirmed": True},
        ).status_code
        == 409
    )


def test_ordered_atomic_crm_steps_and_independent_grant(workflows):
    client, owner, _ = workflows
    person, _, review = prepare_run(
        client,
        document(
            [
                node("one", "crm_note", {"body": "Primera {{nombre}}"}, "two"),
                node("two", "crm_task", {"title": "Segunda", "due_days": 1}, "three"),
                node("three", "end"),
            ]
        ),
    )
    run = activate(client, review)
    assert (
        client.post(
            f"/crm/workflows/runs/{run['id']}/activate",
            json={"fingerprint": review["fingerprint"], "consent_confirmed": True},
        ).status_code
        == 409
    )
    with psycopg.connect(owner) as db:
        db.execute("DELETE FROM crm.sessions")
    # No fabricated browser token: approved grant survives logout/session expiry.
    for _ in range(5):
        worker.tick()
    with psycopg.connect(owner) as db:
        assert (
            db.execute("SELECT status FROM crm.workflow_runs WHERE id=%s", (run["id"],)).fetchone()[
                0
            ]
            == "completed"
        )
        assert (
            db.execute(
                "SELECT count(*) FROM crm.workflow_steps WHERE run_id=%s", (run["id"],)
            ).fetchone()[0]
            == 3
        )
        assert (
            db.execute(
                "SELECT count(*) FROM crm.tasks WHERE contact_id=%s", (person["id"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute("SELECT count(*) FROM crm.activities WHERE kind='note'").fetchone()[0] == 1
        )


def test_pause_stop_and_disabled_administrator(workflows):
    client, owner, _ = workflows
    _, _, review = prepare_run(client)
    run = activate(client, review)
    paused = client.post(
        f"/crm/workflows/runs/{run['id']}/pause", json={"version": run["version"]}
    ).json()
    worker.tick()
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.workflow_steps").fetchone()[0] == 0
    resumed = client.post(
        f"/crm/workflows/runs/{run['id']}/resume", json={"version": paused["version"]}
    )
    assert resumed.status_code == 200, resumed.text
    stopped = client.post(
        f"/crm/workflows/runs/{run['id']}/stop", json={"version": resumed.json()["version"]}
    )
    assert stopped.status_code == 200
    worker.tick()
    assert client.get(f"/crm/workflows/runs/{run['id']}").json()["run"]["status"] == "stopped"
    _, _, review2 = prepare_run(client, phone="3001234568")
    run2 = activate(client, review2)
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.users SET enabled=false")
    worker.tick()
    with psycopg.connect(owner) as db:
        assert (
            db.execute(
                "SELECT status FROM crm.workflow_runs WHERE id=%s", (run2["id"],)
            ).fetchone()[0]
            == "paused"
        )


@pytest.fixture
def fake_social(workflows, monkeypatch):
    from app.social import workflow

    client, owner, _password = workflows
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.control_connections SET enabled=true WHERE key IN ('zernio','whatsapp')"
        )
    calls = []
    changed = {"value": False, "unknown": False}

    def prepare(db, n, c, binding=None, cache=None):
        return {
            "kind": n["kind"],
            "account_id": "acct",
            "platform": "whatsapp",
            "profile_id": "profile",
            "conversation_id": "conv",
            "participant_id": "participant",
            "contact_id": c["id"],
            "summary": {"description": "Mensaje aprobado"},
        }

    def check(plan):
        if changed["value"]:
            raise HTTPException(409, "provider_identity_changed")

    def dispatch(plan, request_id):
        calls.append(request_id)
        if changed["unknown"]:
            raise RuntimeError("secret must not persist")
        return {"state": "completed", "receipt": {"submission": "accepted"}}

    monkeypatch.setattr(workflow, "prepare", prepare)
    monkeypatch.setattr(workflow, "check", check)
    monkeypatch.setattr(workflow, "dispatch", dispatch)
    return client, owner, calls, changed


def social_doc(daily_limit=20):
    return document(
        [
            node(
                "one",
                "whatsapp_template",
                {
                    "account_id": "acct",
                    "template_name": "approved",
                    "language": "es",
                    "parameters": [],
                },
                "two",
            ),
            node("two", "end"),
        ],
        daily_limit,
    )


def test_unknown_send_and_crashed_reservation_never_replay(fake_social):
    client, owner, calls, changed = fake_social
    _, _, review = prepare_run(client, social_doc())
    run = activate(client, review)
    changed["unknown"] = True
    worker.tick()
    worker.tick()
    assert len(calls) == 1
    assert client.get(f"/crm/workflows/runs/{run['id']}").json()["run"]["status"] == "unknown"
    _, _, review2 = prepare_run(client, social_doc(), phone="3001234568")
    run2 = activate(client, review2)
    from app.crm.database import connect

    with connect() as db:
        item = worker.claim(db)
    assert item
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.workflow_steps SET reserved_at=now()-interval '10 minutes' WHERE id=%s",
            (item["id"],),
        )
    worker.tick()
    assert len(calls) == 1
    assert client.get(f"/crm/workflows/runs/{run2['id']}").json()["run"]["status"] == "unknown"


def test_provider_change_and_verified_reply_hold(fake_social):
    client, _owner, calls, changed = fake_social
    _person, _, review = prepare_run(client, social_doc())
    run = activate(client, review)
    changed["value"] = True
    worker.tick()
    assert not calls
    assert client.get(f"/crm/workflows/runs/{run['id']}").json()["run"]["status"] == "paused"
    changed["value"] = False
    _, _, review2 = prepare_run(client, social_doc(), phone="3001234568")
    run2 = activate(client, review2)
    from app.crm.database import connect

    with connect() as db:
        worker.verified_reply(
            db,
            {
                "account_id": "wrong",
                "conversation_id": "conv",
                "participant_id": "participant",
                "profile_id": "profile",
                "platform": "whatsapp",
                "sent_at": "2026-11-16T15:01:00Z",
            },
        )
    assert (
        client.get(f"/crm/workflows/runs/{run2['id']}").json()["recipients"][0]["status"]
        == "active"
    )
    with connect() as db:
        worker.verified_reply(
            db,
            {
                "account_id": "acct",
                "conversation_id": "conv",
                "participant_id": "participant",
                "profile_id": "profile",
                "platform": "whatsapp",
                "sent_at": service.now().isoformat(),
            },
        )
    assert (
        client.get(f"/crm/workflows/runs/{run2['id']}").json()["recipients"][0]["status"]
        == "stopped"
    )


def test_concurrent_claims_once_and_terminal_stop(fake_social):
    client, _owner, calls, _ = fake_social
    _, _, review = prepare_run(client, social_doc())
    run = activate(client, review)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker.tick(), range(2)))
    assert len(calls) == 1
    worker.tick()  # Finish the first run's end node before the independent late-receipt case.
    assert client.get(f"/crm/workflows/runs/{run['id']}").json()["run"]["status"] == "completed"
    # A late receipt must not restore a manually stopped run.
    _, _, review2 = prepare_run(client, social_doc(), phone="3001234568")
    run2 = activate(client, review2)
    from app.crm.database import connect

    with connect() as db:
        item = worker.claim(db)
    assert item
    stopped = client.post(
        f"/crm/workflows/runs/{run2['id']}/stop", json={"version": run2["version"]}
    )
    assert stopped.status_code == 200
    with connect() as db:
        worker.finalize(db, item, {"state": "completed", "receipt": {}})
    assert client.get(f"/crm/workflows/runs/{run2['id']}").json()["run"]["status"] == "stopped"


def test_csrf_worker_default_off_and_typed_broker(workflows, monkeypatch):
    client, _owner, _ = workflows
    _person, _definition, review = prepare_run(client)
    headers = dict(client.headers)
    del client.headers["x-csrf-token"]
    assert (
        client.post(
            "/crm/workflows/definitions", json={"name": "No", "document": document()}
        ).status_code
        == 403
    )
    client.headers.update(headers)
    monkeypatch.setattr(worker, "available", lambda: False)
    assert (
        client.post(
            f"/crm/workflows/runs/{review['run']['id']}/activate",
            json={"fingerprint": review["fingerprint"], "consent_confirmed": True},
        ).status_code
        == 503
    )
    from app.control import service as control

    assert "workflows.activate" not in control.ACTION_MODELS
    assert "workflows.prepare" not in control.ACTION_MODELS
    assert "workflows.draft.create" in control.ACTION_MODELS


def test_provider_validation_crossing_schedule_never_reserves(fake_social, monkeypatch):
    client, owner, calls, _ = fake_social
    doc = social_doc()
    doc["schedule"].update(days=[1], start_time="09:00", end_time="17:00")
    _, _, review = prepare_run(client, doc)
    run = activate(client, review)
    clock = {"now": datetime(2026, 11, 16, 21, 59, 59, tzinfo=UTC)}
    monkeypatch.setattr(service, "now", lambda: clock["now"])
    original = service.check_plan

    def slow_check(*args, **kwargs):
        value = original(*args, **kwargs)
        clock["now"] = datetime(2026, 11, 16, 22, 0, 1, tzinfo=UTC)
        return value

    monkeypatch.setattr(service, "check_plan", slow_check)
    assert worker.tick() is False
    assert calls == []
    with psycopg.connect(owner) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM crm.workflow_steps WHERE run_id=%s", (run["id"],)
            ).fetchone()[0]
            == 0
        )
        assert db.execute(
            "SELECT due_at FROM crm.workflow_recipients WHERE run_id=%s", (run["id"],)
        ).fetchone()[0] == datetime(2026, 11, 23, 14, tzinfo=UTC)


def test_predispatch_crossing_schedule_is_held_without_replay(fake_social, monkeypatch):
    client, owner, calls, _ = fake_social
    doc = social_doc()
    doc["schedule"].update(days=[1], start_time="09:00", end_time="17:00")
    _, _, review = prepare_run(client, doc)
    run = activate(client, review)
    clock = {"now": datetime(2026, 11, 16, 21, 59, 59, tzinfo=UTC), "checks": 0}
    monkeypatch.setattr(service, "now", lambda: clock["now"])
    original = service.check_snapshot

    def slow_check(*args, **kwargs):
        value = original(*args, **kwargs)
        clock["checks"] += 1
        if clock["checks"] == 2:
            clock["now"] = datetime(2026, 11, 16, 22, 0, 1, tzinfo=UTC)
        return value

    monkeypatch.setattr(service, "check_snapshot", slow_check)
    assert worker.tick() is False
    assert calls == []
    with psycopg.connect(owner) as db:
        assert db.execute(
            "SELECT state FROM crm.workflow_steps WHERE run_id=%s", (run["id"],)
        ).fetchall() == [("failed",)]
    assert client.get(f"/crm/workflows/runs/{run['id']}").json()["run"]["status"] == "blocked"
    worker.tick()
    assert calls == []


def test_multichannel_review_freezes_each_explicit_account_binding(fake_social, monkeypatch):
    from app.social import workflow

    client, owner, calls, _ = fake_social
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.control_connections SET enabled=true WHERE key IN ('facebook','instagram')"
        )
    received = []

    def prepare_channel(db, n, c, binding=None, cache=None):
        assert binding is not None
        assert binding["account_id"] == n["settings"]["account_id"]
        received.append((n["id"], binding["conversation_id"]))
        return {"summary": {"description": binding["conversation_id"]}}

    monkeypatch.setattr(workflow, "prepare", prepare_channel)
    person = customer(client, "3001234567")
    doc = document(
        [
            node(
                "one",
                "social_message",
                {
                    "account_id": "fb",
                    "platform": "facebook",
                    "text": "Hola",
                    "allow_provider_takeover": True,
                },
                "ig",
            ),
            node(
                "ig",
                "social_message",
                {
                    "account_id": "ig",
                    "platform": "instagram",
                    "text": "Hola",
                    "allow_provider_takeover": True,
                },
                "end",
            ),
            node("end", "end"),
        ]
    )
    saved = client.post("/crm/workflows/definitions", json={"name": "Multicanal", "document": doc})
    assert saved.status_code == 201
    payload = {
        "version": 1,
        "contact_ids": [person["id"]],
        "consent_confirmed": True,
        "channel_bindings": [
            {"contact_id": person["id"], "account_id": "fb", "conversation_id": "thread-fb"},
            {"contact_id": person["id"], "account_id": "ig", "conversation_id": "thread-ig"},
        ],
    }
    review = client.post(f"/crm/workflows/definitions/{saved.json()['id']}/prepare", json=payload)
    assert review.status_code == 200, review.text
    assert received == [("one", "thread-fb"), ("ig", "thread-ig")]
    assert "thread-fb" in review.json()["steps"][0]["description"]
    assert "thread-ig" in review.json()["steps"][1]["description"]
    assert calls == []
    with psycopg.connect(owner) as db:
        frozen = db.execute(
            "SELECT snapshot,status FROM crm.workflow_runs WHERE id=%s",
            (review.json()["run"]["id"],),
        ).fetchone()
    assert frozen[1] == "prepared"
    assert frozen[0]["channel_bindings"][person["id"]]["ig"]["conversation_id"] == "thread-ig"
    payload["channel_bindings"].append(payload["channel_bindings"][0])
    assert (
        client.post(
            f"/crm/workflows/definitions/{saved.json()['id']}/prepare", json=payload
        ).status_code
        == 422
    )
