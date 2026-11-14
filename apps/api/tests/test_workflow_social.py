"""Read-only preparation and one-shot fixed-host messaging; never real vendor traffic."""

import copy
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.social import workflow

PROFILE, ACCOUNT = "a" * 24, "b" * 24
CONTACT = {"id": "contact-1", "name": "Ana", "phone": "+573001234567"}
NODE = {
    "kind": "whatsapp_template",
    "settings": {
        "account_id": ACCOUNT,
        "template_name": "welcome",
        "language": "es_CO",
        "parameters": ["{{nombre}}"],
    },
}


@pytest.fixture
def vendor(monkeypatch):
    state = {
        "credentials": {
            "api_key": "private-key-never-return",
            "profile_id": PROFILE,
            "generation": "generation-1",
            "webhook_secret": "secret",
        },
        "accounts": [
            {
                "_id": ACCOUNT,
                "profileId": PROFILE,
                "platform": "whatsapp",
                "isActive": True,
                "needsReconnection": False,
                "displayName": "Jardines",
            }
        ],
        "templates": [
            {
                "id": "template-1",
                "name": "welcome",
                "language": "es_CO",
                "status": "APPROVED",
                "components": [{"type": "BODY", "text": "Hola {{1}}"}],
            }
        ],
        "conversations": [],
        "messages": [],
        "calls": [],
        "post_status": 201,
        "post_body": {
            "success": True,
            "data": {
                "messageId": "wamid.1",
                "conversationId": "thread:1",
                "participantId": "573001234567",
            },
        },
    }

    class Response:
        def __init__(self, status, body):
            self.status, self.body = status, json.dumps(body).encode()

        def read(self, maximum):
            return self.body[:maximum]

    class Connection:
        def request(self, method, path, body=None, headers=None):
            state["calls"].append((method, path, json.loads(body) if body else None, headers))
            self.method, self.path = method, path

        def getresponse(self):
            if self.method == "POST":
                if state.get("timeout"):
                    raise TimeoutError("SECRET upstream timeout")
                return Response(state["post_status"], state["post_body"])
            if self.path.startswith("/api/v1/accounts?"):
                return Response(200, {"accounts": state["accounts"]})
            if self.path.startswith("/api/v1/whatsapp/templates?"):
                return Response(200, {"success": True, "templates": state["templates"]})
            if "/messages?" in self.path:
                return Response(200, {"messages": state["messages"]})
            return Response(200, {"data": state["conversations"], "pagination": {"hasMore": False}})

        def close(self):
            pass

    def connection(host, timeout):
        assert host == "zernio.com" and timeout == 4
        return Connection()

    monkeypatch.setattr(workflow, "https_connection", connection)
    monkeypatch.setattr(workflow.config, "required", lambda: copy.deepcopy(state["credentials"]))
    monkeypatch.setattr(workflow.config, "locked", nullcontext)
    monkeypatch.setattr(workflow, "connect", lambda: nullcontext(None))
    monkeypatch.setattr(workflow, "require_connections", lambda db, *keys: None)
    return state


def conversation(vendor, platform="whatsapp", control="app", age=1):
    vendor["accounts"][0]["platform"] = platform
    vendor["conversations"] = [
        {
            "id": "thread:1",
            "accountId": ACCOUNT,
            "platform": platform,
            "participantId": "573001234567",
            "participantName": "Ana",
            "threadControl": control,
        }
    ]
    vendor["messages"] = [
        {
            "id": "incoming.1",
            "conversationId": "thread:1",
            "accountId": ACCOUNT,
            "platform": platform,
            "senderId": "573001234567",
            "direction": "incoming",
            "createdAt": (datetime.now(UTC) - timedelta(hours=age)).isoformat(),
        }
    ]
    return {
        "kind": "social_message",
        "settings": {"account_id": ACCOUNT, "platform": platform, "text": "Hola {{nombre}}"},
    }, {"account_id": ACCOUNT, "conversation_id": "thread:1"}


def test_template_prepare_is_read_only_private_and_dispatch_exact(vendor):
    plan = workflow.prepare(None, NODE, CONTACT)
    assert "private-key" not in json.dumps(plan)
    assert plan["summary"]["parameters"] == ["Ana"]
    assert all(call[0] == "GET" for call in vendor["calls"])
    result = workflow.dispatch(plan, "reserved-request-1")
    posts = [call for call in vendor["calls"] if call[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][1:3] == (
        "/api/v1/inbox/conversations",
        {
            "accountId": ACCOUNT,
            "participantId": "573001234567",
            "templateName": "welcome",
            "templateLanguage": "es_CO",
            "templateParams": ["Ana"],
        },
    )
    assert result == {
        "state": "completed",
        "receipt": {"status": "accepted", "message_id": "wamid.1", "conversation_id": "thread:1"},
    }


@pytest.mark.parametrize("change", ["credentials", "account", "template", "tamper"])
def test_revisions_and_plan_tamper_block_without_send(vendor, change):
    plan = workflow.prepare(None, NODE, CONTACT)
    if change == "credentials":
        vendor["credentials"]["api_key"] = "rotated"
    elif change == "account":
        vendor["accounts"][0]["isActive"] = False
    elif change == "template":
        vendor["templates"][0]["components"][0]["text"] = "Changed {{1}}"
    else:
        plan["payload"]["participantId"] = "573009999999"
    with pytest.raises(HTTPException):
        workflow.dispatch(plan, "reserved-request-1")
    assert not any(c[0] == "POST" for c in vendor["calls"])


def test_exact_existing_conversation_reply_and_encoded_opaque_path(vendor):
    node, binding = conversation(vendor)
    plan = workflow.prepare(None, node, CONTACT, binding)
    result = workflow.dispatch(plan, "request-1")
    post = next(c for c in vendor["calls"] if c[0] == "POST")
    assert post[1] == "/api/v1/inbox/conversations/thread%3A1/messages"
    assert post[2] == {"accountId": ACCOUNT, "message": "Hola Ana"}
    assert result["state"] == "completed"


@pytest.mark.parametrize("control", [None, "ai_agent", "other"])
def test_thread_control_absent_or_external_is_never_taken(vendor, control):
    node, binding = conversation(vendor, control=control)
    with pytest.raises(HTTPException):
        workflow.prepare(None, node, CONTACT, binding)
    with pytest.raises(HTTPException):
        workflow.prepare(None, NODE, CONTACT)


def test_window_requires_incoming_exact_recipient_and_rechecks(vendor):
    node, binding = conversation(vendor)
    plan = workflow.prepare(None, node, CONTACT, binding)
    vendor["messages"][0]["direction"] = "outgoing"
    with pytest.raises(HTTPException):
        workflow.check(plan)
    vendor["messages"][0]["direction"] = "incoming"
    vendor["messages"][0]["createdAt"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with pytest.raises(HTTPException):
        workflow.prepare(None, node, CONTACT, binding)


@pytest.mark.parametrize("platform", ["telegram", "tiktok"])
def test_no_personal_recipient_inference_on_unsupported_channel(vendor, platform):
    node, binding = conversation(vendor, platform=platform)
    with pytest.raises(HTTPException):
        workflow.prepare(None, node, CONTACT, binding)


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_provider_implicit_takeover_policy_cannot_be_authorized(vendor, platform):
    node, binding = conversation(vendor, platform=platform)
    with pytest.raises(HTTPException) as exc:
        workflow.prepare(None, node, CONTACT, binding)
    assert exc.value.detail == "provider_control_policy_unreviewed"
    assert workflow.options(None)["accounts"][0]["available"] is False


def test_prepare_cache_is_per_request_and_never_used_for_dispatch(vendor):
    cache = {}
    workflow.prepare(None, NODE, CONTACT, cache=cache)
    count = len(vendor["calls"])
    plan = workflow.prepare(None, NODE, CONTACT, cache=cache)
    assert len(vendor["calls"]) == count
    vendor["templates"][0]["status"] = "PAUSED"
    with pytest.raises(HTTPException):
        workflow.dispatch(plan, "reserved-1")
    assert not any(c[0] == "POST" for c in vendor["calls"])


@pytest.mark.parametrize("mutation", ["account", "sender", "conversation", "future", "standby"])
def test_window_proof_requires_exact_nonstandby_incoming(vendor, mutation):
    node, binding = conversation(vendor)
    message = vendor["messages"][0]
    if mutation == "account":
        message["accountId"] = "other"
    elif mutation == "sender":
        message["senderId"] = "other"
    elif mutation == "conversation":
        message["conversationId"] = "other"
    elif mutation == "future":
        message["createdAt"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    else:
        message["metadata"] = {"standby": True}
    with pytest.raises(HTTPException):
        workflow.prepare(None, node, CONTACT, binding)


@pytest.mark.parametrize("mutation", ["media", "named", "buttons", "count", "pending"])
def test_only_approved_simple_text_templates_with_exact_parameters(vendor, mutation):
    if mutation == "media":
        vendor["templates"][0]["components"].append({"type": "HEADER", "format": "IMAGE"})
    elif mutation == "named":
        vendor["templates"][0]["parameter_format"] = "NAMED"
    elif mutation == "buttons":
        vendor["templates"][0]["components"].append({"type": "BUTTONS", "buttons": []})
    elif mutation == "count":
        vendor["templates"][0]["components"][0]["text"] = "Hola {{1}} {{2}}"
    else:
        vendor["templates"][0]["status"] = "PENDING"
    with pytest.raises(HTTPException):
        workflow.prepare(None, NODE, CONTACT)


def test_connection_preferences_disabled_block_prepare_and_dispatch(vendor, monkeypatch):
    plan = workflow.prepare(None, NODE, CONTACT)

    def denied(db, *keys):
        raise HTTPException(409, "connection_disabled")

    monkeypatch.setattr(workflow, "require_connections", denied)
    with pytest.raises(HTTPException):
        workflow.dispatch(plan, "request-1")
    assert workflow.options(None)["reason"] == "connection_disabled"
    assert not any(c[0] == "POST" for c in vendor["calls"])


def test_no_oauth_fallback_when_private_rest_key_absent(vendor, monkeypatch):
    def missing():
        raise HTTPException(503, "zernio_not_configured")

    monkeypatch.setattr(workflow.config, "required", missing)
    assert workflow.options(None) == {
        "available": False,
        "accounts": [],
        "templates": [],
        "conversations": [],
        "reason": "zernio_not_configured",
    }
    assert vendor["calls"] == []


def test_account_profile_mismatch_cannot_be_prepared(vendor):
    vendor["accounts"][0]["profileId"] = "c" * 24
    with pytest.raises(HTTPException):
        workflow.prepare(None, NODE, CONTACT)


def test_new_thread_or_changed_recipient_holds_frozen_plan(vendor):
    plan = workflow.prepare(None, NODE, CONTACT)
    conversation(vendor)
    with pytest.raises(HTTPException):
        workflow.check(plan)
    node, binding = conversation(vendor)
    plan = workflow.prepare(None, node, CONTACT, binding)
    vendor["conversations"][0]["participantId"] = "573009999999"
    with pytest.raises(HTTPException):
        workflow.check(plan)


def test_transport_bounded_reads_and_no_arbitrary_operation(vendor):
    credentials = vendor["credentials"]
    with pytest.raises(HTTPException):
        workflow._request(credentials, "https://attacker.invalid/steal")
    assert vendor["calls"] == []
    vendor["accounts"][0]["untrusted"] = "x" * workflow.MAX_RESPONSE
    with pytest.raises(HTTPException) as exc:
        workflow.prepare(None, NODE, CONTACT)
    assert exc.value.detail == "zernio_workflow_unavailable"


def test_new_template_requires_complete_conversation_page(vendor, monkeypatch):
    request = workflow._request

    def truncated(credentials, operation, **kwargs):
        data = request(credentials, operation, **kwargs)
        if operation == "conversations":
            data["pagination"] = {"hasMore": True, "nextCursor": None}
        return data

    monkeypatch.setattr(workflow, "_request", truncated)
    with pytest.raises(HTTPException) as exc:
        workflow.prepare(None, NODE, CONTACT)
    assert exc.value.detail == "zernio_conversations_incomplete"


def test_no_identity_or_contact_binding_substitution(vendor):
    node, binding = conversation(vendor)
    for changed in (
        {**binding, "account_id": "other"},
        {**binding, "contact_id": "another-contact"},
        {**binding, "conversation_id": "another-thread"},
    ):
        with pytest.raises(HTTPException):
            workflow.prepare(None, node, CONTACT, changed)
    with pytest.raises(HTTPException):
        workflow.prepare(None, node, {**CONTACT, "phone": "+573009999999"}, binding)


@pytest.mark.parametrize("mode", ["timeout", "server", "redirect", "malformed"])
def test_uncertain_submission_held_without_retry_or_body_leak(vendor, mode):
    plan = workflow.prepare(None, NODE, CONTACT)
    if mode == "timeout":
        vendor["timeout"] = True
    elif mode == "server":
        vendor["post_status"] = 502
    elif mode == "redirect":
        vendor["post_status"] = 302
    else:
        vendor["post_body"] = {"secret": "private-key-never-return"}
    result = workflow.dispatch(plan, "reserved-request-1")
    assert result == {"state": "unknown", "receipt": {}, "error": "zernio_submission_unknown"}
    assert len([c for c in vendor["calls"] if c[0] == "POST"]) == 1


def test_options_only_safe_approved_and_unambiguous(vendor):
    conversation(vendor, control="other")
    vendor["templates"][0]["secret"] = "never-return"
    result = workflow.options(None, ACCOUNT)
    assert result["available"] is True
    assert result["templates"][0]["parameter_count"] == 1
    assert result["conversations"][0]["can_reply"] is False
    assert "never-return" not in json.dumps(result)


def test_normalize_only_authenticatable_inbound_identity_without_content():
    payload = {
        "id": "event-1",
        "event": "message.received",
        "account": {"accountId": ACCOUNT, "profileId": PROFILE, "platform": "whatsapp"},
        "conversation": {
            "id": "internal-thread-1",
            "platformConversationId": "thread:1",
            "participantId": "573001234567",
        },
        "message": {
            "id": "internal-1",
            "platformMessageId": "wamid.1",
            "platform": "whatsapp",
            "conversationId": "internal-thread-1",
            "direction": "incoming",
            "sender": {"id": "573001234567"},
            "text": "private message",
            "sentAt": datetime.now(UTC).isoformat(),
        },
    }
    event = workflow.normalize_event(payload)
    assert event["participant_id"] == "573001234567"
    assert event["message_id"] == "wamid.1"
    assert event["conversation_id"] == "thread:1"
    assert "private message" not in json.dumps(event)
    for patch in ({"test": True}, {"metadata": {"standby": True}}):
        assert workflow.normalize_event({**payload, **patch}) is None
    payload["message"]["direction"] = "outgoing"
    assert workflow.normalize_event(payload) is None
