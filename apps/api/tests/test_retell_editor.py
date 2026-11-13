"""Guarded full-editor HTTP/DB tests; parent runs the isolated database suite serially."""

# ruff: noqa: F811
import psycopg
import pytest
from test_crm import authenticated  # noqa: F401
from test_retell import retelled  # noqa: F401

from app.retell import bridge, editor


@pytest.fixture
def editable(retelled, monkeypatch):
    client, owner, _, state, calls, control = retelled
    request = bridge.request
    full = "Complete behavior and speech instructions. " * 150

    def gateway(path, body=None, timeout=3):
        if path == "/schema" and body["endpoint"] == "updateRetellLLM":
            metadata = editor.service.operation("updateRetellLLM")
            return {
                "revision": state["revision"],
                "endpoint": "updateRetellLLM",
                "schema_hash": control["hash"],
                "metadata": metadata,
                "input_schema": {
                    "properties": {
                        "requestBody": {
                            "properties": {
                                "general_prompt": {"type": "string"},
                                "begin_message": {"type": "string", "nullable": True},
                            }
                        }
                    }
                },
            }
        if path == "/editor-read":
            calls.append((path, body))
            return {
                "status": "completed",
                "endpoint": "getRetellLLM",
                "data": {
                    "llm_id": "llm_1",
                    "version": 7,
                    "general_prompt": full,
                    "begin_message": None,
                },
                "editor": {
                    "complete_fields": ["general_prompt", "begin_message"],
                    "blocked_fields": {},
                },
            }
        return request(path, body, timeout)

    monkeypatch.setattr(bridge, "request", gateway)
    return client, owner, calls, full


def test_editor_full_prompt_preserved_without_proposal_or_snapshot_persistence(editable):
    client, owner, calls, full = editable
    response = client.post(
        "/crm/retell/editor",
        json={"revision": 1, "kind": "instructions", "id": "llm_1", "version": 7},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["general_prompt"] == full
    assert response.json()["data"]["begin_message"] is None
    assert "no-store" in response.headers["cache-control"]
    assert sum(path == "/editor-read" for path, _ in calls) == 1
    assert not any(path == "/execute" for path, _ in calls)
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0
        audits = db.execute(
            "SELECT arguments FROM crm.control_audit WHERE action='retell.editor_read'"
        ).fetchall()
        assert len(audits) == 2 and full not in str(audits)


def test_editor_admin_csrf_query_and_disabled_connection(editable):
    client, owner, calls, _ = editable
    body = {"revision": 1, "kind": "instructions", "id": "llm_1", "version": 7}
    assert (
        client.post("/crm/retell/editor", json=body, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert (
        client.post(
            "/crm/retell/editor", json=body, headers={"Origin": "https://other.invalid"}
        ).status_code
        == 403
    )
    assert client.post("/crm/retell/editor?endpoint=createAgent", json=body).status_code == 422
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='retell'")
    assert client.post("/crm/retell/editor", json=body).status_code == 409
    assert not any(path == "/editor-read" for path, _ in calls)
