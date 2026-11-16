"""Internal notifications never use a lead's phone as an outbound recipient."""

# ruff: noqa: F811
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb
from test_crm import authenticated  # noqa: F401

from app.crm.database import connect
from app.social import lead_notifications as notices

TIME = datetime(2026, 11, 16, 16, 30, tzinfo=UTC)
DOCUMENT = {
    "account_id": "account",
    "phone": "+573211111111",
    "developers": [
        {"name": "Johan", "phone": "+573001111111"},
        {"name": "Andrés", "phone": "+573002222222"},
    ],
    "instructions": "",
    "knowledge": "",
}


@pytest.fixture
def configured(authenticated, monkeypatch):
    session, _, _ = authenticated
    monkeypatch.setattr(notices, "now", lambda: TIME)
    monkeypatch.setattr(
        notices.config, "required", lambda: {"profile_id": "profile", "api_key": "fixture"}
    )
    monkeypatch.setattr(notices.config, "locked", nullcontext)
    monkeypatch.setattr(notices, "verify_account", lambda *a: None)
    monkeypatch.setattr(
        notices,
        "resolve_recipients",
        lambda c, d: [
            {**r, "conversation_id": "thread-" + str(i)} for i, r in enumerate(d["developers"])
        ],
    )
    monkeypatch.setattr(notices.control, "require_connections", lambda *a: None)
    with connect() as db:
        actor = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()
        db.execute(
            "INSERT INTO crm.whatsapp_agent(singleton,version,enabled,document) VALUES(true,1,true,%s)",
            (Jsonb(DOCUMENT),),
        )
        notices.configure(db, actor["id"])
    return session


def insert(phone="+573009999991", source="whatsapp"):
    with connect() as db:
        return db.execute(
            "INSERT INTO crm.contacts(name,phone,source) VALUES('Ana Prueba',%s,%s) ON CONFLICT(phone) DO NOTHING RETURNING id",
            (phone, source),
        ).fetchone()


def deliveries():
    with connect() as db:
        return db.execute(
            "SELECT * FROM crm.lead_notice_deliveries ORDER BY recipient_phone"
        ).fetchall()


def test_new_lead_outbox_is_atomic_and_deduplicated(configured):
    insert()
    insert()
    assert len(deliveries()) == 2
    assert {r["recipient_phone"] for r in deliveries()} == {
        r["phone"] for r in DOCUMENT["developers"]
    }
    with pytest.raises(RuntimeError), connect() as db:
        db.execute(
            "INSERT INTO crm.contacts(name,phone,source) VALUES('Rollback','+573009999992','web')"
        )
        raise RuntimeError("rollback")
    assert len(deliveries()) == 2


def test_no_historical_replay_and_no_notifications_when_disabled(configured):
    with connect() as db:
        db.execute("UPDATE crm.lead_notice_config SET enabled=false")
    insert()
    assert deliveries() == []
    with connect() as db:
        owner = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()
        notices.configure(db, owner["id"])
    assert deliveries() == []


def test_hourly_and_daily_are_bogota_clock_aligned_and_idempotent(configured):
    with connect() as db:
        notices.schedule(db, TIME + timedelta(minutes=29))
    assert deliveries() == []
    for _ in range(2):
        with connect() as db:
            notices.schedule(db, TIME + timedelta(minutes=30))  # 12:00 Bogotá
    assert len(deliveries()) == 2
    with connect() as db:
        notices.schedule(db, datetime(2026, 11, 17, 3, tzinfo=UTC))  # 22:00 Bogotá
    rows = deliveries()
    assert len(rows) == 4  # Daily replaces the simultaneous 22:00 hourly notice.
    with connect() as db:
        events = db.execute("SELECT kind FROM crm.lead_notice_events").fetchall()
    assert sorted(r["kind"] for r in events) == ["daily", "hourly"]


def test_origin_counts_do_not_label_every_campaign_as_facebook(configured):
    a = insert(source="social_campaign")
    insert("+573009999993", "web")
    with connect() as db:
        assert notices.origin(db, a["id"], "social_campaign") == "Otros / sin confirmar"
        snapshot = notices.counts(db, datetime(2030, 1, 1, tzinfo=UTC))
    assert snapshot["total"] == 2 and snapshot["whatsapp"] == snapshot["facebook"] == 0
    with connect() as db:
        db.execute(
            """INSERT INTO crm.lead_capture_threads(profile_id,account_id,conversation_id,
          platform,participant_id,observed_marker,status,contact_id)
          VALUES('profile','facebook','fb-thread','facebook','opaque',%s,'registered',%s)""",
            ("a" * 64, a["id"]),
        )
        assert notices.origin(db, a["id"], "social_campaign") == "Facebook"
        snapshot = notices.counts(db, datetime(2030, 1, 1, tzinfo=UTC))
        assert snapshot["facebook"] == 1 and snapshot["other"] == 1


def test_per_recipient_receipt_and_uncertain_write_are_never_resent(configured, monkeypatch):
    insert()
    calls = []
    monkeypatch.setattr(
        notices,
        "prepare",
        lambda c, row, event: ("reply", {"message": "notice"}, row["conversation_id"]),
    )

    def send(c, op, payload, thread, key):
        calls.append(key)
        if len(calls) == 2:
            raise TimeoutError
        return {"data": {"id": "message", "conversationId": thread}}

    monkeypatch.setattr(notices, "send", send)
    notices.tick()
    notices.tick()
    assert len(calls) == 2
    assert {r["state"] for r in deliveries()} == {"accepted", "unknown"}


def test_revoked_recipient_configuration_cancels_without_dispatch(configured, monkeypatch):
    insert()
    with connect() as db:
        db.execute("UPDATE crm.whatsapp_agent SET enabled=false")
    monkeypatch.setattr(notices, "send", lambda *a: pytest.fail("must not send"))
    notices.tick()
    assert {r["state"] for r in deliveries()} == {"cancelled"}


def test_closed_window_waits_for_exact_approved_template(monkeypatch):
    monkeypatch.setattr(
        notices.workflow,
        "_window",
        lambda *a: (_ for _ in ()).throw(notices.HTTPException(409, "zernio_window_unconfirmed")),
    )
    monkeypatch.setattr(
        notices, "read_thread", lambda *a: {"id": "thread", "participantId": "573001111111"}
    )
    monkeypatch.setattr(notices.workflow, "_templates", lambda *a: [])
    row = {"account_id": "account", "recipient_phone": "+573001111111", "conversation_id": "thread"}
    event = {
        "kind": "lead",
        "payload": {"name": "Ana", "phone": "+573009999999", "origin": "WhatsApp"},
    }
    with pytest.raises(notices.HTTPException, match="notice_template_pending"):
        notices.prepare({}, row, event)


def test_exact_approved_template_preserves_fixed_internal_recipient(monkeypatch):
    monkeypatch.setattr(notices, "read_thread", lambda *a: None)
    template = {
        "id": "template",
        "name": notices.LEAD_TEMPLATE,
        "language": "es_CO",
        "status": "APPROVED",
        "components": [{"type": "BODY", "text": notices.LEAD_BODY}],
    }
    monkeypatch.setattr(notices.workflow, "_templates", lambda *a: [template])
    row = {"account_id": "account", "recipient_phone": "+573001111111", "conversation_id": None}
    event = {
        "kind": "lead",
        "payload": {"name": "Ana", "phone": "+573009999999", "origin": "Facebook"},
    }
    operation, payload, thread = notices.prepare({}, row, event)
    assert operation == "open" and thread is None
    assert payload["participantId"] == "573001111111"
    assert payload["templateParams"] == ["Ana", "+573009999999", "Facebook"]
    template["components"][0]["text"] = "Changed {{1}} {{2}} {{3}}"
    with pytest.raises(notices.HTTPException, match="notice_template_changed"):
        notices.prepare({}, row, event)


@pytest.mark.parametrize("extra_type", ["HEADER", "FOOTER"])
def test_template_rejects_extra_static_content(monkeypatch, extra_type):
    monkeypatch.setattr(notices, "read_thread", lambda *a: None)
    template = {
        "id": "template",
        "name": notices.LEAD_TEMPLATE,
        "language": "es_CO",
        "status": "APPROVED",
        "components": [
            {"type": "BODY", "text": notices.LEAD_BODY},
            {"type": extra_type, "text": "Unauthorized content"},
        ],
    }
    monkeypatch.setattr(notices.workflow, "_templates", lambda *a: [template])
    with pytest.raises(notices.HTTPException, match="notice_template_changed"):
        notices.prepare(
            {},
            {"account_id": "account", "recipient_phone": "+573001111111", "conversation_id": None},
            {
                "kind": "lead",
                "payload": {"name": "Ana", "phone": "+573009999999", "origin": "WhatsApp"},
            },
        )


def test_initially_absent_thread_is_rediscovered_before_next_dispatch(monkeypatch):
    row = {"conversation_id": None, "account_id": "account", "recipient_phone": "+573001111111"}
    monkeypatch.setattr(notices, "_matching_threads", lambda *a: {row["recipient_phone"]: set()})
    assert notices.read_thread({}, row) is None
    # A first approved template or a later incoming message can establish this thread.
    monkeypatch.setattr(
        notices, "_matching_threads", lambda *a: {row["recipient_phone"]: {"new-thread"}}
    )
    thread = {
        "id": "new-thread",
        "accountId": "account",
        "platform": "whatsapp",
        "participantId": "573001111111",
        "threadControl": "human",
    }
    monkeypatch.setattr(notices.lead_capture_worker, "read", lambda *a, **kw: {"data": thread})
    with pytest.raises(notices.HTTPException):
        notices.read_thread({}, row)
    thread["threadControl"] = "app"
    assert notices.read_thread({}, row)["id"] == "new-thread"


def test_all_contact_creation_helpers_share_the_same_trigger(configured):
    from app.crm import services
    from app.crm.models import ContactInput

    with connect() as db:
        actor = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()
        services.create_contact(
            db, ContactInput(name="Manual", phone="+573009999991", source="other"), actor
        )
        data = ContactInput(name="Captured", phone="+573009999992", source="web")
        services.capture_contact(db, data)
        services.capture_contact(db, data)
    assert len(deliveries()) == 4


def test_changed_credentials_cancel_without_provider_write(configured, monkeypatch):
    insert()
    monkeypatch.setattr(
        notices.config, "required", lambda: {"profile_id": "profile", "api_key": "rotated"}
    )
    monkeypatch.setattr(notices, "send", lambda *a: pytest.fail("revoked"))
    notices.tick()
    assert {r["state"] for r in deliveries()} == {"cancelled"}


def test_pre_dispatch_read_failure_retries_but_reserved_crash_does_not(configured, monkeypatch):
    insert()
    monkeypatch.setattr(
        notices, "prepare", lambda *a: (_ for _ in ()).throw(ValueError("read failed"))
    )
    monkeypatch.setattr(notices, "send", lambda *a: pytest.fail("not prepared"))
    notices.tick()
    assert {r["state"] for r in deliveries()} == {"pending"}
    with connect() as db:
        db.execute("UPDATE crm.lead_notice_deliveries SET state='reserved',reserved_at=now()")
    notices.tick()
    assert {r["state"] for r in deliveries()} == {"unknown"}


def test_restart_only_catches_latest_hour_and_last_daily_close(configured):
    future = TIME + timedelta(days=5, hours=1)
    for _ in range(2):
        with connect() as db:
            notices.schedule(db, future)
    assert len(deliveries()) == 4


def test_routing_rejects_a_customer_conversation(monkeypatch):
    monkeypatch.setattr(
        notices.lead_capture_worker,
        "read",
        lambda *a, **kw: {
            "data": {
                "id": "customer-thread",
                "accountId": "account",
                "platform": "whatsapp",
                "participantId": "573009999999",
            }
        },
    )
    with pytest.raises(notices.HTTPException, match="notice_recipient_scope"):
        notices.read_thread(
            {},
            {
                "conversation_id": "customer-thread",
                "account_id": "account",
                "recipient_phone": "+573001111111",
            },
        )


def test_report_copy_contains_all_time_today_and_channel_breakdown():
    data = {
        "total": 20,
        "whatsapp": 7,
        "facebook": 8,
        "other": 5,
        "today": 4,
        "today_whatsapp": 2,
        "today_facebook": 1,
        "today_other": 1,
        "hour": 3,
    }
    event = {"kind": "daily", "payload": data, "cutoff": datetime(2026, 11, 17, 3, tzinfo=UTC)}
    body, params = notices.content(event)
    assert "22:00" in body and "Cierre" in body and "20" in body
    assert "WhatsApp: 7" in body and "Facebook: 8" in body and "sin confirmar: 5" in body
    assert len(params) == 6
