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
    events, deliveries, synthesis, history = {}, [], [], {}
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
                    key.rsplit("-", 1)[-1],
                    copy.deepcopy(args),
                    key,
                )
            )
            return {"success": True, "data": {"messageId": "sent-" + str(len(deliveries))}}
        if op["path"].endswith("/messages"):
            seen = set()
            messages = []
            for item in [event, *reversed(history.get(row["id"], []))]:
                message_id = item["message"]["platformMessageId"]
                if message_id in seen:
                    continue
                seen.add(message_id)
                messages.append(
                    {
                        "id": message_id,
                        "conversationId": row["id"],
                        "accountId": row["accountId"],
                        "platform": row["platform"],
                        "senderId": row["participantId"],
                        "senderName": None,
                        "direction": "incoming",
                        "message": item["message"]["text"],
                        "createdAt": item["message"]["sentAt"],
                    }
                )
            return {"messages": messages}
        return {"data": row}

    def audio(row, c):
        assert row["state"] == "audio_reserved"
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
        history.setdefault("thread-" + suffix, []).append(copy.deepcopy(event))
        assert send(client, credentials, event).status_code == 200
        return event

    return incoming, deliveries, synthesis, events, owner


def state(owner):
    with psycopg.connect(owner, row_factory=dict_row) as db:
        return db.execute("SELECT * FROM crm.social_onboarding ORDER BY created_at,id").fetchall()


@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
def test_first_hello_gets_audio_website_group_before_registration_question(intake, platform):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming(platform, text="Hola")
    for _ in range(3):
        onboarding.tick()
    assert [item[0] for item in deliveries] == ["audio", "website", "group"]
    assert state(owner)[0]["state"] == "waiting"
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 0
    assert len(synthesis) == 1
    onboarding.tick()
    assert [item[0] for item in deliveries] == ["audio", "website", "group", "question"]


def test_same_participant_in_a_new_thread_never_repeats_welcome(intake):
    incoming, deliveries, _synthesis, _events, owner = intake
    incoming()
    for _ in range(3):
        onboarding.tick()
    incoming(suffix="second-thread")
    for _ in range(4):
        onboarding.tick()
    assert [item[0] for item in deliveries] == ["audio", "website", "group"]
    assert len(state(owner)) == 2
    assert state(owner)[1]["welcome_required"] is False


def test_identity_messages_during_welcome_are_not_overwritten_by_later_chatter(intake):
    incoming, deliveries, _synthesis, events, owner = intake
    event = incoming(text="Hola")
    onboarding.tick()
    for identifier, text in [
        ("identity", "Nombre completo: Mariana Torres Celular: 3001110099"),
        ("thanks", "Gracias"),
    ]:
        event = copy.deepcopy(event)
        event["id"] = identifier
        event["message"]["platformMessageId"] = identifier
        event["message"]["text"] = text
        # Keep the previous verified message in the fake REST history.
        if identifier == "identity":
            identity = copy.deepcopy(event)
        events["thread-one"] = event
        with connect() as db:
            assert onboarding.enqueue(db, event, "a" * 24)
    original = onboarding_transport.provider.request

    def history_with_identity(*args, **kwargs):
        result = original(*args, **kwargs)
        if "messages" in result:
            item = copy.deepcopy(result["messages"][0])
            item.update(id="identity", message=identity["message"]["text"])
            result["messages"].append(item)
        return result

    from unittest.mock import patch

    with patch.object(onboarding_transport.provider, "request", history_with_identity):
        for _ in range(4):
            onboarding.tick()
    assert [item[0] for item in deliveries] == ["audio", "website", "group"]
    assert state(owner)[0]["state"] == "completed"
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT name,phone FROM crm.contacts").fetchall() == [
            ("Mariana Torres", "+573001110099")
        ]


@pytest.mark.parametrize("phase", ["website", "group"])
def test_ambiguous_text_phase_is_never_replayed_or_followed(intake, monkeypatch, phase):
    incoming, deliveries, _synthesis, _events, owner = intake
    incoming()
    onboarding.tick()
    if phase == "group":
        onboarding.tick()
    before = list(deliveries)
    original = onboarding_transport.provider.request
    attempts = []

    def uncertain(*args, **kwargs):
        if args[1]["method"] == "POST":
            attempts.append(kwargs.get("key"))
            raise TimeoutError
        return original(*args, **kwargs)

    monkeypatch.setattr(onboarding_transport.provider, "request", uncertain)
    for _ in range(3):
        onboarding.tick()
    assert state(owner)[0]["state"] == "unknown"
    assert len(attempts) == 1 and attempts[0].endswith("-" + phase)
    assert deliveries == before


@pytest.mark.parametrize(
    "phase,reason", [("website", "welcome_audio_required"), ("group", "welcome_website_required")]
)
def test_direct_transport_requires_each_predecessor_receipt(intake, phase, reason):
    incoming, deliveries, _synthesis, _events, _owner = intake
    incoming(text="Hola")
    with connect() as db:
        row = db.execute(
            "UPDATE crm.social_onboarding SET state=%s RETURNING id", (phase + "_reserved",)
        ).fetchone()
    with pytest.raises(ValueError, match=reason):
        onboarding_transport.execute("welcome_" + phase, str(row["id"]))
    assert deliveries == []


def test_legacy_audio_acceptance_resumes_at_website_without_audio(intake):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming()
    with connect() as db:
        db.execute(
            "UPDATE crm.social_onboarding SET state='audio_accepted',audio_receipt=%s",
            (psycopg.types.json.Jsonb({"status": "accepted", "message_id": "legacy-audio"}),),
        )
    onboarding.tick()
    onboarding.tick()
    assert [item[0] for item in deliveries] == ["website", "group"]
    assert synthesis == []
    assert state(owner)[0]["state"] == "completed"


def test_upgrade_preserves_completed_ambiguous_and_duplicate_participant_history(intake):
    from pathlib import Path
    from uuid import uuid4

    from psycopg import sql
    from psycopg.types.json import Jsonb

    _incoming, _deliveries, _synthesis, _events, owner = intake
    schema = "welcome_probe_" + uuid4().hex
    migrations = Path(__file__).parents[1] / "migrations"
    with psycopg.connect(owner) as db:
        assert db.info.dbname == "jardines_crm_test"
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for table in ("users", "contacts", "deals"):
            db.execute(
                sql.SQL("CREATE TABLE {}.{}(id uuid PRIMARY KEY)").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
        db.execute(
            (migrations / "021_social_onboarding.sql").read_text().replace("crm.", schema + ".")
        )
        ids = {}
        for state_name in (
            "completed",
            "unknown",
            "blocked",
            "audio_accepted",
            "links_reserved",
            "waiting",
            "pending",
        ):
            identifier = uuid4()
            ids[state_name] = identifier
            participant = "shared" if state_name in {"completed", "pending"} else state_name
            db.execute(
                sql.SQL(
                    "INSERT INTO {}.social_onboarding(id,profile_id,account_id,conversation_id,participant_id,platform,config_version,source,state) "
                    "VALUES(%s,'profile','account',%s,%s,'whatsapp',1,%s,%s)"
                ).format(sql.Identifier(schema)),
                (
                    identifier,
                    state_name,
                    participant,
                    Jsonb({"message_id": state_name}),
                    state_name,
                ),
            )
        db.execute(
            (migrations / "026_ordered_social_welcome.sql")
            .read_text()
            .replace("crm.", schema + ".")
        )
        rows = dict(
            db.execute(
                sql.SQL("SELECT conversation_id,state FROM {}.social_onboarding").format(
                    sql.Identifier(schema)
                )
            ).fetchall()
        )
        assert rows == {
            "completed": "completed",
            "unknown": "unknown",
            "blocked": "blocked",
            "audio_accepted": "audio_accepted",
            "links_reserved": "unknown",
            "waiting": "pending",
            "pending": "pending",
        }
        claimed = db.execute(
            sql.SQL(
                "SELECT onboarding_id FROM {}.social_welcome_claims WHERE participant_id='shared'"
            ).format(sql.Identifier(schema))
        ).fetchone()[0]
        assert claimed == ids["completed"]
        assert (
            db.execute(
                sql.SQL("SELECT welcome_required FROM {}.social_onboarding WHERE id=%s").format(
                    sql.Identifier(schema)
                ),
                (ids["pending"],),
            ).fetchone()[0]
            is False
        )
        queued = {
            row[0]
            for row in db.execute(
                sql.SQL("SELECT onboarding_id FROM {}.social_onboarding_inputs").format(
                    sql.Identifier(schema)
                )
            ).fetchall()
        }
        assert queued == {ids["audio_accepted"], ids["waiting"], ids["pending"]}
        db.rollback()  # No probe schema or records survive the isolated test.


def test_tiktok_does_not_gain_an_unsupported_audio_path(intake):
    _incoming, deliveries, synthesis, _events, owner = intake
    event = payload("opaque-tiktok")
    event["account"].update(platform="tiktok")
    event["conversation"]["platform"] = "tiktok"
    event["message"]["platform"] = "tiktok"
    with connect() as db:
        assert onboarding.enqueue(db, event, "a" * 24) is False
    onboarding.tick()
    assert state(owner) == [] and deliveries == [] and synthesis == []


def test_registration_then_ordered_welcome_and_no_duplicate_on_replay(intake):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming()
    onboarding.tick()
    assert state(owner)[0]["state"] == "audio_accepted"
    assert [d[0] for d in deliveries] == ["audio"]
    onboarding.tick()  # Restart-safe continuation never sends the audio twice.
    assert state(owner)[0]["state"] == "website_accepted"
    onboarding.tick()
    assert state(owner)[0]["state"] == "completed"
    assert [d[0] for d in deliveries] == ["audio", "website", "group"]
    assert "https://jardinesdelencanto.site/" in deliveries[1][1]["body"]["message"]
    assert "https://chat.whatsapp.com/FixtureOnly" in deliveries[2][1]["body"]["message"]
    onboarding.tick()
    assert len(synthesis) == 1 and len(deliveries) == 3
    # Distinct Facebook thread, same actual phone: one contact, one pipeline record,
    # a welcome on the original Facebook thread, and the same cached Sofía audio.
    incoming("facebook", suffix="two")
    onboarding.tick()
    onboarding.tick()
    onboarding.tick()
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM crm.deals").fetchone()[0] == 1
    assert len(synthesis) == 1
    assert [d[0] for d in deliveries] == ["audio", "website", "group"] * 2
    assert deliveries[-1][1]["path"]["conversationId"] == "thread-two"


@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
def test_welcome_links_explain_the_official_site_and_event_group(intake, platform):
    incoming, deliveries, synthesis, _events, owner = intake
    incoming(platform)
    onboarding.tick()
    onboarding.tick()
    onboarding.tick()
    assert state(owner)[0]["state"] == "completed"
    assert [item[0] for item in deliveries] == ["audio", "website", "group"]
    assert deliveries[1][1]["body"]["message"] == (
        "Aquí puedes ver la página oficial de nuestro proyecto:\nhttps://jardinesdelencanto.site/"
    )
    assert deliveries[2][1]["body"]["message"] == (
        "Para estar al tanto de toda la información previa al evento, "
        "ingresa a nuestro grupo de WhatsApp:\n"
        "https://chat.whatsapp.com/FixtureOnly"
    )
    assert synthesis[0]["arguments"]["text"] == onboarding.SCRIPT


def test_missing_identity_is_requested_after_welcome_and_captured_without_replaying(intake):
    incoming, deliveries, synthesis, events, owner = intake
    event = incoming(text="Hola")
    for _ in range(4):
        onboarding.tick()
    assert state(owner)[0]["state"] == "waiting"
    assert [d[0] for d in deliveries] == ["audio", "website", "group", "question"]
    assert deliveries[3][1]["body"]["message"] == (
        "Hola, soy Sara. Para registrarte, envíame tu nombre completo y número de celular. "
        "Puedes escribir: Nombre completo: … Celular: …"
    )
    assert len(synthesis) == 1
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
    assert [d[0] for d in deliveries] == ["audio", "website", "group", "question"]


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
    assert [d[0] for d in deliveries] == ["audio", "website"]
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


@pytest.mark.parametrize(
    ("first_state", "second_state", "suppressed", "expected_state"),
    [
        ("pending", "audio_accepted", False, "audio_accepted"),
        ("completed", "waiting", True, "pending"),
    ],
)
def test_upgrade_consolidates_progress_and_historical_stop(
    authenticated, first_state, second_state, suppressed, expected_state
):
    from datetime import UTC, datetime, timedelta
    from pathlib import Path
    from uuid import uuid4

    from psycopg import sql
    from psycopg.types.json import Jsonb

    _, owner, _ = authenticated
    schema = "welcome_history_" + uuid4().hex
    migrations = Path(__file__).parents[1] / "migrations"
    with psycopg.connect(owner) as db:
        assert db.info.dbname == "jardines_crm_test"
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for table in ("users", "contacts", "deals"):
            db.execute(
                sql.SQL("CREATE TABLE {}.{}(id uuid PRIMARY KEY)").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
        db.execute(
            (migrations / "021_social_onboarding.sql").read_text().replace("crm.", schema + ".")
        )
        for index, (status, stopped) in enumerate(
            [(first_state, False), (second_state, suppressed)]
        ):
            db.execute(
                sql.SQL(
                    "INSERT INTO {}.social_onboarding(profile_id,account_id,conversation_id,participant_id,platform,config_version,source,state,suppressed,created_at,audio_receipt) "
                    "VALUES('profile','account',%s,'participant','whatsapp',1,%s,%s,%s,%s,%s)"
                ).format(sql.Identifier(schema)),
                (
                    "thread-" + str(index),
                    Jsonb({"message_id": str(index)}),
                    status,
                    stopped,
                    datetime.now(UTC) - timedelta(minutes=2 - index),
                    Jsonb(
                        {"status": "accepted", "message_id": "old-audio"}
                        if status == "audio_accepted"
                        else {}
                    ),
                ),
            )
        for migration in sorted(migrations.glob("02[6-8]_*.sql")):
            db.execute(migration.read_text().replace("crm.", schema + "."))
        chosen = db.execute(
            sql.SQL(
                "SELECT o.state,o.suppressed,o.welcome_required FROM {}.social_welcome_claims c "
                "JOIN {}.social_onboarding o ON o.id=c.onboarding_id"
            ).format(sql.Identifier(schema), sql.Identifier(schema))
        ).fetchone()
        assert chosen == (expected_state, suppressed, True)
        others = db.execute(
            sql.SQL(
                "SELECT o.welcome_required,o.suppressed FROM {}.social_onboarding o "
                "WHERE o.id NOT IN (SELECT onboarding_id FROM {}.social_welcome_claims)"
            ).format(sql.Identifier(schema), sql.Identifier(schema))
        ).fetchall()
        assert others == [(False, suppressed)]
        db.rollback()


@pytest.mark.parametrize("new_thread", [True, False])
def test_historical_sibling_stop_prevents_new_and_queued_dispatch(intake, new_thread):
    incoming, deliveries, _, _, _ = intake
    incoming()
    for _ in range(3):
        onboarding.tick()
    incoming(text="Hola", suffix="old-stopped-thread")
    with connect() as db:
        # Older workers scoped STOP to one conversation instead of the participant.
        db.execute(
            "UPDATE crm.social_onboarding SET suppressed=true,state='waiting',asked=true WHERE conversation_id='thread-old-stopped-thread'"
        )
    deliveries.clear()
    if new_thread:
        incoming(text="Hola", suffix="new-thread")
    else:
        # An active sibling queued before STOP must also fail the final send guard.
        with connect() as db:
            db.execute(
                "UPDATE crm.social_onboarding SET state='pending',asked=false WHERE NOT suppressed"
            )
    onboarding.tick()
    assert deliveries == []


@pytest.mark.parametrize("existing,admitted", [(100, True), (999, True), (1000, False)])
def test_welcome_rolling_daily_limit_is_one_thousand(intake, existing, admitted):
    incoming, deliveries, _, _, owner = intake
    incoming(text="Hola", suffix="budget-source")
    with psycopg.connect(owner) as db:
        db.execute(
            """INSERT INTO crm.social_onboarding(profile_id,account_id,conversation_id,
            participant_id,platform,config_version,source,state,created_at)
            SELECT profile_id,account_id,'quota-thread-'||n,'quota-person-'||n,platform,
            config_version,source,'completed',now()-interval '2 hours'
            FROM crm.social_onboarding CROSS JOIN generate_series(1,%s) n
            WHERE conversation_id='thread-budget-source' """,
            (existing - 1,),
        )
    incoming(text="Hola", suffix="budget-candidate")
    with psycopg.connect(owner) as db:
        assert (
            bool(
                db.execute(
                    "SELECT 1 FROM crm.social_onboarding WHERE conversation_id='thread-budget-candidate'"
                ).fetchone()
            )
            is admitted
        )
        assert db.execute("SELECT count(*) FROM crm.social_onboarding").fetchone()[
            0
        ] == existing + int(admitted)
    assert deliveries == []


def missed_signed_event(intake, configured, platform="whatsapp", age_hours=1):
    from datetime import UTC, datetime, timedelta

    incoming, _, _, _, owner = intake
    client, _, credentials = configured
    event = incoming(platform, text="Hola", suffix="missed")
    with psycopg.connect(owner) as db:
        db.execute("DELETE FROM crm.social_onboarding")
        db.execute("DELETE FROM crm.social_webhook_events")
        db.execute("UPDATE crm.social_onboarding_config SET enabled_at=now()-interval '3 hours'")
    event["message"]["sentAt"] = (datetime.now(UTC) - timedelta(hours=age_hours)).isoformat()
    assert send(client, credentials, event).status_code == 200
    assert state(owner) == []  # Ordinary inbound enrollment still rejects old events.
    return event


@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
def test_operator_recovers_only_signed_unanswered_welcome_once(intake, configured, platform):
    event = missed_signed_event(intake, configured, platform)
    _, deliveries, _, _, owner = intake
    with connect() as db:
        actor = onboarding.settings(db)["owner_id"]
        assert onboarding.recover_unanswered(db, event["id"], actor_id=actor)["state"] == "queued"
    with connect() as db, pytest.raises(ValueError, match="recovery_existing_history"):
        onboarding.recover_unanswered(db, event["id"], actor_id=actor)
    for _ in range(3):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "website", "group"]
    assert state(owner)[0]["recovery_event_id"] == event["id"]


@pytest.mark.parametrize(
    "mutation", ["manual_reply", "uncertain_history", "expired", "wrong_actor"]
)
def test_operator_recovery_rejects_unsafe_history_without_enrollment(
    intake, configured, monkeypatch, mutation
):
    from uuid import uuid4

    event = missed_signed_event(intake, configured, age_hours=25 if mutation == "expired" else 1)
    _, deliveries, _, _, owner = intake
    if mutation == "manual_reply":
        original = onboarding_transport.provider.request

        def replied(credentials, spec, args, key=None):
            result = original(credentials, spec, args, key)
            if spec["path"].endswith("/messages"):
                message = {
                    **result["messages"][0],
                    "id": "manual-response",
                    "direction": "outgoing",
                    "message": "Te respondió un asesor",
                }
                result["messages"].insert(0, message)
            return result

        monkeypatch.setattr(onboarding_transport.provider, "request", replied)
    if mutation == "uncertain_history":
        with connect() as db:
            db.execute(
                """INSERT INTO crm.social_onboarding(profile_id,account_id,conversation_id,participant_id,platform,config_version,source,state)
                VALUES(%s,%s,%s,%s,%s,1,%s,'unknown')""",
                (
                    configured[2]["profile_id"],
                    event["account"]["id"],
                    event["conversation"]["id"],
                    event["conversation"]["participantId"],
                    event["account"]["platform"],
                    psycopg.types.json.Jsonb(
                        onboarding.normalize(event, configured[2]["profile_id"])
                    ),
                ),
            )
    with connect() as db:
        actor = uuid4() if mutation == "wrong_actor" else onboarding.settings(db)["owner_id"]
        with pytest.raises(
            ValueError,
            match={
                "manual_reply": "welcome_recovery_already_answered",
                "uncertain_history": "recovery_existing_history",
                "expired": "recovery_source_expired",
                "wrong_actor": "recovery_not_authorized",
            }[mutation],
        ):
            onboarding.recover_unanswered(db, event["id"], actor_id=actor)
    assert len(state(owner)) == int(mutation == "uncertain_history")
    assert deliveries == []


@pytest.mark.parametrize("phase_count", [0, 2])
def test_recovery_rechecks_manual_reply_before_each_remaining_phase(
    intake, configured, monkeypatch, phase_count
):
    event = missed_signed_event(intake, configured)
    _, deliveries, _, _, owner = intake
    with connect() as db:
        onboarding.recover_unanswered(db, event["id"], actor_id=onboarding.settings(db)["owner_id"])
    original = onboarding_transport.provider.request
    manual = False

    def messages_with_sent_receipts(credentials, spec, args, key=None):
        result = original(credentials, spec, args, key)
        if spec["method"] == "GET" and spec["path"].endswith("/messages"):
            prototype = result["messages"][0]
            for index, item in enumerate(deliveries, 1):
                identifier = "audio-accepted" if item[0] == "audio" else "sent-" + str(index)
                result["messages"].insert(
                    0, {**prototype, "id": identifier, "direction": "outgoing"}
                )
            if manual:
                result["messages"].insert(
                    0, {**prototype, "id": "human-response", "direction": "outgoing"}
                )
        return result

    monkeypatch.setattr(onboarding_transport.provider, "request", messages_with_sent_receipts)
    for _ in range(phase_count):
        onboarding.tick()
    manual = True
    onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "website"][:phase_count]
    assert state(owner)[0]["state"] == "blocked"


def test_recovery_requires_an_actual_signed_receipt(intake, configured):
    _, deliveries, _, _, owner = intake
    with connect() as db, pytest.raises(ValueError, match="recovery_signed_receipt_required"):
        onboarding.recover_unanswered(
            db, "not-a-real-event", actor_id=onboarding.settings(db)["owner_id"]
        )
    assert state(owner) == [] and deliveries == []


@pytest.mark.parametrize(
    "metadata",
    [
        {"pagination": {"hasMore": True}},
        {"pagination": {"nextCursor": "omitted-page"}},
        {"partialFailure": True},
        {"warning": "partial_results"},
        {"meta": {"accountsFailed": 1}},
        {"meta": {"accountsSkipped": 1}},
        {"meta": {"failedAccounts": ["unavailable"]}},
    ],
)
def test_recovery_requires_a_complete_inbox_envelope(intake, configured, monkeypatch, metadata):
    event = missed_signed_event(intake, configured)
    original = onboarding_transport.provider.request

    def partial(credentials, spec, args, key=None):
        result = original(credentials, spec, args, key)
        return {**result, **metadata} if spec["path"].endswith("/messages") else result

    monkeypatch.setattr(onboarding_transport.provider, "request", partial)
    with connect() as db, pytest.raises(ValueError, match="welcome_recovery_history_incomplete"):
        onboarding.recover_unanswered(db, event["id"], actor_id=onboarding.settings(db)["owner_id"])
    assert state(intake[4]) == [] and intake[1] == []


def test_recovery_live_read_does_not_drop_fresh_public_enrollment(intake, configured, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    old = missed_signed_event(intake, configured)
    client, _, credentials = configured
    entered, release = Event(), Event()
    original = onboarding_transport.provider.request

    def delayed_live_read(credentials, spec, args, key=None):
        if spec["method"] == "GET" and args["path"]["conversationId"] == old["conversation"]["id"]:
            entered.set()
            assert release.wait(10)
        return original(credentials, spec, args, key)

    monkeypatch.setattr(onboarding_transport.provider, "request", delayed_live_read)
    with connect() as db:
        actor = onboarding.settings(db)["owner_id"]

    def recover():
        with connect() as db:
            return onboarding.recover_unanswered(db, old["id"], actor_id=actor)

    fresh = payload("573001110088")
    fresh["id"] = "fresh-concurrent"
    fresh["message"]["platformMessageId"] = "fresh-concurrent-message"
    fresh["message"]["text"] = "Hola"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(recover)
        assert entered.wait(3)
        try:
            response = send(client, credentials, fresh)
        finally:
            release.set()
        assert future.result(5)["state"] == "queued"
    assert response.status_code == 200
    with connect() as db:
        assert db.execute(
            "SELECT 1 FROM crm.social_webhook_events WHERE event_id=%s", (fresh["id"],)
        ).fetchone()
        assert db.execute(
            "SELECT 1 FROM crm.social_onboarding WHERE conversation_id=%s",
            (fresh["conversation"]["id"],),
        ).fetchone()


@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
def test_ambiguous_identity_never_blocks_welcome_or_creates_a_contact(intake, platform):
    incoming, deliveries, _, _, owner = intake
    incoming(
        platform, text="Full name: Mariana Torres Phone number: 3001110099 Phone number: 3001110088"
    )
    for _ in range(4):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "website", "group", "question"]
    row = state(owner)[0]
    assert row["contact_id"] is None and row["details"] == {}
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.contacts").fetchone()[0] == 0


def test_operator_recovers_proven_pre_send_blocked_row_without_replaying_a_receipt(
    intake, configured
):
    event = missed_signed_event(intake, configured)
    _, deliveries, _, _, owner = intake
    with connect() as db:
        actor = onboarding.settings(db)["owner_id"]
        onboarding.recover_unanswered(db, event["id"], actor_id=actor)
        db.execute("UPDATE crm.social_onboarding SET state='blocked',error='welcome_not_confirmed'")
    with connect() as db:
        assert onboarding.recover_unanswered(db, event["id"], actor_id=actor)["state"] == "queued"
    for _ in range(3):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["audio", "website", "group"]
    assert len(state(owner)) == 1
    with connect() as db:
        db.execute("UPDATE crm.social_onboarding SET state='blocked'")
    with connect() as db, pytest.raises(ValueError, match="recovery_existing_history"):
        onboarding.recover_unanswered(db, event["id"], actor_id=actor)
    assert len(deliveries) == 3


@pytest.fixture
def tiktok_intake(intake, configured, monkeypatch):
    from app.social import tiktok_intake as tiktok

    _incoming, deliveries, synthesis, events, owner = intake
    client = configured[0]
    original_account = onboarding_transport.service.account
    monkeypatch.setattr(
        onboarding_transport.service,
        "account",
        lambda c, a: {"platform": "tiktok"} if a == "tiktok-one" else original_account(c, a),
    )
    with connect() as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='tiktok'")
        cfg = onboarding.settings(db)
        credentials = onboarding.config.required()

    def incoming(text="Hola", suffix="dm", event_type="message.received"):
        event = payload("opaque-tiktok-user")
        event["id"] = "tiktok-event-" + suffix
        event["event"] = event_type
        event["account"].update(id="tiktok-one", platform="tiktok")
        event["conversation"].update(id="tiktok-thread", platform="tiktok")
        event["message"].update(
            platform="tiktok",
            conversationId="tiktok-thread",
            text=text,
            platformMessageId="tiktok-message-" + suffix,
        )
        event["message"]["sender"].pop("phoneNumber", None)
        event["message"]["sender"]["name"] = "Un Nombre Visible"
        events["tiktok-thread"] = event
        assert send(client, credentials, event).status_code == 200
        return event

    # Activate only after a signed DM has matching live Inbox evidence.
    proof = incoming(suffix="proof")
    with connect() as db:
        tiktok.configure(
            db,
            owner_id=cfg["owner_id"],
            profile_id=cfg["profile_id"],
            account_id="tiktok-one",
            proof_event_id=proof["id"],
        )
    return incoming, deliveries, synthesis, events, owner


def test_tiktok_dm_collects_identity_before_confirmation_and_links(tiktok_intake):
    from app.social import lead_notifications

    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming()
    onboarding.tick()
    row = state(owner)[0]
    assert [d[0] for d in deliveries] == ["introduction"]
    assert "Nombre completo:" in deliveries[0][1]["body"]["message"]
    assert row["details"] == {} and row["contact_id"] is None
    assert row["state"] == "waiting" and not synthesis
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM crm.contacts").fetchone()["n"] == 0
        # Exercise the already configured, two-recipient internal outbox.
        db.execute(
            "INSERT INTO crm.lead_notice_config(singleton,enabled,owner_id,profile_id,account_id,credential_revision,document_revision,activated_at,next_hour,next_daily,recipients) SELECT true,true,owner_id,profile_id,'notice-account',credential_revision,credential_revision,now(),now(),now(),%s FROM crm.tiktok_intake_config",
            (
                psycopg.types.json.Jsonb(
                    [
                        {"name": "Andrés", "phone": "+573001111001", "conversation_id": "dev-a"},
                        {"name": "Johan", "phone": "+573001111002", "conversation_id": "dev-b"},
                    ]
                ),
            ),
        )
    incoming("3001110099", suffix="phone")
    onboarding.tick()
    assert not synthesis and [d[0] for d in deliveries] == ["introduction", "question"]
    incoming("Nombre completo: Mariana Torres", suffix="name")
    for _ in range(3):
        onboarding.tick()
    row = state(owner)[0]
    assert [d[0] for d in deliveries] == [
        "introduction",
        "question",
        "confirmation",
        "website",
        "group",
    ]
    assert row["state"] == "completed" and row["contact_id"] and not synthesis
    assert row["audio_receipt"] == {}
    assert (
        row["introduction_receipt"]["status"] == row["confirmation_receipt"]["status"] == "accepted"
    )
    with connect() as db:
        contact = db.execute("SELECT * FROM crm.contacts").fetchone()
        assert contact["name"] == "Mariana Torres" and contact["phone"] == "+573001110099"
        assert lead_notifications.origin(db, contact["id"], contact["source"]) == "TikTok"
        assert (
            db.execute("SELECT count(*) AS n FROM crm.deals WHERE stage='new'").fetchone()["n"] == 1
        )
        assert (
            db.execute("SELECT count(*) AS n FROM crm.lead_notice_deliveries").fetchone()["n"] == 2
        )
    incoming("Nombre completo: Mariana Torres\nCelular: 3001110099", suffix="repeat")
    onboarding.tick()
    assert len(deliveries) == 5


@pytest.mark.parametrize("event_type", ["comment.received", "message.sent"])
def test_tiktok_comments_and_outgoing_do_not_start_intake(tiktok_intake, event_type):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming(event_type=event_type)
    onboarding.tick()
    assert state(owner) == [] and not deliveries and not synthesis


def test_tiktok_ambiguous_identity_does_not_confirm_or_link(tiktok_intake):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming("Nombre completo: Mariana Torres\nCelular: 3001110099\nCelular: 3001110088")
    onboarding.tick()
    assert state(owner)[0]["contact_id"] is None
    assert [d[0] for d in deliveries] == ["introduction"] and not synthesis
    incoming("Nombre completo: Mariana Torres\nCelular: 3001110099", suffix="corrected")
    for _ in range(3):
        onboarding.tick()
    assert [d[0] for d in deliveries] == ["introduction", "confirmation", "website", "group"]


def test_tiktok_uncertain_introduction_is_not_retried(tiktok_intake, monkeypatch):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming()
    original = onboarding_transport.provider.request

    def fail(c, op, args, key=None):
        if op["method"] == "POST":
            raise TimeoutError("fixture uncertainty")
        return original(c, op, args, key=key)

    monkeypatch.setattr(onboarding_transport.provider, "request", fail)
    onboarding.tick()
    assert state(owner)[0]["state"] == "unknown"
    onboarding.tick()
    assert state(owner)[0]["state"] == "unknown" and not deliveries and not synthesis


@pytest.mark.parametrize("reserved", [9, 10])
def test_tiktok_ten_reply_budget_is_durable(tiktok_intake, reserved):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming()
    row = state(owner)[0]
    with connect() as db:
        for index in range(reserved):
            db.execute(
                "INSERT INTO crm.tiktok_reply_reservations(onboarding_id,profile_id,account_id,participant_id,phase) VALUES(%s,%s,%s,%s,%s)",
                (
                    row["id"],
                    row["profile_id"],
                    row["account_id"],
                    row["participant_id"],
                    "probe-" + str(index),
                ),
            )
    onboarding.tick()
    assert len(deliveries) == (1 if reserved == 9 else 0)
    with connect() as db:
        assert (
            db.execute("SELECT count(*) AS n FROM crm.tiktok_reply_reservations").fetchone()["n"]
            == 10
        )
    assert not synthesis


@pytest.mark.parametrize("hours,allowed", [(47, True), (49, False)])
def test_tiktok_reply_window_is_48_hours_only(tiktok_intake, hours, allowed):
    from datetime import UTC, datetime, timedelta

    from psycopg.types.json import Jsonb

    incoming, deliveries, synthesis, events, _owner = tiktok_intake
    event = incoming()
    sent = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    event["message"]["sentAt"] = sent
    events["tiktok-thread"] = event
    with connect() as db:
        row = db.execute("SELECT * FROM crm.social_onboarding").fetchone()
        row["source"]["sent_at"] = sent
        db.execute(
            "UPDATE crm.social_onboarding SET source=%s WHERE id=%s",
            (Jsonb(row["source"]), row["id"]),
        )
    with connect() as db:
        if allowed:
            onboarding_transport.source(db, row)
        else:
            with pytest.raises(ValueError, match="welcome_source_unverified"):
                onboarding_transport.source(db, row)
    assert not deliveries and not synthesis


@pytest.mark.parametrize(
    "kind", ["partial", "other_reply", "outgoing_budget", "human_control", "stop"]
)
def test_tiktok_live_guards_prevent_sends(tiktok_intake, monkeypatch, kind):
    from datetime import UTC, datetime

    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming("STOP" if kind == "stop" else "Hola")
    original = onboarding_transport.provider.request

    def altered(c, op, args, key=None):
        result = original(c, op, args, key=key)
        if op["method"] == "GET" and op["path"].endswith("/messages"):
            if kind == "partial":
                result["pagination"] = {"hasMore": True}
            if kind in {"other_reply", "outgoing_budget"}:
                count = 10 if kind == "outgoing_budget" else 1
                # A pre-intake history spends quota without implying current human takeover.
                with connect() as db:
                    created = db.execute("SELECT created_at FROM crm.social_onboarding").fetchone()[
                        "created_at"
                    ]
                for n in range(count):
                    from datetime import timedelta

                    result["messages"].append(
                        {
                            "id": "external-" + str(n),
                            "conversationId": "tiktok-thread",
                            "accountId": "tiktok-one",
                            "platform": "tiktok",
                            "direction": "outgoing",
                            "createdAt": (
                                created - timedelta(seconds=1)
                                if kind == "outgoing_budget"
                                else datetime.now(UTC)
                            ).isoformat(),
                        }
                    )
        elif op["method"] == "GET" and kind == "human_control":
            result["data"]["threadControl"] = "human"
        return result

    monkeypatch.setattr(onboarding_transport.provider, "request", altered)
    onboarding.tick()
    assert not deliveries and not synthesis
    assert state(owner)[0]["state"] in {"blocked", "unknown", "pending"}


def test_tiktok_registration_is_saved_even_when_reply_quota_is_spent(tiktok_intake):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming("Nombre completo: Mariana Torres\nCelular: 3001110099")
    row = state(owner)[0]
    with connect() as db:
        for n in range(10):
            db.execute(
                "INSERT INTO crm.tiktok_reply_reservations(onboarding_id,profile_id,account_id,participant_id,phase) VALUES(%s,%s,%s,%s,%s)",
                (
                    row["id"],
                    row["profile_id"],
                    row["account_id"],
                    row["participant_id"],
                    "prior-" + str(n),
                ),
            )
    onboarding.tick()
    assert state(owner)[0]["contact_id"] and not deliveries and not synthesis


def test_tiktok_confirmation_cannot_bypass_registration_or_intro(tiktok_intake):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming()
    row = state(owner)[0]
    with connect() as db:
        db.execute(
            "UPDATE crm.social_onboarding SET state='confirmation_reserved' WHERE id=%s",
            (row["id"],),
        )
        db.execute(
            "INSERT INTO crm.tiktok_reply_reservations(onboarding_id,profile_id,account_id,participant_id,phase,source_message_id) VALUES(%s,%s,%s,%s,'confirmation',%s)",
            (
                row["id"],
                row["profile_id"],
                row["account_id"],
                row["participant_id"],
                row["source"]["message_id"],
            ),
        )
    with pytest.raises(ValueError, match="introduction_required"):
        onboarding_transport.execute("welcome_confirmation", str(row["id"]))
    with connect() as db:
        db.execute(
            "UPDATE crm.social_onboarding SET introduction_receipt=%s WHERE id=%s",
            (psycopg.types.json.Jsonb({"status": "accepted", "message_id": "intro"}), row["id"]),
        )
    with pytest.raises(ValueError, match="registration_required"):
        onboarding_transport.execute("welcome_confirmation", str(row["id"]))
    assert not deliveries and not synthesis


def test_tiktok_quota_reservation_is_serialized(tiktok_intake):
    from concurrent.futures import ThreadPoolExecutor

    from app.social import tiktok_intake as tiktok

    incoming, _deliveries, _synthesis, _events, owner = tiktok_intake
    incoming()
    row = state(owner)[0]
    with connect() as db:
        for n in range(9):
            db.execute(
                "INSERT INTO crm.tiktok_reply_reservations(onboarding_id,profile_id,account_id,participant_id,phase) VALUES(%s,%s,%s,%s,%s)",
                (
                    row["id"],
                    row["profile_id"],
                    row["account_id"],
                    row["participant_id"],
                    "prior-" + str(n),
                ),
            )

    def attempt(step):
        try:
            with connect() as db:
                tiktok.reserve(db, row, step)
            return True
        except ValueError as exc:
            assert str(exc) == "welcome_tiktok_reply_budget"
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["probe-one", "probe-two"]))
    assert sorted(results) == [False, True]


def test_tiktok_activation_and_normalization_do_not_enable_generic_workflows(tiktok_intake):
    from app.social import workflow

    incoming, _deliveries, _synthesis, _events, _owner = tiktok_intake
    event = incoming()
    assert workflow.normalize_event(event) is None
    assert onboarding.normalize(event, "a" * 24)["platform"] == "tiktok"
    with connect() as db:
        assert set(onboarding.settings(db)["accounts"].values()) == {"whatsapp", "facebook"}
        assert onboarding.settings(db, "tiktok")["accounts"] == {"tiktok-one": "tiktok"}


def test_tiktok_disabled_config_and_fair_expiry_stop_sends(tiktok_intake, monkeypatch):
    from datetime import UTC, datetime, timedelta

    incoming, deliveries, synthesis, _events, _owner = tiktok_intake
    incoming()
    with connect() as db:
        db.execute("UPDATE crm.tiktok_intake_config SET enabled=false")
    onboarding.tick()
    assert not deliveries and not synthesis
    with connect() as db:
        db.execute("UPDATE crm.tiktok_intake_config SET enabled=true")
    monkeypatch.setattr(onboarding, "WELCOME_UNTIL", datetime.now(UTC) - timedelta(seconds=1))
    onboarding.tick()
    assert not deliveries and not synthesis


def test_tiktok_interest_text_is_not_a_self_declared_name(tiktok_intake):
    incoming, deliveries, synthesis, _events, owner = tiktok_intake
    incoming()
    onboarding.tick()
    incoming("3001110099", suffix="phone")
    onboarding.tick()
    incoming("Me interesa el proyecto", suffix="interest")
    onboarding.tick()
    row = state(owner)[0]
    assert row["details"] == {"phone": "+573001110099"}
    assert row["contact_id"] is None
    with connect() as db:
        assert db.execute("SELECT count(*) AS n FROM crm.contacts").fetchone()["n"] == 0
        assert (
            db.execute("SELECT count(*) AS n FROM crm.lead_notice_deliveries").fetchone()["n"] == 0
        )
    assert [d[0] for d in deliveries] == ["introduction", "question", "question"]
    assert len({d[2] for d in deliveries}) == 3
    assert not synthesis
    incoming("Nombre completo: Mariana Torres", suffix="self-identified")
    for _ in range(3):
        onboarding.tick()
    assert state(owner)[0]["contact_id"]
    assert [d[0] for d in deliveries][-3:] == ["confirmation", "website", "group"]
