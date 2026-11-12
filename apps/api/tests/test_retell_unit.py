"""Pure Retell boundaries; no database, account or paid calls."""

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.retell import bridge, models, service


@pytest.mark.parametrize(
    "key", ["api_key", "auth_config", "custom_sip_headers", "access_token", "password"]
)
def test_secret_arguments_rejected_before_persistence(key):
    with pytest.raises(ValidationError):
        models.Execute(endpoint="createAgent", arguments={"requestBody": {key: "private"}})


def test_arguments_bounded_and_strict():
    for value in [float("nan"), "x" * 33000]:
        with pytest.raises(ValidationError):
            models.Execute(endpoint="getAgent", arguments={"agent_id": value})
    with pytest.raises(ValidationError):
        models.Execute(endpoint="getAgent", arguments={}, consent_confirmed=True)


def test_gateway_state_fails_closed(monkeypatch):
    monkeypatch.setattr(bridge, "request", lambda *a, **k: {"api_key": "private"})
    assert service.state()["available"] is False
    with pytest.raises(HTTPException) as caught:
        service.require_state()
    assert caught.value.status_code == 503


def test_fixed_gateway_host_and_routes(monkeypatch):
    monkeypatch.setenv("RETELL_GATEWAY_URL", "https://attacker.invalid")
    assert bridge.base_url() is None
    with pytest.raises(HTTPException):
        bridge.request("/arbitrary")
    monkeypatch.setenv("RETELL_GATEWAY_URL", "http://retell-gateway:8093")
    assert bridge.base_url() == "http://retell-gateway:8093"


def test_response_redaction_and_size():
    result = service.safe_result(
        {"access_token": "private", "nested": {"headers": {"a": "secret"}, "name": "ok"}}
    )
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)
    assert result["nested"]["name"] == "ok"
    assert len(json.dumps(service.safe_result({"text": "x" * 100000}))) < 25000


def test_outreach_exact_contact_binding_and_colombia_blocked():
    contact = {"contact_id": str(uuid4()), "expected_phone": "+573001234567"}
    args = models.Execute(
        endpoint="createPhoneCall",
        arguments={
            "requestBody": {"from_number": "+15550000000", "to_number": contact["expected_phone"]}
        },
        contacts=[contact],
    )
    with pytest.raises(HTTPException) as caught:
        service.validate_contacts(None, args)
    assert caught.value.detail == "retell_route_confirmation_required"


def test_schema_summary_not_entire_large_schema():
    source = {
        "type": "object",
        "properties": {
            f"field{i}": {"type": "string", "description": "x" * 20000} for i in range(100)
        },
    }
    result = service.schema_page(source, models.SchemaBrowse(endpoint="createAgent"))
    assert len(json.dumps(result).encode()) < 12 * 1024
    assert result["next_offset"] is not None


@pytest.mark.parametrize("status", ["ready", "completed", "external_outcome_unconfirmed"])
def test_execution_always_identifies_retell_provider(monkeypatch, status):
    request_id = str(uuid4())
    endpoint = "createWebCall" if status == "ready" else "getAgent"
    value = {"status": status}
    if status == "ready":
        value["session_id"] = request_id
    elif status == "completed":
        value.update(endpoint=endpoint, data={"agent_id": "fixture"})
    monkeypatch.setattr(bridge, "request", lambda *a, **k: value)
    result = service.execute_reserved({"endpoint": endpoint, "request_id": request_id}, {})
    assert result["provider"] == "retell"
