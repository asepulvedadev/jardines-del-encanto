"""Deterministic intake: only verified inbound data can create a CRM lead."""

# ruff: noqa: F811
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_crm import authenticated  # noqa: F401

from app.crm.database import connect
from app.social import lead_capture as capture

WA = "a" * 24
FB = "b" * 24
PROFILE = "c" * 24
FORM = "Full name: Ana Prueba\nPhone number: 3001234567\nCity: Bogotá\n¿En qué horario asistirás a la feria inmobiliaria este 22 de Noviembre?: Mañana"


def conversation(account=WA, platform="whatsapp", participant="573001234567"):
    return {
        "id": "thread-1",
        "accountId": account,
        "platform": platform,
        "participantId": participant,
        "participantName": "Ana",
        "lastMessageAt": "2026-11-16T12:00:00Z",
    }


def message(text=FORM, **changes):
    return {
        "id": "m1",
        "conversationId": "thread-1",
        "accountId": WA,
        "platform": "whatsapp",
        "senderId": "573001234567",
        "direction": "incoming",
        "message": text,
        **changes,
    }


@pytest.fixture
def intake(authenticated, monkeypatch):
    session, owner, _ = authenticated
    monkeypatch.setattr(capture, "ACCOUNTS", {WA: "whatsapp", FB: "facebook"})
    monkeypatch.setenv("CRM_LEAD_CAPTURE_ENABLED", "1")
    monkeypatch.setenv("CRM_LEAD_CAPTURE_ACTOR", "testadmin")
    monkeypatch.setattr(
        capture.config,
        "required",
        lambda: {
            "profile_id": PROFILE,
            "api_key": "fixture",
            "webhook_secret": "fixture-signing-key",
        },
    )
    monkeypatch.setattr(capture, "require_connections", lambda *args: None)
    monkeypatch.setattr(capture.config, "load", capture.config.required)
    return session, owner


def apply(row, rows, profile=PROFILE):
    with connect() as db:
        return capture.ingest(db, profile, row, rows, complete=True)


def test_form_precedence_and_inert_text():
    candidate = capture.extract(
        conversation(participant="CO.1234567890123456"), [message(senderId="CO.1234567890123456")]
    )
    assert candidate["name"] == "Ana Prueba"
    assert candidate["phone"] == "+573001234567"
    assert capture.extract(conversation(), [message(direction="outgoing")])["phone"] is None
    assert capture.extract(conversation(), [message(senderId="other")])["phone"] is None
    assert capture.extract(conversation(), [message(accountId="other")])["phone"] is None


def test_messenger_ids_are_never_phones_and_partial_history_has_no_fallback():
    row = conversation(FB, "facebook", "573001234567")
    incoming = message("Hola, Jardines del Encanto", accountId=FB, platform="facebook")
    assert capture.extract(row, [incoming])["phone"] is None
    assert capture.extract(conversation(), [message("Hola")], complete=False)["phone"] is None
    assert capture.extract(conversation(), [message("Hola")])["phone"] == "+573001234567"


def test_invalid_explicit_phone_never_falls_back_to_sender():
    result = capture.extract(
        conversation(), [message("Full name: Ana\nPhone number: CO.123456789")]
    )
    assert result["phone"] is None
    assert result["reason"] == "missing_phone"


def test_new_contact_and_concurrent_replays_are_atomic(intake):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: apply(conversation(), [message()]), range(4)))
    state = intake[0].get("/crm/workspace").json()
    assert len(state["contacts"]) == len(state["deals"]) == 1
    assert state["contacts"][0]["name"] == "Ana Prueba"
    assert state["deals"][0]["stage"] == "new"
    assert len(state["activities"]) == 1


def test_existing_contact_and_won_deal_are_preserved(intake):
    session, _ = intake
    person = session.post(
        "/crm/contacts", json={"name": "Nombre confirmado", "phone": "3001234567", "source": "web"}
    ).json()
    state = session.get("/crm/workspace").json()
    deal = state["deals"][0]
    assert (
        session.patch(
            "/crm/deals/" + deal["id"], json={"stage": "won", "version": deal["version"]}
        ).status_code
        == 200
    )
    apply(conversation(), [message()])
    state = session.get("/crm/workspace").json()
    assert {key: state["contacts"][0][key] for key in person} == person
    assert state["deals"][0]["stage"] == "won"
    assert len(state["activities"]) == 2


def test_missing_identity_is_durable_and_later_completed(intake):
    row = conversation(participant="CO.1234567890123456")
    apply(row, [message("Hola", senderId=row["participantId"])])
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 0
    with connect() as db:
        pending = db.execute("SELECT * FROM crm.lead_capture_threads").fetchone()
        assert pending["reason"] == "missing_phone" and pending["contact_id"] is None
    apply(row, [message(senderId=row["participantId"])])
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 1


def test_shared_facebook_scope_and_excluded_accounts(intake):
    row = conversation(FB, "facebook", "user-1")
    incoming = message(accountId=FB, platform="facebook", senderId="user-1")
    assert apply(row, [incoming])["status"] == "registered"
    for bad in [conversation("other"), {**row, "platform": "whatsapp"}]:
        assert apply(bad, [message()]) is None
    unrelated = {**row, "id": "casanova"}
    result = apply(
        unrelated,
        [
            {
                **incoming,
                "conversationId": "casanova",
                "message": "Casanova Campestre\nFull name: Otro\nPhone number: 3011234567",
            }
        ],
    )
    assert result["status"] == "out_of_scope"
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 1


def test_poll_is_get_only_scoped_durable_and_resumes_pages(intake, monkeypatch):
    calls = []
    accounts = [{"id": WA, "platform": "whatsapp", "active": True}]
    monkeypatch.setattr(capture.inbox_service, "accounts", lambda _: accounts)

    def vendor(credentials, operation, args):
        calls.append((operation["method"], deepcopy(args), operation["path"]))
        if operation["path"] == "/v1/inbox/conversations":
            return {"data": [conversation()], "pagination": {"hasMore": False}}
        return {"messages": [message()], "pagination": {"hasMore": False}}

    monkeypatch.setattr(capture.inbox_provider, "request", vendor)
    capture.tick()
    capture.tick()
    assert calls and all(method == "GET" for method, _, _ in calls)
    assert all(args["query"]["accountId"] == WA for _, args, _ in calls)
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 1
    assert all(
        path in {"/v1/inbox/conversations", "/v1/inbox/conversations/{conversationId}/messages"}
        for _, _, path in calls
    )


def test_status_is_private_and_contains_no_contact_data(intake):
    apply(conversation(), [message()])
    result = intake[0].get("/crm/inbox/lead-capture")
    assert result.status_code == 200
    assert result.json()["registered"] == 1
    assert "Ana" not in result.text and "3001234567" not in result.text
    intake[0].cookies.clear()
    assert intake[0].get("/crm/inbox/lead-capture").status_code == 401


@pytest.mark.parametrize("failure", ["agent", "onboarding"])
def test_signed_webhook_saves_even_when_reply_agent_fails(intake, monkeypatch, failure):
    from app.social import onboarding, whatsapp_agent

    def fail(db, *args):
        db.execute("SELECT 1/0")

    monkeypatch.setattr(onboarding if failure == "onboarding" else whatsapp_agent, "enqueue", fail)
    payload = {
        "id": "capture-event-" + uuid4().hex,
        "event": "message.received",
        "account": {"accountId": WA, "profileId": PROFILE, "platform": "whatsapp"},
        "conversation": {
            "id": "internal-1",
            "platformConversationId": "thread-1",
            "participantId": "573001234567",
        },
        "message": {
            "id": "internal-m1",
            "platformMessageId": "wamid.1",
            "platform": "whatsapp",
            "conversationId": "internal-1",
            "direction": "incoming",
            "sender": {"id": "573001234567", "name": "Ana"},
            "text": FORM,
            "sentAt": datetime.now(UTC).isoformat(),
        },
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(b"fixture-signing-key", raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Zernio-Signature": signature,
        "X-Zernio-Event-Id": payload["id"],
        "X-Zernio-Event": payload["event"],
    }
    for _ in range(2):
        result = intake[0].post("/integrations/zernio/webhook", content=raw, headers=headers)
        assert result.status_code == 200
    state = intake[0].get("/crm/workspace").json()
    assert state["counts"]["contacts"] == 1 and len(state["activities"]) == 1
    with connect() as db:
        assert db.execute(
            "SELECT 1 FROM crm.social_webhook_events WHERE event_id=%s", (payload["id"],)
        ).fetchone()
        assert (
            db.execute("SELECT conversation_id FROM crm.lead_capture_threads").fetchone()[
                "conversation_id"
            ]
            == payload["conversation"]["id"]
        )
    raw = raw.replace(payload["id"].encode(), b"capture-event-unsigned")
    assert (
        intake[0].post("/integrations/zernio/webhook", content=raw, headers=headers).status_code
        == 401
    )


def test_unknown_facebook_project_is_pending_not_a_fake_contact(intake):
    row = conversation(FB, "facebook", "573001234567")
    result = apply(row, [message("Hola", accountId=FB, platform="facebook")])
    assert result == {"status": "pending", "reason": "project_unconfirmed"}
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 0
    assert apply(conversation(), [message()], profile="other-profile") is None


def test_cursor_and_partial_response_fail_closed():
    from app.social.lead_capture_worker import page

    for data in [
        {"data": [], "pagination": {"hasMore": True}},
        {"data": [], "pagination": {"hasMore": True, "nextCursor": "same"}},
        {"data": [], "meta": {"accountsFailed": 1}},
    ]:
        with pytest.raises(ValueError):
            page(data, "data", previous="same")


def test_explicit_casanova_fair_does_not_match_jardines(intake):
    row = conversation(FB, "facebook", "user-1")
    result = apply(
        row,
        [
            message(
                "Casanova Campestre\n" + FORM, accountId=FB, platform="facebook", senderId="user-1"
            )
        ],
    )
    assert result == {"status": "out_of_scope", "reason": "other_project"}
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 0
    with connect() as db:
        result = capture.ingest(
            db,
            PROFILE,
            row,
            [
                message(
                    "Casanova Campestre\n" + FORM,
                    accountId=FB,
                    platform="facebook",
                    senderId="user-1",
                )
            ],
            complete=False,
            cursor="older-project",
        )
        saved = db.execute("SELECT * FROM crm.lead_capture_threads").fetchone()
        assert result["status"] == "out_of_scope"
        assert saved["scan_cursor"] is None and saved["checked_marker"] == saved["observed_marker"]


@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
def test_identity_survives_history_pages_until_project_evidence_completes(intake, platform):
    aid = WA if platform == "whatsapp" else FB
    row = conversation(aid, platform)
    first = message(
        "Hola" if platform == "whatsapp" else "Full name: Ana Prueba\nPhone number: 3001234567",
        accountId=aid,
        platform=platform,
    )
    with connect() as db:
        result = capture.ingest(db, PROFILE, row, [first], complete=False, cursor="older")
        assert result["status"] == "pending"
    with connect() as db:
        middle = {**first, "direction": "outgoing", "message": "Mensaje anterior"}
        result = capture.ingest(
            db,
            PROFILE,
            row,
            [middle],
            complete=False,
            cursor="oldest",
            expected_marker=capture.marker(row),
        )
        assert result["status"] == "pending"
    last = message(
        "Información anterior" if platform == "whatsapp" else "Me interesa Jardines del Encanto",
        accountId=aid,
        platform=platform,
        direction="outgoing" if platform == "whatsapp" else "incoming",
    )
    with connect() as db:
        result = capture.ingest(
            db, PROFILE, row, [last], complete=True, expected_marker=capture.marker(row)
        )
        assert result["status"] == "registered"
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 1


def test_poll_cursor_survives_failure_and_restart(intake, monkeypatch):
    monkeypatch.setattr(
        capture.inbox_service,
        "accounts",
        lambda _: [{"id": WA, "platform": "whatsapp", "active": True}],
    )
    seen = []
    failed = False

    def vendor(credentials, operation, args):
        nonlocal failed
        if operation["path"] == "/v1/inbox/conversations":
            cursor = args["query"].get("cursor")
            seen.append((args["query"]["status"], cursor))
            if args["query"]["status"] == "active" and not cursor:
                return {
                    "data": [conversation()],
                    "pagination": {"hasMore": True, "nextCursor": "page-2"},
                }
            return {"data": [], "pagination": {"hasMore": False}}
        if not failed:
            failed = True
            raise ValueError("fixture provider unavailable")
        return {"messages": [message()], "pagination": {"hasMore": False}}

    monkeypatch.setattr(capture.inbox_provider, "request", vendor)
    capture.tick()
    with connect() as db:
        record = db.execute("SELECT reason,checked_marker FROM crm.lead_capture_threads").fetchone()
        assert record["reason"] == "capture_read_failed" and record["checked_marker"] is None
        db.execute("UPDATE crm.lead_capture_threads SET next_attempt=now()")
    capture.tick()
    assert ("active", "page-2") in seen
    assert intake[0].get("/crm/workspace").json()["counts"]["contacts"] == 1
