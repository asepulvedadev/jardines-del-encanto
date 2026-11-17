"""Native broadcast attribution is read-only and requires a verified later reply."""

# ruff: noqa: F811

from copy import deepcopy
from datetime import UTC, datetime

from test_crm import authenticated  # noqa: F401
from test_lead_capture import PROFILE, WA, apply, conversation, intake, message  # noqa: F401

from app.crm.database import connect
from app.social import template_cohorts as cohorts

SENT = datetime(2026, 11, 17, 12, tzinfo=UTC)


def test_reply_requires_matching_incoming_after_send():
    row = conversation()
    incoming = message(createdAt="2026-11-17T12:01:00Z")
    assert cohorts.reply_at(row, [incoming], SENT) == datetime(2026, 11, 17, 12, 1, tzinfo=UTC)
    for changes in (
        {"direction": "outgoing"},
        {"accountId": "other"},
        {"senderId": "other"},
        {"conversationId": "other"},
        {"platform": "facebook"},
        {"isDeleted": True},
        {"createdAt": "2026-11-17T11:59:00Z"},
        {"createdAt": "bad"},
        {"createdAt": "2026-11-17T12:00:00"},
    ):
        assert cohorts.reply_at(row, [{**incoming, **changes}], SENT) is None


def test_native_campaign_is_exact_and_read_only(monkeypatch):
    calls = []
    native = {
        "id": "d" * 24,
        "name": cohorts.NATIVE_NAME,
        "accountId": WA,
        "platform": "whatsapp",
        "status": "completed",
        "recipientCount": 1,
        "template": {"name": cohorts.TEMPLATE, "language": "es"},
        "segmentFilters": {"tags": [cohorts.NATIVE_TAG]},
        "startedAt": SENT.isoformat(),
    }
    monkeypatch.setattr(cohorts, "ACCOUNT", WA)

    def request(credentials, method, path):
        calls.append((method, path))
        assert method == "GET"
        if path == "/v1/broadcasts":
            return {"broadcasts": [native], "pagination": {"hasMore": False}}
        return {"broadcast": native}

    monkeypatch.setattr(cohorts.provider, "request", request)
    assert cohorts.discover({"profile_id": PROFILE})[0]["id"] == native["id"]
    native["accountId"] = "other"
    assert cohorts.discover({"profile_id": PROFILE}) == []
    assert all(method == "GET" for method, _ in calls)


def seed_native(db, contact_id):
    db.execute(
        """INSERT INTO crm.template_lead_attribution
        (profile_id,account_id,broadcast_id,contact_id,conversation_id,participant_id,
         label,template_name,sent_at,reply_at,state)
        VALUES(%s,%s,%s,%s,'thread-1','573001234567',%s,%s,%s,%s,'matched')""",
        (
            PROFILE,
            WA,
            "d" * 24,
            contact_id,
            "Templates · Base 1",
            cohorts.TEMPLATE,
            SENT,
            datetime(2026, 11, 17, 12, 1, tzinfo=UTC),
        ),
    )


def test_dashboard_cohorts_are_disjoint_and_filters_keep_existing_identity(intake):
    client, _ = intake
    record = client.post(
        "/crm/contacts",
        json={
            "name": "Ana Original",
            "phone": "3001234567",
            "source": "social_campaign",
        },
    ).json()
    with connect() as db:
        before = db.execute("SELECT * FROM crm.contacts WHERE id=%s", (record["id"],)).fetchone()
        seed_native(db, record["id"])
        db.execute("UPDATE crm.deals SET stage='won' WHERE contact_id=%s", (record["id"],))
    data = client.get("/crm/workspace").json()
    assert data["counts"]["contacts"] == 1
    assert data["counts"]["template_leads"] == 1
    assert data["counts"]["campaign_leads"] == 0
    assert data["contacts"][0]["template_tags"] == ["Templates · Base 1"]
    assert data["contacts"][0]["source"] == "social_campaign"
    assert data["deals"][0]["stage"] == "won"
    selected = client.post("/crm/broadcasts/filter", json={"cohort": "template"}).json()
    assert [c["id"] for c in selected["contacts"]] == [record["id"]]
    assert (
        client.post("/crm/broadcasts/filter", json={"cohort": "campaign"}).json()["contacts"] == []
    )
    assert client.post("/crm/broadcasts/filter", json={"cohort": "invalid"}).status_code == 422
    with connect() as db:
        assert (
            db.execute("SELECT * FROM crm.contacts WHERE id=%s", (record["id"],)).fetchone()
            == before
        )


def test_reconciliation_requires_send_receipt_and_later_inbound(intake, monkeypatch):
    client, _ = intake
    apply(conversation(), [message()])
    monkeypatch.setattr(cohorts, "ACCOUNT", WA)
    calls = []
    native = {
        "id": "d" * 24,
        "name": cohorts.NATIVE_NAME,
        "accountId": WA,
        "platform": "whatsapp",
        "status": "completed",
        "recipientCount": 1,
        "template": {"name": cohorts.TEMPLATE, "language": "es"},
        "segmentFilters": {"tags": [cohorts.NATIVE_TAG]},
        "startedAt": SENT.isoformat(),
    }
    recipient = {
        "platformIdentifier": "573001234567",
        "status": "delivered",
        "sentAt": SENT.isoformat(),
        "messageId": "wamid.fixture",
    }

    def request(credentials, method, path):
        calls.append((method, path))
        assert method == "GET"
        if path == "/v1/broadcasts":
            return {"broadcasts": [native], "pagination": {"hasMore": False}}
        if "/recipients?" in path:
            return {"recipients": [recipient], "pagination": {"total": 1, "hasMore": False}}
        return {"broadcast": native}

    monkeypatch.setattr(cohorts.provider, "request", request)
    monkeypatch.setattr(
        cohorts.capture.inbox_service,
        "account",
        lambda *args: {"platform": "whatsapp", "active": True},
    )
    rows = [message(createdAt="2026-11-17T11:59:00Z")]

    def read(credentials, account, operation, query=None, path=None):
        if operation == "getInboxConversation":
            return {"data": conversation()}
        return {"messages": deepcopy(rows), "pagination": {"hasMore": False}}

    monkeypatch.setattr(cohorts, "read", read)
    cohorts.tick()
    assert client.get("/crm/workspace").json()["counts"]["template_leads"] == 0
    rows[0]["createdAt"] = "2026-11-17T12:01:00Z"
    with connect() as db:
        db.execute("UPDATE crm.template_lead_attribution SET next_attempt=now()")
    cohorts.tick()
    cohorts.tick()
    data = client.get("/crm/workspace").json()
    assert data["counts"]["template_leads"] == 1
    assert data["counts"]["contacts"] == 1
    assert all(method == "GET" for method, _ in calls)


def test_changed_phone_does_not_inherit_template_provenance(intake):
    client, _ = intake
    record = client.post(
        "/crm/contacts",
        json={
            "name": "Ana Original",
            "phone": "3001234567",
            "source": "social_campaign",
        },
    ).json()
    with connect() as db:
        seed_native(db, record["id"])
        db.execute("UPDATE crm.contacts SET phone='+573001234568' WHERE id=%s", (record["id"],))
    data = client.get("/crm/workspace").json()
    assert data["counts"]["template_leads"] == 0
    assert data["counts"]["campaign_leads"] == 1
    assert data["contacts"][0]["template_tags"] == []


def test_failed_recipient_is_not_a_template_lead(intake, monkeypatch):
    client, _ = intake
    apply(conversation(), [message()])
    monkeypatch.setattr(cohorts, "ACCOUNT", WA)
    native = {
        "id": "d" * 24,
        "recipientCount": 1,
        "startedAt": SENT.isoformat(),
    }
    monkeypatch.setattr(cohorts, "discover", lambda credentials: [native])
    monkeypatch.setattr(
        cohorts.capture.inbox_service,
        "account",
        lambda *args: {"platform": "whatsapp", "active": True},
    )
    monkeypatch.setattr(
        cohorts.provider,
        "request",
        lambda *args: {
            "recipients": [
                {"platformIdentifier": "573001234567", "status": "failed", "sentAt": None}
            ],
            "pagination": {"total": 1, "hasMore": False},
        },
    )
    cohorts.tick()
    data = client.get("/crm/workspace").json()
    assert data["counts"]["contacts"] == 1
    assert data["counts"]["template_leads"] == 0
    with connect() as db:
        assert (
            db.execute("SELECT count(*) AS n FROM crm.template_lead_attribution").fetchone()["n"]
            == 0
        )


def test_native_discovery_follows_pagination_without_writes(monkeypatch):
    monkeypatch.setattr(cohorts, "ACCOUNT", WA)
    calls = []
    native = {
        "id": "d" * 24,
        "name": cohorts.NATIVE_NAME,
        "accountId": WA,
        "platform": "whatsapp",
        "status": "completed",
        "recipientCount": 0,
        "template": {"name": cohorts.TEMPLATE, "language": "es"},
        "segmentFilters": {"tags": [cohorts.NATIVE_TAG]},
        "startedAt": SENT.isoformat(),
    }

    def request(credentials, method, path):
        calls.append((method, path))
        if path == "/v1/broadcasts":
            return {
                "broadcasts": [{"name": "Another brand", "accountId": "other"}],
                "pagination": {"hasMore": True},
            }
        if path == "/v1/broadcasts?limit=100&skip=1":
            return {"broadcasts": [native], "pagination": {"hasMore": False}}
        return {"broadcast": native}

    monkeypatch.setattr(cohorts.provider, "request", request)
    assert cohorts.discover({"profile_id": PROFILE}) == [native]
    assert calls == [
        ("GET", "/v1/broadcasts"),
        ("GET", "/v1/broadcasts?limit=100&skip=1"),
        ("GET", "/v1/broadcasts/" + "d" * 24),
    ]


def test_pagination_transport_is_get_only_and_keeps_existing_routes(monkeypatch):
    import json

    import pytest
    from fastapi import HTTPException

    calls = []

    class Response:
        status = 200

        def read(self, maximum):
            return json.dumps({"success": True}).encode()

        def getheader(self, name, default=""):
            return "application/json"

    class Connection:
        def request(self, method, path, **kwargs):
            calls.append((method, path))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(cohorts.provider, "https_connection", lambda *args, **kwargs: Connection())
    credentials = {"api_key": "synthetic"}
    path = "/v1/broadcasts?limit=100&skip=1"
    assert cohorts.provider.request(credentials, "GET", path) == {"success": True}
    for method, payload in [("POST", None), ("DELETE", None), ("GET", {})]:
        with pytest.raises(HTTPException) as rejected:
            cohorts.provider.request(credentials, method, path, payload)
        assert rejected.value.status_code == 422
    for method in ("GET", "POST"):
        assert cohorts.provider.request(credentials, method, "/v1/broadcasts") == {"success": True}
    assert calls == [
        ("GET", "/api" + path),
        ("GET", "/api/v1/broadcasts"),
        ("POST", "/api/v1/broadcasts"),
    ]
