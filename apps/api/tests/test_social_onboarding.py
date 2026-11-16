"""Deterministic intake uses real contact fields, never routing IDs as identity."""
# ruff: noqa: F811

import pytest

from app.social.onboarding import details, opted_out


@pytest.mark.parametrize(
    "text",
    [
        "Full name: Mariana Torres Phone number: +57 300 111 0099 City: Bogotá",
        "City: Bogotá\nPhone number: 3001110099\nFull name: Mariana Torres",
        "¡Hola! Completé el formulario. Full name: Mariana Torres ¿Método de pago?: Contado Phone number: +573001110099 City: Bogotá",
    ],
)
def test_shuffled_ad_form_fields(text):
    assert details(text, {}, {}) == {"name": "Mariana Torres", "phone": "+573001110099"}


def test_opaque_platform_ids_are_not_contact_phones():
    assert (
        details("Hola", {"name": "+CO.1141068341986850", "phoneNumber": "+CO.1141068341986850"}, {})
        == {}
    )
    assert details("Hola", {"name": "Mariana Torres", "phoneNumber": "+573001110099"}, {}) == {
        "name": "Mariana Torres",
        "phone": "+573001110099",
    }


def test_conflicting_form_fields_fail_closed():
    with pytest.raises(ValueError):
        details(
            "Full name: Mariana Torres Phone number: 3001110099 Phone number: 3001110088", {}, {}
        )


def test_missing_fields_can_be_supplied_without_inventing_a_name():
    assert details("3001110099", {}, {"name": "Mariana Torres"}) == {
        "name": "Mariana Torres",
        "phone": "+573001110099",
    }
    assert details("Quiero información", {}, {}) == {}


@pytest.mark.parametrize(
    "text",
    [
        "SALIR",
        "No recibir más",
        "No me contacten",
        "No quiero más mensajes",
        "No quiero que me contacten",
        "No me vuelvas a escribir",
        "No deseo recibir mensajes",
    ],
)
def test_opt_out_is_terminal(text):
    assert opted_out(text)


# Database integration tests use only the isolated, disposable CRM test database.
import base64
import copy
from contextlib import nullcontext

import psycopg
from psycopg.rows import dict_row
from test_crm import authenticated  # noqa: F401
from test_whatsapp_agent import DOC, configured, payload, send  # noqa: F401

from app.crm.database import connect
from app.social import media, media_process, onboarding, onboarding_transport, whatsapp_audio
from app.voice import service as voice

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"fixture-audio" * 5


@pytest.fixture
def intake(configured, monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(onboarding, "WELCOME_UNTIL", datetime.now(UTC) + timedelta(days=7))
    client, owner, credentials = configured
    monkeypatch.setattr(
        whatsapp_audio,
        "_provider",
        lambda db: {
            "revision": 3,
            "connection_version": 1,
            "voice_id": "sofia",
            "model_id": "multilingual",
        },
    )
    with psycopg.connect(owner) as db:
        db.execute("TRUNCATE crm.social_welcome_audio")
    with connect() as db:
        admin = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()
        db.execute(
            "UPDATE crm.control_connections SET enabled=true WHERE key IN ('facebook','elevenlabs')"
        )
        onboarding.configure(
            db,
            owner_id=admin["id"],
            profile_id=credentials["profile_id"],
            accounts={DOC["account_id"]: "whatsapp", "facebook-one": "facebook"},
            group_url="https://chat.whatsapp.com/FixtureOnly",
            facebook_takeover=True,
        )
    events, deliveries, synthesis = {}, [], []
    monkeypatch.setattr(onboarding_transport.config, "locked", nullcontext)
    monkeypatch.setattr(media, "_isolated", media_process.execute)
    monkeypatch.setattr(
        onboarding_transport.service,
        "account",
        lambda c, a: {"platform": "facebook" if a == "facebook-one" else "whatsapp"},
    )
    monkeypatch.setattr(
        whatsapp_audio,
        "_provider",
        lambda db: {
            "revision": 3,
            "connection_version": 1,
            "voice_id": "sofia",
            "model_id": "multilingual",
        },
    )

    def tts(path, body, **kwargs):
        with connect() as db:
            assert db.execute("SELECT count(*) AS n FROM crm.contacts").fetchone()["n"] > 0
            assert (
                db.execute(
                    "SELECT state FROM crm.social_welcome_audio WHERE id=%s", (body["id"],)
                ).fetchone()["state"]
                == "synthesizing"
            )
        synthesis.append(body)
        return {
            "status": "completed",
            "mime_type": "audio/mpeg",
            "data_base64": base64.b64encode(MP3).decode(),
        }

    def request(c, op, args, key=None):
        event = events[args["path"]["conversationId"]]
        row = {
            "id": event["conversation"]["id"],
            "accountId": event["account"]["id"],
            "platform": event["account"]["platform"],
            "participantId": event["conversation"]["participantId"],
        }
        if op["method"] == "POST":
            deliveries.append(
                (
                    "links" if "Página web:" in args["body"]["message"] else "question",
                    copy.deepcopy(args),
                    key,
                )
            )
            return {"success": True, "data": {"messageId": "sent-" + str(len(deliveries))}}
        if op["path"].endswith("/messages"):
            return {
                "messages": [
                    {
                        "id": event["message"]["platformMessageId"],
                        "conversationId": row["id"],
                        "accountId": row["accountId"],
                        "platform": row["platform"],
                        "senderId": row["participantId"],
                        "senderName": None,
                        "direction": "incoming",
                        "message": event["message"]["text"],
                        "createdAt": event["message"]["sentAt"],
                    }
                ]
            }
        return {"data": row}

    def audio(row, c):
        assert row["state"] == "audio_reserved" and row["contact_id"] and row["deal_id"]
        assert bytes(row["audio"]) == MP3
        deliveries.append(("audio", row["conversation_id"], None))
        return {"status": "accepted", "message_id": "audio-accepted"}

    monkeypatch.setattr(onboarding_transport.provider, "request", request)
    monkeypatch.setattr(onboarding_transport, "transmit_audio", audio)
    monkeypatch.setattr(voice.bridge, "request", tts)

    def incoming(
        platform="whatsapp",
        text="Full name: Mariana Torres Phone number: 3001110099 City: Bogotá",
        suffix="one",
    ):
        event = payload("CO.opaque-one" if platform == "whatsapp" else "facebook-opaque")
        event["id"] = "event-" + suffix
        event["account"].update(
            id=DOC["account_id"] if platform == "whatsapp" else "facebook-one", platform=platform
        )
        event["conversation"].update(id="thread-" + suffix, platform=platform)
        event["message"].update(platform=platform, conversationId="thread-" + suffix, text=text)
        event["message"]["sender"].pop("phoneNumber", None)
        events["thread-" + suffix] = event
        assert send(client, credentials, event).status_code == 200
        return event

    return incoming, deliveries, synthesis, events, owner


def state(owner):
    with psycopg.connect(owner, row_factory=dict_row) as db:
        return db.execute("SELECT * FROM crm.social_onboarding ORDER BY created_at,id").fetchall()


def test_registration_then_audio_then_links_and_no_duplicate_on_replay(intake):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming()
    onboarding.tick()
    assert state(owner)[0]["state"] == "audio_accepted"
    assert [d[0] for d in deliveries] == ["audio"]
    onboarding.tick()  # Restart-safe continuation never sends the audio twice.
    assert state(owner)[0]["state"] == "completed"
    assert [d[0] for d in deliveries] == ["audio", "links"]
    assert "https://jardinesdelencanto.site/" in deliveries[1][1]["body"]["message"]
    assert "https://chat.whatsapp.com/FixtureOnly" in deliveries[1][1]["body"]["message"]
    onboarding.tick()
    assert len(synthesis) == 1 and len(deliveries) == 2
    # Distinct Facebook thread, same actual phone: one contact, one pipeline record,
    # a welcome on the original Facebook thread, and the same cached Sofía audio.
    incoming("facebook", suffix="two")
    onboarding.tick()
    onboarding.tick()
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM crm.deals").fetchone()[0] == 1
    assert len(synthesis) == 1
    assert [d[0] for d in deliveries] == ["audio", "links", "audio", "links"]
    assert deliveries[-1][1]["path"]["conversationId"] == "thread-two"


def test_missing_identity_requests_details_before_creating_or_paying(intake):
    incoming, deliveries, synthesis, events, owner = intake
    event = incoming(text="Hola")
    onboarding.tick()
    assert state(owner)[0]["state"] == "waiting"
    assert [d[0] for d in deliveries] == ["question"]
    assert synthesis == []
    event = copy.deepcopy(event)
    event["id"] = "event-followup"
    event["message"]["platformMessageId"] = "source-followup"
    event["message"]["text"] = "Nombre completo: Mariana Torres Celular: 3001110099"
    events["thread-one"] = event
    with connect() as db:
        assert onboarding.enqueue(db, event, "a" * 24)
    onboarding.tick()
    onboarding.tick()
    assert state(owner)[0]["state"] == "completed"
    assert [d[0] for d in deliveries] == ["question", "audio", "links"]


def test_unknown_audio_never_retries_or_sends_links(intake, monkeypatch):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming()

    def uncertain(*args):
        raise TimeoutError

    monkeypatch.setattr(onboarding_transport, "transmit_audio", uncertain)
    onboarding.tick()
    assert state(owner)[0]["state"] == "unknown"
    onboarding.tick()
    assert deliveries == [] and len(synthesis) == 1


def test_opt_out_between_audio_and_links_stops_the_sequence(intake):
    incoming, deliveries, _synthesis, events, owner = intake
    event = incoming()
    onboarding.tick()
    event = copy.deepcopy(event)
    event["id"] = "event-stop"
    event["message"]["platformMessageId"] = "source-stop"
    event["message"]["text"] = "No recibir más"
    events["thread-one"] = event
    with connect() as db:
        assert onboarding.enqueue(db, event, "a" * 24)
    onboarding.tick()
    assert state(owner)[0]["suppressed"]
    assert [d[0] for d in deliveries] == ["audio"]


def test_existing_won_lead_and_identity_are_not_overwritten(intake):
    incoming, _deliveries, _synthesis, _events, _owner = intake
    with connect() as db:
        contact = db.execute(
            "INSERT INTO crm.contacts(name,phone,source) VALUES('Existing Customer','+573001110099','referral') RETURNING id"
        ).fetchone()
        db.execute("INSERT INTO crm.deals(contact_id,stage) VALUES(%s,'won')", (contact["id"],))
    incoming()
    onboarding.tick()
    with connect() as db:
        assert db.execute("SELECT name,source FROM crm.contacts").fetchone() == {
            "name": "Existing Customer",
            "source": "referral",
        }
        assert db.execute("SELECT stage FROM crm.deals").fetchone()["stage"] == "won"


def test_developer_routing_and_unrelated_accounts_are_unchanged(intake):
    _incoming, _deliveries, _synthesis, _events, owner = intake
    with connect() as db:
        assert onboarding.enqueue(db, payload(), "a" * 24) is False
        event = payload("573001110099")
        event["account"]["id"] = "unrelated-account"
        assert onboarding.enqueue(db, event, "a" * 24) is False
    assert state(owner) == []


@pytest.mark.parametrize(
    "mutation", ["credentials", "disabled", "source", "human", "standby", "expired"]
)
def test_revocation_or_changed_provider_context_prevents_sending(intake, monkeypatch, mutation):
    from datetime import UTC, datetime, timedelta

    incoming, deliveries, synthesis, _events, owner = intake
    incoming()
    if mutation == "credentials":
        original = onboarding.config.required()
        monkeypatch.setattr(
            onboarding.config, "required", lambda: {**original, "api_key": "new-key"}
        )
    elif mutation == "disabled":
        with connect() as db:
            db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='zernio'")
    else:
        original = onboarding_transport.provider.request

        def altered(*args, **kwargs):
            result = original(*args, **kwargs)
            if "messages" in result:
                message = result["messages"][0]
                if mutation == "source":
                    message["message"] = "Changed text"
                if mutation == "expired":
                    message["createdAt"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
            elif "data" in result:
                if mutation == "human":
                    result["data"]["threadControl"] = "other"
                if mutation == "standby":
                    result["data"]["metadata"] = {"standby": True}
            return result

        monkeypatch.setattr(onboarding_transport.provider, "request", altered)
    onboarding.tick()
    assert state(owner)[0]["state"] == "blocked"
    assert deliveries == [] and synthesis == []
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM crm.contacts").fetchone()["n"] == 0


def test_interrupted_audio_reservation_is_never_replayed(intake):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming()
    with connect() as db:
        db.execute("UPDATE crm.social_onboarding SET state='audio_reserved'")
    onboarding.tick()
    assert state(owner)[0]["state"] == "unknown"
    assert deliveries == [] and synthesis == []


def test_phone_dedup_is_safe_under_concurrent_capture(intake):
    from concurrent.futures import ThreadPoolExecutor

    from app.crm.models import ContactInput
    from app.crm.services import capture_contact

    def capture(index):
        with connect() as db:
            return capture_contact(
                db,
                ContactInput(
                    name="Mariana Torres",
                    phone="3001110099",
                    source="whatsapp" if index % 2 else "social_campaign",
                ),
            )[0]["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(capture, range(8)))
    assert len(set(ids)) == 1
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM crm.deals").fetchone()["n"] == 1


def test_final_submission_and_opt_out_share_the_same_row_lock(intake, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    incoming, deliveries, _synthesis, _events, owner = intake
    incoming()
    onboarding.tick()
    identifier = state(owner)[0]["id"]
    original = onboarding_transport.provider.request
    locked = []

    def try_suppress():
        try:
            with connect() as db:
                db.execute("SET LOCAL lock_timeout='80ms'")
                db.execute(
                    "UPDATE crm.social_onboarding SET suppressed=true WHERE id=%s", (identifier,)
                )
            return False
        except psycopg.errors.LockNotAvailable:
            return True

    def request(*args, **kwargs):
        if args[1]["method"] == "POST":
            with ThreadPoolExecutor(max_workers=1) as pool:
                locked.append(pool.submit(try_suppress).result())
        return original(*args, **kwargs)

    monkeypatch.setattr(onboarding_transport.provider, "request", request)
    onboarding.tick()
    assert locked == [True]
    assert [d[0] for d in deliveries] == ["audio", "links"]
    assert try_suppress() is False
    assert state(owner)[0]["suppressed"]


def test_simultaneous_first_contact_cannot_discard_a_stop(intake):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    _incoming, _deliveries, _synthesis, _events, owner = intake
    first = payload("573001110099")
    first["message"]["text"] = "Full name: Mariana Torres Phone number: 3001110099"
    stop = copy.deepcopy(first)
    stop["id"] = "concurrent-stop"
    stop["message"]["platformMessageId"] = "concurrent-stop-source"
    stop["message"]["text"] = "No quiero que me contacten"
    awaiting_quota = Event()

    class ObservedConnection:
        def __init__(self, db):
            self.db = db

        def execute(self, sql, *args):
            if "pg_advisory_xact_lock(9142041)" in sql:
                awaiting_quota.set()
            return self.db.execute(sql, *args)

    def suppress():
        with connect() as db:
            return onboarding.enqueue(ObservedConnection(db), stop, "a" * 24)

    with connect() as db, ThreadPoolExecutor(max_workers=1) as pool:
        assert onboarding.enqueue(db, first, "a" * 24)
        future = pool.submit(suppress)
        assert awaiting_quota.wait(timeout=3)
        db.commit()
        assert future.result(timeout=5)
    rows = state(owner)
    assert len(rows) == 1 and rows[0]["suppressed"]


def test_elapsed_fair_does_not_take_over_future_customer_conversations(intake, monkeypatch):
    from datetime import UTC, datetime, timedelta

    _incoming, _deliveries, _synthesis, _events, owner = intake
    monkeypatch.setattr(onboarding, "WELCOME_UNTIL", datetime.now(UTC) - timedelta(seconds=1))
    with connect() as db:
        assert onboarding.enqueue(db, payload("573001110099"), "a" * 24) is False
    assert state(owner) == []
