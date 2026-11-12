"""Automatic read policy, synchronization and isolation with fake local dependencies."""

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Event, Lock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.control import service as control
from app.crm import security
from app.main import app
from app.retell import bridge, inventory, models, service


@pytest.fixture
def fake(monkeypatch):
    state = {"version": 1, "enabled": True, "revision": 7, "schema": "a" * 64, "live": True}
    calls, audits = [], []
    state_lock = Lock()

    class DB:
        def execute(self, sql, parameters=None):
            assert (
                "INSERT INTO crm.hermes_proposals" not in sql
                and "UPDATE crm.hermes_proposals" not in sql
            )
            self.sql = sql
            return self

        def fetchone(self):
            if "hermes_proposals" in self.sql:
                return {"completed": state.get("mutation", 0), "newest": None}
            if "crm.sessions" in self.sql:
                return {"id": "fixture"} if state["live"] else None
            return {"enabled": state["enabled"], "version": state["version"]}

    @contextmanager
    def connect():
        yield DB()

    def request(path, body=None, timeout=3):
        with state_lock:
            calls.append((path, deepcopy(body)))
        if path == "/state":
            return {
                "configured": True,
                "verified": True,
                "revision": state["revision"],
                "defaults": {},
            }
        if path == "/prepare":
            return {
                "revision": state["revision"],
                "endpoint": body["endpoint"],
                "risk": "read",
                "requires_consent": False,
                "schema_hash": state["schema"],
            }
        if path == "/execute":
            return {
                "status": "completed",
                "endpoint": body["endpoint"],
                "data": [{"agent_id": "fixture", "access_token": "do-not-expose"}],
            }
        raise AssertionError(path)

    monkeypatch.setattr(inventory, "connect", connect)
    monkeypatch.setattr(control, "require_connections", lambda db, *keys: None)
    monkeypatch.setattr(
        control, "audit", lambda db, admin, action, arguments: audits.append((action, arguments))
    )
    monkeypatch.setattr(bridge, "request", request)
    inventory.clear_cache()
    admin = {"id": uuid4(), "token_hash": "fixture-session"}
    yield state, calls, audits, admin, request
    inventory.clear_cache()


def test_inventory_fixed_reads_cache_and_isolation(fake):
    state, calls, audits, admin, _ = fake
    result = inventory.synchronize(models.Revision(revision=7), admin)
    assert result["partial"] is True and result["cached"] is False
    assert result["errors"] == []
    assert [row["endpoint"] for row in result["snapshots"]] == list(models.INVENTORY_ENDPOINTS)
    assert all(row["data"] == [{"agent_id": "fixture"}] for row in result["snapshots"])
    executed = [body for path, body in calls if path == "/execute"]
    assert len(executed) == 11 and all(body["consent_confirmed"] is False for body in executed)
    assert all(action == "retell.automatic_read" for action, _ in audits)
    assert "do-not-expose" not in str(audits) and "arguments" not in str(audits)
    result["snapshots"][0]["data"].clear()
    assert inventory.synchronize(models.Revision(revision=7), admin)["cached"] is True
    assert inventory.synchronize(models.Revision(revision=7), admin)["snapshots"][0]["data"]
    assert len([1 for path, _ in calls if path == "/execute"]) == 11
    for identity in [{**admin, "token_hash": "another-session"}, {**admin, "id": uuid4()}]:
        assert inventory.synchronize(models.Revision(revision=7), identity)["cached"] is False
    state["version"] += 1
    assert inventory.synchronize(models.Revision(revision=7), admin)["cached"] is False
    state["revision"] = 8
    assert inventory.synchronize(models.Revision(revision=8), admin)["cached"] is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "createAgent",
        "createWebCall",
        "deleteAgent",
        "listenLiveCall",
        "createApp",
        "listAppUsages",
        "futureRead",
    ],
)
def test_denied_operations_never_contact_gateway(fake, endpoint):
    _, calls, _, admin, _ = fake
    with pytest.raises((ValidationError, HTTPException)):
        inventory.read(models.AutomaticRead(revision=7, endpoint=endpoint, arguments={}), admin)
    assert calls == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"url": "https://attacker.invalid"},
        {"agent_id": "https://attacker.invalid"},
        {"headers": {}},
        {"access_token": "secret"},
        {"consent_confirmed": True},
        {"key": float("nan")},
    ],
)
def test_urls_tokens_consent_and_nonfinite_arguments_rejected(fake, arguments):
    _, calls, _, _, _ = fake
    with pytest.raises(ValidationError):
        models.AutomaticRead(revision=7, endpoint="getAgent", arguments=arguments)
    assert calls == []


def test_all_allowed_reads_return_sanitized_completed_results(fake):
    _, calls, _, admin, _ = fake
    for endpoint in models.AUTOMATIC_READ_ENDPOINTS:
        result = inventory.read(
            models.AutomaticRead(revision=7, endpoint=endpoint, arguments={}), admin
        )
        assert result == {
            "provider": "retell",
            "status": "completed",
            "endpoint": endpoint,
            "data": [{"agent_id": "fixture"}],
        }
    assert len([body for path, body in calls if path == "/execute"]) == 23


def test_pinned_policy_change_rejects_before_external_calls(fake, monkeypatch):
    _, calls, _, admin, _ = fake
    monkeypatch.setattr(service, "operation", lambda endpoint: {"risk": "paid", "available": True})
    with pytest.raises(HTTPException):
        inventory.read(models.AutomaticRead(revision=7, endpoint="getAgent", arguments={}), admin)
    assert calls == []


@pytest.mark.parametrize("change", ["version", "enabled", "revision", "schema", "live"])
def test_current_connection_provider_schema_and_session_rechecked_after_dispatch(
    fake, monkeypatch, change
):
    state, _, _, admin, request = fake

    def changing(path, body=None, timeout=3):
        result = request(path, body, timeout)
        if path == "/execute":
            state[change] = {
                "version": 2,
                "enabled": False,
                "revision": 8,
                "schema": "b" * 64,
                "live": False,
            }[change]
        return result

    monkeypatch.setattr(bridge, "request", changing)
    with pytest.raises(HTTPException):
        inventory.read(models.AutomaticRead(revision=7, endpoint="getAgent", arguments={}), admin)


def test_disabled_stale_and_expired_sessions_do_not_execute(fake):
    state, calls, _, admin, _ = fake
    state["enabled"] = False
    with pytest.raises(HTTPException):
        inventory.synchronize(models.Revision(revision=7), admin)
    assert not calls
    state["enabled"], state["live"] = True, False
    with pytest.raises(HTTPException):
        inventory.synchronize(models.Revision(revision=7), admin)
    assert not calls
    state["live"] = True
    with pytest.raises(HTTPException):
        inventory.synchronize(models.Revision(revision=8), admin)
    assert not any(path == "/execute" for path, _ in calls)


def test_partial_failure_keeps_successes_and_explicit_load_only_retries_missing(fake, monkeypatch):
    _, calls, _, admin, request = fake
    failing = [True]

    def partial(path, body=None, timeout=3):
        if path == "/execute" and body["endpoint"] == "listVoices" and failing[0]:
            raise HTTPException(503, "raw-secret-provider-error")
        return request(path, body, timeout)

    monkeypatch.setattr(bridge, "request", partial)
    result = inventory.synchronize(models.Revision(revision=7), admin)
    assert len(result["snapshots"]) == 10
    assert result["errors"] == [{"endpoint": "listVoices", "code": "retell_read_unavailable"}]
    failing[0] = False
    result = inventory.synchronize(models.Revision(revision=7), admin)
    assert len(result["snapshots"]) == 11 and result["errors"] == []
    assert len([1 for path, _ in calls if path == "/execute"]) == 11


def test_singleflight_and_three_reader_concurrency(fake, monkeypatch):
    _, calls, _, admin, request = fake
    started, release = Event(), Event()
    active, maximum = [0], [0]
    lock = Lock()

    def blocked(path, body=None, timeout=3):
        if path == "/execute":
            with lock:
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
                if active[0] == 3:
                    started.set()
            assert release.wait(10)
            with lock:
                active[0] -= 1
        return request(path, body, timeout)

    monkeypatch.setattr(bridge, "request", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(inventory.synchronize, models.Revision(revision=7), admin)
        assert started.wait(10)
        second = pool.submit(inventory.synchronize, models.Revision(revision=7), admin)
        release.set()
        assert len(first.result(timeout=15)["snapshots"]) == 11
        assert len(second.result(timeout=15)["snapshots"]) == 11
    assert maximum[0] == 3
    assert len([1 for path, _ in calls if path == "/execute"]) == 11


def test_cache_is_bounded_and_expired_snapshots_reload(fake, monkeypatch):
    _, _, _, admin, _ = fake
    clock = [100.0]
    monkeypatch.setattr(inventory, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        inventory,
        "_collect",
        lambda revision, owner, version, seed: {"snapshots": [], "partial": True, "errors": []},
    )
    for _ in range(140):
        inventory.synchronize(models.Revision(revision=7), {**admin, "id": uuid4()})
    assert inventory.cache_size() == 128
    assert inventory.synchronize(models.Revision(revision=7), admin)["cached"] is False
    assert inventory.synchronize(models.Revision(revision=7), admin)["cached"] is True
    clock[0] += 31
    assert inventory.synchronize(models.Revision(revision=7), admin)["cached"] is False


def test_routes_authentication_and_strict_inputs(fake):
    _, calls, _, admin, _ = fake
    with TestClient(app) as client:
        assert client.post("/crm/retell/inventory", json={"revision": 7}).status_code == 401
        assert (
            client.post(
                "/crm/retell/read", json={"revision": 7, "endpoint": "listAgents", "arguments": {}}
            ).status_code
            == 401
        )
    app.dependency_overrides[security.session] = lambda: admin
    try:
        with TestClient(app) as client:
            for path, body in [
                ("inventory", {"revision": 7}),
                ("read", {"revision": 7, "endpoint": "listAgents", "arguments": {}}),
            ]:
                assert client.post(f"/crm/retell/{path}?url=bad", json=body).status_code == 422
                assert (
                    client.post(
                        f"/crm/retell/{path}", json={**body, "consent_confirmed": True}
                    ).status_code
                    == 422
                )
                assert (
                    client.post(f"/crm/retell/{path}", json={**body, "revision": True}).status_code
                    == 422
                )
                assert client.get(f"/crm/retell/{path}").status_code == 405
            assert calls == []
            response = client.post("/crm/retell/inventory", json={"revision": 7})
            assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    finally:
        app.dependency_overrides.pop(security.session, None)


def test_completed_same_session_mutation_invalidates_inventory_cache(fake):
    state, calls, _, admin, _ = fake
    first = inventory.synchronize(models.Revision(revision=7), admin)
    assert first["cached"] is False
    state["mutation"] = 1
    assert inventory.synchronize(models.Revision(revision=7), admin)["cached"] is False
    assert len([1 for path, _ in calls if path == "/execute"]) == 22


def test_unavailable_resource_is_partial_not_an_all_inventory_failure(fake, monkeypatch):
    _, _, _, admin, _ = fake
    operation = service.operation

    def reviewed(endpoint):
        if endpoint == "listVoices":
            raise HTTPException(422, "retell_operation_unavailable")
        return operation(endpoint)

    monkeypatch.setattr(service, "operation", reviewed)
    result = inventory.synchronize(models.Revision(revision=7), admin)
    assert len(result["snapshots"]) == 10 and result["errors"][0]["endpoint"] == "listVoices"


@pytest.mark.parametrize(
    "arguments",
    [
        {"agent_id": "  https://attacker.invalid"},
        {"agent_id": "//attacker.invalid"},
        {"api-key": "private"},
    ],
)
def test_obfuscated_urls_and_secret_keys_never_reach_gateway(fake, arguments):
    _, calls, _, _, _ = fake
    with pytest.raises(ValidationError):
        models.AutomaticRead(revision=7, endpoint="getAgent", arguments=arguments)
    assert calls == []


def test_collector_deadline_cancels_queued_futures_without_waiting_for_pool_shutdown(
    fake, monkeypatch
):
    _, _, _, admin, _ = fake
    futures = []

    class PendingFuture(Future):
        def result(self, timeout=None):
            assert timeout is not None and 0 <= timeout <= 64
            raise TimeoutError

    class SharedPool:
        def submit(self, *args, **kwargs):
            future = PendingFuture()
            futures.append(future)
            return future

    monkeypatch.setattr(inventory, "_pool", SharedPool())
    result = inventory._collect(7, admin, 1, {})
    assert len(result["errors"]) == 11
    assert all(row["code"] == "retell_read_timeout" for row in result["errors"])
    assert all(future.cancelled() for future in futures)


def test_reader_budget_stops_late_followon_checks_and_sends_bounded_timeouts(fake, monkeypatch):
    _, _, _, admin, request = fake
    clock = [100.0]
    monkeypatch.setattr(inventory, "monotonic", lambda: clock[0])

    def slow(path, body=None, timeout=3):
        if path == "/prepare":
            assert 0 < timeout <= 1.5
        elif path == "/execute":
            assert 0 < timeout <= 8
        clock[0] += timeout
        return request(path, body, timeout)

    monkeypatch.setattr(bridge, "request", slow)
    with pytest.raises(HTTPException) as failure:
        inventory.read(models.AutomaticRead(revision=7, endpoint="getAgent", arguments={}), admin)
    assert failure.value.detail == "retell_read_timeout"
    assert clock[0] - 100 < 18


def test_cached_policy_changes_preserve_other_resources(fake, monkeypatch):
    _, _, _, admin, _ = fake
    inventory.synchronize(models.Revision(revision=7), admin)
    operation = service.operation

    def reviewed(endpoint):
        if endpoint == "listVoices":
            raise HTTPException(422, "retell_operation_unavailable")
        return operation(endpoint)

    monkeypatch.setattr(service, "operation", reviewed)
    result = inventory.synchronize(models.Revision(revision=7), admin)
    assert len(result["snapshots"]) == 10
    assert result["errors"] == [{"endpoint": "listVoices", "code": "retell_read_unavailable"}]
