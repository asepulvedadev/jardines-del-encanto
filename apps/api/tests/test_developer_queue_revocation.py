"""Channel provenance is retained until delayed paid claims execute."""

# ruff: noqa: F811
from uuid import uuid4

import pytest
from test_crm import authenticated  # noqa: F401
from test_sara_images import png
from test_whatsapp_agent import configured  # noqa: F401
from test_whatsapp_developer import call, issue


@pytest.mark.parametrize("kind", ["image", "simulation"])
def test_revoke_developer_before_queued_paid_work(configured, monkeypatch, kind):
    from app.images import worker as images
    from app.sara import simulations

    client, _owner, _job, _row, _run, headers = issue(configured, monkeypatch)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    if kind == "image":
        action, args = "images.generate", {"request_id": str(uuid4()), "prompt": "A brand concept"}
    else:
        action, args = "sara.simulate", {"request_id": str(uuid4()), "customer_turns": ["Hola"]}
    queued = call(client, headers, action, args).json()["result"]
    assert queued.get("status") == "queued", queued
    state = client.get("/crm/social/whatsapp-agent").json()
    data = {
        k: state[k]
        for k in [
            "version",
            "shared_profile_version",
            "account_id",
            "phone",
            "instructions",
            "knowledge",
        ]
    }
    data.update(developers=[], enabled=True, consent_confirmed=True)
    revoked = client.patch("/crm/social/whatsapp-agent", json=data)
    assert revoked.status_code == 200, revoked.text
    calls = []
    if kind == "image":

        def generate(*a):
            calls.append("paid image")
            return png()

        monkeypatch.setattr(images.bridge, "generate", generate)
        images.tick()
        after = client.get("/crm/images/" + queued["id"]).json()
    else:

        def model(*a, **k):
            calls.append("paid simulation")
            return {"ok": True, "tools": 0, "response": "Hola.", "model": "gpt-6-luna"}

        monkeypatch.setattr(simulations.bridge, "request", model)
        simulations.tick()
        after = client.get("/crm/sara/simulations/" + queued["id"]).json()
    print(kind, "after_revocation=", after["status"], "paid_calls=", len(calls))
    assert not calls, "Revoked WhatsApp developer grant must not authorize queued paid work"


@pytest.mark.parametrize("kind", ["image", "simulation"])
def test_completed_developer_chat_keeps_authorized_queued_work_usable(
    configured, monkeypatch, kind
):
    import psycopg

    from app.images import worker as images
    from app.sara import simulations

    client, owner, job, _row, _run, headers = issue(configured, monkeypatch)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    action, args = (
        ("images.generate", {"request_id": str(uuid4()), "prompt": "Brand concept"})
        if kind == "image"
        else ("sara.simulate", {"request_id": str(uuid4()), "customer_turns": ["Hola"]})
    )
    queued = call(client, headers, action, args).json()["result"]
    assert (
        client.post(
            "/internal/hermes/finish", json={"reply": "Trabajo en cola."}, headers=headers
        ).status_code
        == 200
    )
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.whatsapp_agent_jobs SET state='completed',reply='Trabajo en cola.' WHERE id=%s",
            (job["id"],),
        )
    calls = []
    if kind == "image":

        def generate(*a):
            calls.append(1)
            return png()

        monkeypatch.setattr(images.bridge, "generate", generate)
        images.tick()
        status = client.get("/crm/images/" + queued["id"]).json()
    else:

        def generate(*a, **k):
            calls.append(1)
            return {"ok": True, "tools": 0, "response": "Hola.", "model": "gpt-6-luna"}

        monkeypatch.setattr(simulations.bridge, "request", generate)
        simulations.tick()
        status = client.get("/crm/sara/simulations/" + queued["id"]).json()
    assert status["status"] == "completed", status
    assert calls == [1]
