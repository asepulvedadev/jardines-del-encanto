"""Inbox is private, profile-scoped and never dispatches before confirmation."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_crm import authenticated  # noqa: F401

from app.inbox import provider, service
from app.inbox.models import OPERATIONS, Execute, validate
from app.main import app

ACCOUNT = "a" * 24
PROFILE = "b" * 24
CREDENTIALS = {
    "api_key": "private-test-key",
    "profile_id": PROFILE,
    "generation": "test-generation",
}


def reply(**changes):
    return {
        "operation": "sendInboxMessage",
        "account_id": ACCOUNT,
        "path": {"conversationId": "opaque:wa/a?b"},
        "query": {},
        "body": {"message": "Respuesta de prueba"},
        **changes,
    }


def test_catalog_covers_the_complete_pinned_inbox_contract():
    assert len(OPERATIONS) == 43
    assert all(op["path"].startswith("/v1/inbox/") for op in OPERATIONS.values())
    for name in (
        "sendInboxMessage",
        "getMessageAttachment",
        "listInboxMentions",
        "replyToMention",
        "replyToInboxReview",
        "replyToInboxPost",
        "setConversationThreadControl",
        "addMessageReaction",
        "setCommentModeration",
        "listInboxLabels",
    ):
        assert name in OPERATIONS


def test_models_inject_scope_and_encode_opaque_ids_once():
    operation, args = validate(Execute(**reply()), CREDENTIALS)
    assert args["body"]["accountId"] == ACCOUNT
    path = provider.route(operation, args)
    assert path == "/v1/inbox/conversations/opaque%3Awa%2Fa%3Fb/messages"
    _, args = validate(Execute(operation="listInboxConversations", account_id=ACCOUNT), CREDENTIALS)
    assert args["query"] == {"accountId": ACCOUNT, "profileId": PROFILE}


@pytest.mark.parametrize(
    "changes",
    [
        {"operation": "https://evil.test"},
        {"body": {"accountId": "other", "message": "x"}},
        {"query": {"profileId": "other"}},
        {"body": {"message": "x", "headers": {"Authorization": "secret"}}},
        {"body": {"attachmentUrl": "http://127.0.0.1/secret"}},
        {"path": {"conversationId": ".."}},
        {"body": {"message": "x", "interactive": {"not-a-field": "x"}}},
    ],
)
def test_invalid_commands_never_reach_the_network(changes):
    with pytest.raises((HTTPException, ValueError)):
        validate(Execute(**reply(**changes)), CREDENTIALS)


def test_unknown_query_and_attachment_redirect_are_rejected():
    for query in ({"url": "https://evil.test"}, {"format": "redirect"}):
        with pytest.raises(HTTPException):
            validate(
                Execute(
                    operation="getMessageAttachment",
                    account_id=ACCOUNT,
                    path={"conversationId": "c", "messageId": "m", "index": 0},
                    query=query,
                ),
                CREDENTIALS,
            )


def test_private_routes_require_session_and_bound_the_request():
    with TestClient(app) as client:
        for path in ("/crm/inbox/catalog", "/crm/inbox/accounts", "/crm/inbox/actions"):
            assert client.get(path).status_code == 401
        assert client.post("/crm/inbox/read", json=reply()).status_code == 401
        assert client.post("/crm/inbox/prepare", content=b"x" * 65537).status_code == 413


@pytest.fixture
def vendor(monkeypatch):
    calls = []
    monkeypatch.setattr(service.config, "required", lambda: deepcopy(CREDENTIALS))
    monkeypatch.setattr(service, "require_connections", lambda *args: None)
    monkeypatch.setattr(
        service,
        "context",
        lambda *args: {
            "participantId": "fixture-participant",
            "participantName": "Contacto de prueba",
            "platform": "whatsapp",
            "accountId": ACCOUNT,
        },
    )
    monkeypatch.setattr(
        service,
        "accounts",
        lambda credentials: [
            {"id": ACCOUNT, "platform": "whatsapp", "name": "Número de prueba", "active": True}
        ],
    )

    def request(credentials, operation, args, key=None):
        calls.append((operation["method"], args, key))
        return {"data": {"id": "receipt-1", "accountId": ACCOUNT}, "status": "success"}

    monkeypatch.setattr(provider, "request", request)
    return calls


def test_read_cannot_send_and_prepare_has_no_external_write(authenticated, vendor):
    client, _, _ = authenticated
    assert client.post("/crm/inbox/read", json=reply()).status_code == 422
    plan = client.post("/crm/inbox/prepare", json=reply())
    assert plan.status_code == 201, plan.text
    assert plan.json()["state"] == "prepared"
    assert not vendor
    assert (
        client.post(
            "/crm/inbox/read?url=https://evil.test",
            json={"operation": "listInboxConversations", "account_id": ACCOUNT},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/crm/inbox/prepare", headers={"X-CSRF-Token": "wrong"}, json=reply()
        ).status_code
        == 403
    )
    assert not vendor


def test_explicit_confirmation_executes_once_and_survives_replay(authenticated, vendor):
    client, _, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()
    path = f"/crm/inbox/actions/{plan['id']}/confirm"
    assert client.post(path, json={"confirmed": False}).status_code == 422
    result = client.post(path, json={"confirmed": True})
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "sent"
    assert len(vendor) == 1 and vendor[0][2] == plan["id"]
    assert client.post(path, json={"confirmed": True}).status_code == 409
    assert len(vendor) == 1
    assert client.get("/crm/inbox/actions").json()["items"][0]["state"] == "sent"


def test_concurrent_confirmation_has_one_winner(authenticated, vendor):
    client, _, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()

    def confirm(_):
        return client.post(
            f"/crm/inbox/actions/{plan['id']}/confirm", json={"confirmed": True}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, range(2))) == [200, 409]
    assert len(vendor) == 1


def test_unknown_delivery_is_durable_and_not_retried(authenticated, vendor, monkeypatch):
    client, _, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()

    def ambiguous(*args, **kwargs):
        vendor.append("attempt")
        raise HTTPException(502, "inbox_delivery_unknown")

    monkeypatch.setattr(provider, "request", ambiguous)
    path = f"/crm/inbox/actions/{plan['id']}/confirm"
    assert client.post(path, json={"confirmed": True}).json()["state"] == "unknown"
    assert client.post(path, json={"confirmed": True}).status_code == 409
    assert len(vendor) == 1


def test_confirmation_revalidates_rotation_account_and_actor(authenticated, vendor, monkeypatch):
    client, _, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()
    monkeypatch.setattr(
        service.config, "required", lambda: {**CREDENTIALS, "generation": "rotated"}
    )
    assert (
        client.post(
            f"/crm/inbox/actions/{plan['id']}/confirm", json={"confirmed": True}
        ).status_code
        == 409
    )
    assert not vendor
    assert (
        client.post(f"/crm/inbox/actions/{uuid4()}/confirm", json={"confirmed": True}).status_code
        == 404
    )


def test_foreign_or_disconnected_account_is_rejected(authenticated, vendor):
    client, _, _ = authenticated
    assert client.post("/crm/inbox/prepare", json=reply(account_id="c" * 24)).status_code == 409
    assert not vendor


def schema_example(schema):
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for kind in ("anyOf", "oneOf"):
        if schema.get(kind):
            return schema_example(schema[kind][0])
    kind = schema.get("type")
    if kind == "object":
        return {k: schema_example(schema["properties"][k]) for k in schema.get("required", [])}
    if kind == "array":
        return [schema_example(schema.get("items", {})) for _ in range(schema.get("minItems", 0))]
    if kind in ("number", "integer"):
        return schema.get("minimum", 1)
    if kind == "boolean":
        return True
    return "123" if schema.get("pattern") == "^[0-9]+$" else "fixture-id"


@pytest.mark.parametrize("name", sorted(OPERATIONS))
def test_every_catalog_operation_constructs_only_its_fixed_route(name):
    operation = OPERATIONS[name]
    values = {location: schema_example(schema) for location, schema in operation["input"].items()}
    for fields in values.values():
        fields.pop("accountId", None)
        fields.pop("profileId", None)
    if name == "getMessageAttachment":
        values["query"]["format"] = "json"
    op, args = validate(Execute(operation=name, account_id=ACCOUNT, **values), CREDENTIALS)
    path = provider.route(op, args)
    assert path.startswith("/v1/inbox/") and "{" not in path
    assert ACCOUNT in path or args["body"].get("accountId") == ACCOUNT


def test_transport_never_follows_redirects_leaks_tokens_or_retries(monkeypatch):
    events = []

    class Response:
        status = 302

        def read(self, size):
            return b'{"error":"private-test-key"}'

        def getheader(self, name, default=None):
            return "application/json" if name == "Content-Type" else "https://evil.test"

    class Connection:
        def request(self, *args, **kwargs):
            events.append(args)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(provider, "https_connection", lambda host, timeout: Connection())
    op, args = validate(Execute(**reply()), CREDENTIALS)
    with pytest.raises(HTTPException) as cause:
        provider.request(CREDENTIALS, op, args, key=str(uuid4()))
    assert cause.value.detail == "inbox_provider_rejected"
    assert len(events) == 1 and events[0][1].startswith("/api/v1/inbox/")
    clean = provider.scrub(
        {
            "api_key": "private-test-key",
            "message": "private-test-key",
            "nested": {"refresh_token": "x", "message": "hello"},
        },
        CREDENTIALS,
    )
    assert clean == {"message": "[redacted]", "nested": {"message": "hello"}}


def test_foreign_result_account_is_not_exposed():
    with pytest.raises(HTTPException):
        service.scope_result({"data": [{"accountId": "foreign", "message": "private"}]}, ACCOUNT)


def test_actor_cannot_confirm_another_actors_action(authenticated, vendor):
    client, _, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()
    with pytest.raises(HTTPException) as cause:
        service.confirm(plan["id"], {"id": uuid4()})
    assert cause.value.status_code == 404
    assert not vendor


def test_expired_preparation_cannot_send(authenticated, vendor):
    import psycopg

    client, owner_url, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()
    with psycopg.connect(owner_url) as db:
        db.execute(
            "UPDATE crm.inbox_actions SET expires_at=now()-interval '1 second' WHERE id=%s",
            (plan["id"],),
        )
    assert (
        client.post(
            f"/crm/inbox/actions/{plan['id']}/confirm", json={"confirmed": True}
        ).status_code
        == 409
    )
    assert not vendor


def test_read_uses_selected_account_and_has_no_external_write(authenticated, vendor):
    client, _, _ = authenticated
    result = client.post(
        "/crm/inbox/read", json={"operation": "listInboxConversations", "account_id": ACCOUNT}
    )
    assert result.status_code == 200
    assert vendor[0][0] == "GET"
    assert vendor[0][1]["query"]["profileId"] == PROFILE
    assert vendor[0][1]["query"]["accountId"] == ACCOUNT


def test_recipient_identity_is_revalidated_before_external_dispatch(
    authenticated, vendor, monkeypatch
):
    client, _, _ = authenticated
    plan = client.post("/crm/inbox/prepare", json=reply()).json()
    monkeypatch.setattr(
        service,
        "context",
        lambda *args: {
            "participantId": "different-participant",
            "participantName": "Changed",
            "platform": "whatsapp",
            "accountId": ACCOUNT,
        },
    )
    assert (
        client.post(
            f"/crm/inbox/actions/{plan['id']}/confirm", json={"confirmed": True}
        ).status_code
        == 409
    )
    assert not vendor


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_confirmation_never_coerces_non_boolean_consent(value):
    from pydantic import ValidationError

    from app.inbox.models import Confirmation

    with pytest.raises(ValidationError):
        Confirmation(confirmed=value)
