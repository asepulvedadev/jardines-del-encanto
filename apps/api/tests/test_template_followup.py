"""Synthetic campaign replies only. Providers are replaced by existing test fixtures."""
# ruff: noqa: F811

import copy

import psycopg
import pytest
from test_crm import authenticated  # noqa: F401
from test_social_onboarding import intake, state  # noqa: F401
from test_whatsapp_agent import configured, payload, send  # noqa: F401
from test_whatsapp_audio import audio_setup  # noqa: F401

from app.crm.database import connect
from app.social import onboarding, whatsapp_agent


def followup(event, text, events, configured, suffix="followup"):
    event = copy.deepcopy(event)
    event["id"] = suffix
    event["message"].update(platformMessageId=suffix, text=text)
    events[event["conversation"]["id"]] = event
    client, _, credentials = configured
    assert send(client, credentials, event).status_code == 200
    return event


@pytest.mark.parametrize(
    "text",
    [
        "No recibir información",
        "No",
        "No gracias",
        "No me interesa",
        "Salir",
        "No deseo información",
    ],
)
def test_campaign_declines_are_terminal(text):
    assert onboarding.opted_out(text)


@pytest.mark.parametrize(
    "text",
    [
        "No tengo inconveniente",
        "¿No tienen financiación?",
        "No entiendo el precio",
        "Sí, me interesa",
    ],
)
def test_negative_questions_are_not_unsubscriptions(text):
    assert not onboarding.opted_out(text)


def test_interested_reply_waits_for_identity_before_links(intake, configured):
    incoming, deliveries, _synthesis, events, owner = intake
    event = incoming(text="Conocer opciones")
    for _ in range(5):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "question"]
    assert state(owner)[0]["contact_id"] is None
    event = copy.deepcopy(event)
    event["id"] = "identity-followup"
    event["message"].update(
        platformMessageId="identity-followup",
        text="Nombre completo: Mariana Torres Celular: 3001110099",
    )
    events[event["conversation"]["id"]] = event
    client, _, credentials = configured
    assert send(client, credentials, event).status_code == 200
    assert send(client, credentials, event).status_code == 200
    for _ in range(5):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "question", "website", "group"]
    assert state(owner)[0]["contact_id"] is not None
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM crm.deals").fetchone()[0] == 1


def test_no_fallback_reply_when_welcome_disabled(configured, monkeypatch):
    client, owner, credentials = configured
    from app.social import onboarding_transport

    monkeypatch.setattr(onboarding_transport, "execute", lambda *a: pytest.fail("No welcome send"))
    event = payload("573001110099")
    event["message"]["text"] = "No recibir información"
    assert send(client, credentials, event).status_code == 200
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.whatsapp_agent_jobs").fetchone()[0] == 0
    event["id"] = "later-inbound"
    event["message"].update(platformMessageId="later-inbound", text="Hola")
    assert send(client, credentials, event).status_code == 200
    assert whatsapp_agent.claim() is None


def test_pending_public_reply_is_blocked_after_decline(configured):
    client, _owner, credentials = configured
    event = payload("573001110099")
    event["message"]["text"] = "Hola"
    assert send(client, credentials, event).status_code == 200
    event["id"] = "stop-pending"
    event["message"].update(platformMessageId="stop-pending", text="Salir")
    assert send(client, credentials, event).status_code == 200
    assert whatsapp_agent.claim() is None
    with connect() as db:
        assert (
            db.execute(
                "SELECT state FROM crm.whatsapp_agent_jobs ORDER BY created_at LIMIT 1"
            ).fetchone()["state"]
            == "blocked"
        )


def test_decline_between_audio_and_identity_stops_every_remaining_phase(intake, configured):
    incoming, deliveries, synthesis, events, _ = intake
    event = incoming(text="Sí, quiero conocer opciones")
    onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio"]
    followup(event, "No recibir información", events, configured, "decline-after-audio")
    for _ in range(5):
        onboarding.tick()
        whatsapp_agent.tick()
    assert [d[0] for d in deliveries] == ["audio"]
    assert len(synthesis) == 1


def test_identity_can_arrive_in_separate_messages(intake, configured):
    incoming, deliveries, _, events, owner = intake
    event = incoming(text="Conocer opciones")
    onboarding.tick()
    onboarding.tick()
    event = followup(event, "Nombre completo: Mariana Torres", events, configured, "name-only")
    onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "question"]
    followup(event, "Celular: 3001110099", events, configured, "phone-only")
    for _ in range(4):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "question", "website", "group"]
    assert state(owner)[0]["identity_confirmed"]


def test_decline_during_model_prevents_public_send(configured, monkeypatch):
    from test_whatsapp_agent import mock_dispatch

    client, owner, credentials = configured
    sent = mock_dispatch(monkeypatch)
    event = payload("573001110099")
    event["message"]["text"] = "¿Cuánto cuesta?"
    assert send(client, credentials, event).status_code == 200

    def model(*args, **kwargs):
        stop = copy.deepcopy(event)
        stop["id"] = "stop-during-model"
        stop["message"].update(platformMessageId="stop-during-model", text="No gracias")
        assert send(client, credentials, stop).status_code == 200
        return {"ok": True, "tools": 0, "response": "No debe salir"}

    monkeypatch.setattr(whatsapp_agent.bridge, "request", model)
    whatsapp_agent.tick()
    assert not sent
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT state FROM crm.whatsapp_agent_jobs").fetchone()[0] == "blocked"


def test_final_sequence_guard_rejects_suppressed_recipient(configured, monkeypatch):
    from contextlib import nullcontext

    from app.social import workflow

    client, _, credentials = configured
    event = payload("573001110099")
    event["message"]["text"] = "SALIR"
    assert send(client, credentials, event).status_code == 200
    monkeypatch.setattr(workflow.config, "locked", nullcontext)
    monkeypatch.setattr(
        workflow, "_request", lambda *a, **k: pytest.fail("No vendor request allowed")
    )
    plan = onboarding.normalize(event, credentials["profile_id"])
    with pytest.raises(Exception, match="recipient_opted_out"):
        workflow.dispatch(plan, "synthetic-guard-check")


@pytest.mark.parametrize("shared", [False, True])
def test_remote_unsubscribe_is_scoped_and_never_sends_messages(monkeypatch, shared):
    from app.social import consent_transport, onboarding_transport

    identifier = "c" * 24
    row = {
        "profile_id": "a" * 24,
        "account_id": "b" * 24,
        "platform": "whatsapp",
        "participant_id": "573001110099",
        "conversation_id": "thread",
    }
    monkeypatch.setattr(
        onboarding_transport.service, "account", lambda *a: {"platform": "whatsapp"}
    )
    monkeypatch.setattr(
        onboarding_transport,
        "read",
        lambda *a: {
            "data": {
                "id": "thread",
                "accountId": row["account_id"],
                "platform": "whatsapp",
                "participantId": row["participant_id"],
                "contactId": identifier,
            }
        },
    )
    calls = []
    subscribed = True

    def request(c, method, target, body=None):
        nonlocal subscribed
        assert target == identifier
        calls.append((method, body))
        if method == "PATCH":
            assert body == {"isSubscribed": False}
            subscribed = False
        channels = [
            {
                "accountId": row["account_id"],
                "platform": "whatsapp",
                "platformIdentifier": row["participant_id"],
            }
        ]
        if shared:
            channels.append(
                {
                    "accountId": "different-brand",
                    "platform": "whatsapp",
                    "platformIdentifier": row["participant_id"],
                }
            )
        return {
            "success": True,
            "contact": {"id": identifier, "isSubscribed": subscribed},
            "channels": channels,
        }

    monkeypatch.setattr(consent_transport, "contact_request", request)
    if shared:
        with pytest.raises(ValueError, match="opt_out_contact_shared"):
            consent_transport.unsubscribe({}, row)
        assert calls == [("GET", None)]
    else:
        consent_transport.unsubscribe({}, row)
        assert calls == [("GET", None), ("PATCH", {"isSubscribed": False}), ("GET", None)]


@pytest.mark.parametrize("failure", [None, "shared", "temporary"])
def test_unsubscribe_sync_preserves_local_refusal(configured, monkeypatch, failure):
    from contextlib import nullcontext

    from app.social import consent, consent_transport

    client, _, credentials = configured
    event = payload("573001110099")
    event["message"]["text"] = "No recibir información"
    assert send(client, credentials, event).status_code == 200
    calls = []

    def unsubscribe(c, row):
        assert c["profile_id"] == row["profile_id"]
        calls.append(row["participant_id"])
        if failure == "shared":
            raise ValueError("opt_out_contact_shared")
        if failure == "temporary":
            raise OSError("Synthetic outage")

    monkeypatch.setattr(consent.config, "locked", nullcontext)
    monkeypatch.setattr(consent_transport, "unsubscribe", unsubscribe)
    for _ in range(6):
        consent.sync()
        if failure == "temporary":
            with connect() as db:
                db.execute("UPDATE crm.social_opt_outs SET next_attempt=now()")
    with connect() as db:
        row = db.execute("SELECT * FROM crm.social_opt_outs").fetchone()
        assert row["remote_state"] == ("synced" if failure is None else "blocked")
        assert row["attempts"] == (5 if failure == "temporary" else 1)
        assert consent.suppressed(db, row)
    assert len(calls) == (5 if failure == "temporary" else 1)


def test_opt_out_during_tts_stops_audio_submission(audio_setup, monkeypatch):
    from test_whatsapp_audio import enqueue

    from app.voice import service as voice

    client, owner, credentials, _, calls, requests, _ = audio_setup
    event = enqueue(audio_setup)
    original = voice.bridge.request

    def tts(*args, **kwargs):
        result = original(*args, **kwargs)
        stop = copy.deepcopy(event)
        stop["id"] = "stop-during-tts"
        stop["message"].update(platformMessageId="stop-during-tts", text="No recibir información")
        assert send(client, credentials, stop).status_code == 200
        return result

    monkeypatch.setattr(voice.bridge, "request", tts)
    whatsapp_agent.tick()
    assert len(calls) == 1
    assert requests == []
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.social_opt_outs").fetchone()[0] == 1


def test_known_sender_must_confirm_identity_before_links(intake, configured, monkeypatch):
    from app.social import onboarding_transport

    incoming, deliveries, _, events, owner = intake
    original = onboarding_transport.provider.request

    def verified_sender(*args, **kwargs):
        result = original(*args, **kwargs)
        for message in result.get("messages", []):
            message.update(senderName="Mariana Torres", senderPhoneNumber="+573001110099")
        return result

    monkeypatch.setattr(onboarding_transport.provider, "request", verified_sender)
    event = incoming(text="Conocer opciones")
    for _ in range(4):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "question"]
    assert "Mariana Torres" in deliveries[1][1]["body"]["message"]
    assert state(owner)[0]["contact_id"] is None
    followup(event, "Confirmo", events, configured, "confirmed-known-sender")
    for _ in range(4):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "question", "website", "group"]
    assert state(owner)[0]["identity_confirmed"]


@pytest.mark.parametrize("reply_text,expected", [("Mariana Torres", True), ("Me interesa", False)])
def test_prompted_plain_name_is_identity_but_interest_is_not(
    intake, configured, monkeypatch, reply_text, expected
):
    from app.social import onboarding_transport

    incoming, deliveries, _, events, owner = intake
    original = onboarding_transport.provider.request

    def known_phone(*args, **kwargs):
        result = original(*args, **kwargs)
        for message in result.get("messages", []):
            message.update(senderPhoneNumber="+573001110099")
        return result

    monkeypatch.setattr(onboarding_transport.provider, "request", known_phone)
    event = incoming(text="Conocer opciones")
    for _ in range(3):
        onboarding.tick()
    followup(event, reply_text, events, configured, "plain-name-reply")
    for _ in range(4):
        onboarding.tick()
    row = state(owner)[0]
    assert bool(row["contact_id"]) is expected
    assert row["identity_confirmed"] is expected
    if expected:
        assert [d[0] for d in deliveries] == ["audio", "question", "website", "group"]
    else:
        assert "name" not in row["details"]
        assert [d[0] for d in deliveries] == ["audio", "question"]


def test_refusal_is_durable_while_a_send_is_in_progress(configured):
    import threading

    from app.social import consent

    client, _, credentials = configured
    event = payload("573001110099")
    event["message"]["text"] = "SALIR"
    row = onboarding.normalize(event, credentials["profile_id"])
    locked, release = threading.Event(), threading.Event()

    def busy_send():
        with consent.sending(row):
            locked.set()
            release.wait(8)

    worker = threading.Thread(target=busy_send)
    worker.start()
    assert locked.wait(2)
    try:
        result = send(client, credentials, event)
        with connect() as db:
            assert consent.suppressed(db, row)
            assert (
                db.execute("SELECT count(*) AS n FROM crm.social_webhook_events").fetchone()["n"]
                == 1
            )
        assert result.status_code == 200
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()


def test_refusal_survives_locked_welcome_projection(intake, configured):
    import threading

    incoming, deliveries, _, events, owner = intake
    event = incoming(text="Conocer opciones")
    row = state(owner)[0]
    locked, release = threading.Event(), threading.Event()

    def busy_row():
        with connect() as db:
            db.execute("SELECT id FROM crm.social_onboarding WHERE id=%s FOR UPDATE", (row["id"],))
            db.execute("SELECT pg_advisory_xact_lock(9142041)")
            locked.set()
            release.wait(8)

    worker = threading.Thread(target=busy_row)
    worker.start()
    assert locked.wait(2)
    try:
        followup(event, "SALIR", events, configured, "locked-welcome-refusal")
        with connect() as db:
            assert db.execute("SELECT count(*) AS n FROM crm.social_opt_outs").fetchone()["n"] == 1
            assert (
                db.execute(
                    "SELECT suppressed FROM crm.social_onboarding WHERE id=%s", (row["id"],)
                ).fetchone()["suppressed"]
                is False
            )
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    for _ in range(3):
        onboarding.tick()
    assert deliveries == []
