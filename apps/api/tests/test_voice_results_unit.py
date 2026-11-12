"""Approved Retell snapshot boundaries without a database or external provider."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.crm import security
from app.main import app
from app.retell import bridge, routes, service


class SnapshotDB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))
        return self

    def fetchall(self):
        return self.rows


def snapshot_row(endpoint="listAgents", **changes):
    return {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "endpoint": endpoint,
        "revisions": {"provider:retell": 7},
        "result": {
            "provider": "retell",
            "status": "completed",
            "endpoint": endpoint,
            "data": [{"agent_id": "fixture", "api_key": "private"}],
        },
        **changes,
    }


def no_external(*args, **kwargs):
    raise AssertionError("Snapshot recovery must not contact an external provider")


def test_results_are_resanitized_local_latest_per_endpoint(monkeypatch):
    monkeypatch.setattr(bridge, "request", no_external)
    newest = snapshot_row()
    older = snapshot_row()
    voice = snapshot_row("listVoices")
    db = SnapshotDB([newest, older, voice])
    actor, session = uuid4(), "fixture-session-hash"
    result = service.results(db, {"id": actor, "token_hash": session})
    assert result == {
        "partial": True,
        "snapshots": [
            {
                "id": str(row["id"]),
                "endpoint": row["endpoint"],
                "created_at": row["created_at"].isoformat(),
                "provider_revision": 7,
                "data": [{"agent_id": "fixture"}],
            }
            for row in [newest, voice]
        ],
    }
    assert "private" not in json.dumps(result)
    sql, parameters = db.calls[0]
    assert parameters == (actor, session)
    for guard in [
        "actor_id=%s",
        "session_hash=%s",
        "retell.execute",
        "approved",
        "connection:retell",
        "to_jsonb(c.version)",
        "c.enabled",
        "LIMIT 96",
    ]:
        assert guard in sql
    assert "SELECT *" not in sql


@pytest.mark.parametrize(
    "changes",
    [
        {"result": None},
        {"result": []},
        {"endpoint": "createAgent"},
        {"endpoint": "unknownOperation"},
        {"endpoint": []},
        {"id": "not-a-uuid"},
        {"created_at": "not-a-date"},
        {"revisions": []},
        {"revisions": {"provider:retell": True}},
        {"revisions": {"provider:retell": -1}},
        {"revisions": {"provider:retell": "7"}},
        {
            "result": {
                "provider": "other",
                "status": "completed",
                "endpoint": "listAgents",
                "data": [],
            }
        },
        {"result": {"provider": "retell", "status": "ready", "endpoint": "listAgents", "data": []}},
        {
            "result": {
                "provider": "retell",
                "status": "external_outcome_unconfirmed",
                "endpoint": "listAgents",
                "data": [],
            }
        },
        {
            "result": {
                "provider": "retell",
                "status": "completed",
                "endpoint": "getAgent",
                "data": [],
            }
        },
        {"result": {"provider": "retell", "status": "completed", "endpoint": "listAgents"}},
        {
            "result": {
                "provider": "retell",
                "status": "completed",
                "endpoint": "listAgents",
                "data": {"bad": float("nan")},
            }
        },
    ],
)
def test_malformed_or_unreviewed_rows_are_skipped(changes):
    assert service.results(
        SnapshotDB([snapshot_row(**changes)]), {"id": uuid4(), "token_hash": "session"}
    ) == {"partial": True, "snapshots": []}


def test_results_are_bounded_even_with_many_distinct_read_endpoints(monkeypatch):
    operations = {f"read{i}": {"available": True, "risk": "read"} for i in range(100)}
    monkeypatch.setattr(service, "registry", lambda: operations)
    rows = [snapshot_row(key) for key in operations]
    for row in rows:
        row["result"]["data"] = {"items": ["x" * 20000] * 100}
    result = service.results(SnapshotDB(rows), {"id": uuid4(), "token_hash": "session"})
    assert len(result["snapshots"]) == 32
    assert all(len(json.dumps(s["data"]).encode()) <= 16384 for s in result["snapshots"])


def test_disabled_reviewed_operation_does_not_restore_a_snapshot(monkeypatch):
    monkeypatch.setattr(
        service, "registry", lambda: {"listAgents": {"available": False, "risk": "read"}}
    )
    assert (
        service.results(SnapshotDB([snapshot_row()]), {"id": uuid4(), "token_hash": "session"})[
            "snapshots"
        ]
        == []
    )


def test_results_route_is_authenticated_and_rejects_body_and_queries(monkeypatch):
    monkeypatch.setattr(bridge, "request", no_external)
    with TestClient(app) as client:
        assert client.get("/crm/retell/results").status_code == 401
    actor = {"id": uuid4(), "token_hash": "fixture-session"}
    app.dependency_overrides[security.session] = lambda: actor
    opened = []

    @contextmanager
    def connect():
        opened.append(True)
        yield SnapshotDB([])

    monkeypatch.setattr(routes, "connect", connect)
    try:
        with TestClient(app) as client:
            result = client.get("/crm/retell/results")
            assert result.status_code == 200
            assert result.json() == {"snapshots": [], "partial": True}
            assert "no-store" in result.headers["cache-control"]
            assert "private" in result.headers["cache-control"]
            assert client.get("/crm/retell/results?endpoint=listAgents").status_code == 422
            assert client.request("GET", "/crm/retell/results", content=b"{}").status_code == 422
            assert client.post("/crm/retell/results", json={}).status_code == 405
            assert len(opened) == 1
    finally:
        app.dependency_overrides.pop(security.session, None)
