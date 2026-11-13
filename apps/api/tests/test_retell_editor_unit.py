"""Pure complete-editor boundary tests; no database or provider requests."""

import pytest
from pydantic import ValidationError

from app.retell import editor, models


def test_editor_input_has_exact_identity_and_no_arbitrary_endpoint():
    assert models.EditorRead(revision=1, kind="instructions", id="llm_1", version=0).version == 0
    for extra in ({"endpoint": "createAgent"}, {"consent_confirmed": True}, {"api_key": "private"}):
        with pytest.raises(ValidationError):
            models.EditorRead(revision=1, kind="agent", id="agent_1", **extra)
    with pytest.raises(ValidationError):
        models.EditorRead(revision=1, kind="agent", id="agent_1", version=None)
    for invalid in ("", "https://other.invalid", "../state"):
        with pytest.raises(ValidationError):
            models.EditorRead(revision=1, kind="agent", id=invalid)


def test_complete_response_validation_rejects_partial_or_private_fields():
    request = models.EditorRead(revision=1, kind="instructions", id="llm_1", version=7)
    value = {
        "status": "completed",
        "endpoint": "getRetellLLM",
        "data": {"llm_id": "llm_1", "version": 7, "general_prompt": "complete " * 600},
        "editor": {"complete_fields": ["general_prompt"], "blocked_fields": {}},
    }
    assert (
        editor.validate_result(value, request, {"general_prompt": {"type": "string"}})["data"][
            "general_prompt"
        ]
        == value["data"]["general_prompt"]
    )
    for data in (
        {**value, "editor": {"complete_fields": [], "blocked_fields": {}}},
        {**value, "data": {**value["data"], "api_key": "private"}},
        {**value, "data": {**value["data"], "version": 8}},
    ):
        with pytest.raises((ValueError, ValidationError)):
            editor.validate_result(data, request, {"general_prompt": {"type": "string"}})


@pytest.fixture
def fake_editor(monkeypatch):
    from contextlib import contextmanager
    from uuid import uuid4

    from app.retell import bridge, inventory, service

    state = {"current": True, "provider": 1, "schema": "a" * 64, "version": 3}
    calls, audits, phases = [], [], []

    @contextmanager
    def connection():
        phases.append("open")
        try:
            yield object()
        finally:
            phases.append("committed")

    def current(db, admin, version=None):
        from fastapi import HTTPException

        if not state["current"]:
            raise HTTPException(401, "authentication_required")
        if version is not None and version != state["version"]:
            raise HTTPException(409, "connection_changed")
        return state["version"]

    def preflight(db, args, revision=None, **kw):
        from fastapi import HTTPException

        if revision != state["provider"]:
            raise HTTPException(409, "retell_provider_changed")
        return revision, state["schema"]

    def prepare(db, row, args, admin, consent, **kw):
        assert consent is False
        return {
            "request_id": str(row["id"]),
            "revision": 1,
            "endpoint": args.endpoint,
            "arguments": args.arguments,
            "expected_schema_hash": state["schema"],
            "consent_confirmed": False,
        }

    def schema(db, data):
        return {
            "input_schema": {
                "properties": {
                    "requestBody": {
                        "properties": {
                            "general_prompt": {"type": "string"},
                            "begin_message": {"type": "string", "nullable": True},
                        }
                    }
                }
            }
        }

    def request(path, body, timeout=3):
        assert phases[-1] == "committed"
        calls.append((path, body))
        return {
            "status": "completed",
            "endpoint": "getRetellLLM",
            "data": {
                "llm_id": "llm_1",
                "version": 7,
                "general_prompt": "Complete " * 900,
                "begin_message": None,
            },
            "editor": {
                "complete_fields": ["general_prompt", "begin_message"],
                "blocked_fields": {},
            },
        }

    monkeypatch.setattr(editor, "connect", connection)
    monkeypatch.setattr(inventory, "_current", current)
    monkeypatch.setattr(service, "preflight", preflight)
    monkeypatch.setattr(service, "prepare", prepare)
    monkeypatch.setattr(service, "schema", schema)
    monkeypatch.setattr(bridge, "request", request)
    monkeypatch.setattr(
        editor.control, "audit", lambda db, admin, action, data: audits.append((action, data))
    )
    return state, calls, audits, {"id": uuid4(), "token_hash": "fixture"}, request


def test_editor_snapshot_exact_full_values_metadata_only_and_no_proposals(fake_editor):
    _, calls, audits, admin, _ = fake_editor
    result = editor.snapshot(
        models.EditorRead(revision=1, kind="instructions", id="llm_1", version=7), admin
    )
    assert result["data"]["general_prompt"] == "Complete " * 900
    assert result["data"]["begin_message"] is None
    assert result["provider"] == "retell"
    assert [path for path, _ in calls] == ["/editor-read"]
    assert calls[0][1]["endpoint"] == "getRetellLLM"
    assert calls[0][1]["arguments"] == {"llm_id": "llm_1", "version": 7}
    assert [data["stage"] for _, data in audits] == ["prepared", "completed"]
    assert "Complete" not in str(audits)


@pytest.mark.parametrize("change", ["current", "provider", "schema", "version"])
def test_editor_rechecks_live_identity_connection_and_revision_after_read(
    fake_editor, monkeypatch, change
):
    from fastapi import HTTPException

    from app.retell import bridge

    state, _, audits, admin, request = fake_editor

    def changed(path, body, timeout=3):
        result = request(path, body, timeout)
        state[change] = {"current": False, "provider": 2, "schema": "b" * 64, "version": 4}[change]
        return result

    monkeypatch.setattr(bridge, "request", changed)
    with pytest.raises(HTTPException):
        editor.snapshot(
            models.EditorRead(revision=1, kind="instructions", id="llm_1", version=7), admin
        )
    assert len(audits) == 1


def test_editor_routes_authentication_exact_inputs_and_query_guard(fake_editor):
    from fastapi.testclient import TestClient

    from app.crm import security
    from app.main import app

    _, calls, _, admin, _ = fake_editor
    with TestClient(app) as client:
        assert (
            client.post(
                "/crm/retell/editor", json={"revision": 1, "kind": "instructions", "id": "llm_1"}
            ).status_code
            == 401
        )
    app.dependency_overrides[security.session] = lambda: admin
    try:
        with TestClient(app) as client:
            base = {"revision": 1, "kind": "instructions", "id": "llm_1", "version": 7}
            for invalid in (
                {**base, "revision": True},
                {**base, "version": True},
                {**base, "id": ""},
                {**base, "endpoint": "createAgent"},
                {**base, "kind": "call"},
            ):
                assert client.post("/crm/retell/editor", json=invalid).status_code == 422
            assert client.post("/crm/retell/editor?url=bad", json=base).status_code == 422
            assert client.get("/crm/retell/editor").status_code == 405
            assert not calls
            response = client.post("/crm/retell/editor", json=base)
            assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    finally:
        app.dependency_overrides.pop(security.session, None)
