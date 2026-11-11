"""Zernio boundary tests. All provider traffic is replaced with deterministic fixtures."""

import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.social import config, provider

PROFILE = "a" * 24
OTHER_PROFILE = "b" * 24
ORIGIN = "http://127.0.0.1:4320"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.crm.manage import migrate
    from app.crm.security import password_hash

    url = os.getenv("CRM_TEST_DATABASE_URL")
    owner = os.getenv("CRM_TEST_MIGRATION_DATABASE_URL")
    if not url or not owner:
        pytest.skip("Isolated CRM test database is required")
    for candidate in (url, owner):
        if psycopg.conninfo.conninfo_to_dict(candidate).get("dbname") != "jardines_crm_test":
            pytest.fail("Refusing to reset a database other than jardines_crm_test")
    migrate(owner)
    password = secrets.token_urlsafe(24)
    with psycopg.connect(owner) as db:
        db.execute("TRUNCATE crm.users, crm.login_limits, crm.contacts CASCADE")
        db.execute("TRUNCATE crm.social_connections, crm.social_state, crm.social_webhook_events")
        db.execute(
            "INSERT INTO crm.users(username, password_hash) VALUES (%s,%s)",
            ("socialadmin", password_hash.hash(password)),
        )
    monkeypatch.setenv("CRM_DATABASE_URL", url)
    monkeypatch.setenv("CRM_ORIGIN", ORIGIN)
    monkeypatch.setenv("CRM_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("ZERNIO_CONFIG_DIR", str(tmp_path / "private"))
    with TestClient(app, base_url=ORIGIN) as session:
        session.headers["Origin"] = ORIGIN
        response = session.post(
            "/crm/auth/login", json={"username": "socialadmin", "password": password}
        )
        session.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield session, owner


def vendor(monkeypatch, accounts=None):
    calls = []

    def request(credentials, method, path, payload=None):
        calls.append((method, path, payload))
        if path.startswith("/v1/profiles/"):
            return {"profile": {"_id": PROFILE, "name": "Jardines", "apiKey": "never-return"}}
        if path.startswith("/v1/accounts"):
            return {"accounts": accounts or []}
        if path.startswith("/v1/connect/telegram"):
            return {
                "code": "ABCD1234",
                "instructions": ["Connect the channel"],
                "expiresAt": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                "status": "pending",
            }
        return {"authUrl": "https://www.facebook.com/dialog/oauth?state=provider-state"}

    monkeypatch.setattr(provider, "request", request)
    return calls


def configured(client, monkeypatch, accounts=None):
    session, _ = client
    calls = vendor(monkeypatch, accounts)
    response = session.post(
        "/crm/social/settings", json={"api_key": "test-provider-secret", "profile_id": PROFILE}
    )
    assert response.status_code == 200, response.text
    return session, calls


def test_social_authentication_and_csrf(client, monkeypatch):
    session, _ = client
    assert session.get("/crm/social/settings").json()["configured"] is False
    session.headers["X-CSRF-Token"] = "wrong"
    assert session.post("/crm/social/sync", json={}).status_code == 403
    session.cookies.clear()
    assert session.get("/crm/social/settings").status_code == 401


def test_private_configuration_verification_and_explicit_replacement(client, monkeypatch):
    session, _ = configured(client, monkeypatch)
    file = Path(os.environ["ZERNIO_CONFIG_DIR"]) / "credentials.json"
    assert file.stat().st_mode & 0o777 == 0o600
    assert file.parent.stat().st_mode & 0o777 == 0o700
    previous = file.read_bytes()
    assert (
        session.post(
            "/crm/social/settings", json={"api_key": "other-secret", "profile_id": PROFILE}
        ).status_code
        == 409
    )
    assert file.read_bytes() == previous

    def failure(*args, **kwargs):
        from fastapi import HTTPException

        raise HTTPException(502, "zernio_unavailable")

    monkeypatch.setattr(provider, "request", failure)
    assert (
        session.post(
            "/crm/social/settings",
            json={"api_key": "bad-secret", "profile_id": PROFILE, "replace": True},
        ).status_code
        == 502
    )
    assert file.read_bytes() == previous
    response = session.get("/crm/social/settings")
    assert response.json()["profile"] == {"id": PROFILE, "name": "Jardines"}
    for secret in ("test-provider-secret", "never-return", "webhook_secret"):
        assert secret not in response.text


def account(id="account-1", profile=PROFILE, platform="facebook", **extra):
    return {
        "_id": id,
        "profileId": profile,
        "platform": platform,
        "username": "jardines",
        "displayName": "Jardines",
        "isActive": True,
        "accessToken": "never-store",
        **extra,
    }


def test_sync_is_profile_scoped_bounded_and_stores_no_tokens(client, monkeypatch):
    session, calls = configured(client, monkeypatch, [account(), account("foreign", OTHER_PROFILE)])
    response = session.post("/crm/social/sync", json={})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["connections"]] == ["account-1"]
    assert "never-store" not in response.text
    assert "profileId=" + PROFILE in calls[-1][1]
    with psycopg.connect(client[1]) as db:
        assert db.execute("SELECT count(*) FROM crm.social_connections").fetchone()[0] == 1
        assert "accessToken" not in str(
            db.execute("SELECT * FROM crm.social_connections").fetchall()
        )
    vendor(monkeypatch, [account(str(i)) for i in range(101)])
    response = session.post("/crm/social/sync", json={})
    assert len(response.json()["connections"]) <= 100
    assert response.json()["sync_warning"] is not None


def test_profile_validation_cannot_overwrite_configuration(client, monkeypatch):
    session, _ = configured(client, monkeypatch)
    file = Path(os.environ["ZERNIO_CONFIG_DIR"]) / "credentials.json"
    previous = file.read_bytes()
    monkeypatch.setattr(
        provider, "request", lambda *args, **kw: {"profile": {"_id": OTHER_PROFILE}}
    )
    response = session.post(
        "/crm/social/settings",
        json={"api_key": "new-secret", "profile_id": PROFILE, "replace": True},
    )
    assert response.status_code == 502
    assert file.read_bytes() == previous


def test_intent_callback_requires_new_verified_account_and_is_idempotent(client, monkeypatch):
    session, _ = configured(client, monkeypatch, [account()])
    session.post("/crm/social/sync", json={})
    started = session.post("/crm/social/connect/facebook", json={})
    assert started.status_code == 200, started.text
    intent = started.json()["intent_id"]
    assert (
        session.post("/crm/social/complete", json={"intent_id": intent}).json()["status"]
        == "pending"
    )
    vendor(monkeypatch, [account(), account("new-account")])
    response = session.post("/crm/social/complete", json={"intent_id": intent})
    assert response.json()["status"] == "connected"
    vendor(monkeypatch, [])
    assert (
        session.post("/crm/social/complete", json={"intent_id": intent}).json()["status"]
        == "connected"
    )


def test_intent_expiry_owner_and_unsafe_provider_redirect(client, monkeypatch):
    session, _ = configured(client, monkeypatch)
    started = session.post("/crm/social/connect/facebook", json={}).json()
    with psycopg.connect(client[1]) as db:
        db.execute("UPDATE crm.social_connection_intents SET session_hash='another-session'")
    assert (
        session.post("/crm/social/complete", json={"intent_id": started["intent_id"]}).status_code
        == 404
    )
    started = session.post("/crm/social/connect/facebook", json={}).json()
    with psycopg.connect(client[1]) as db:
        db.execute("UPDATE crm.social_connection_intents SET expires_at=now()-interval '1 second'")
    assert (
        session.post("/crm/social/complete", json={"intent_id": started["intent_id"]}).status_code
        == 410
    )
    monkeypatch.setattr(
        provider, "request", lambda *a, **kw: {"authUrl": "https://attacker.invalid/key"}
    )
    assert session.post("/crm/social/connect/facebook", json={}).status_code == 502


def test_telegram_code_only_and_completion_uses_stored_code(client, monkeypatch):
    session, calls = configured(client, monkeypatch)
    response = session.post("/crm/social/connect/telegram", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["auth_url"] is None and data["code"] == "ABCD1234"
    session.post("/crm/social/complete", json={"intent_id": data["intent_id"]})
    assert any(method == "PATCH" and "code=ABCD1234" in path for method, path, payload in calls)


def test_webhook_signature_durable_deduplication_and_scope(client, monkeypatch):
    session, _ = configured(client, monkeypatch)
    credentials = config.load()
    body = json.dumps(
        {
            "id": "evt-1",
            "event": "account.connected",
            "account": {
                "profileId": PROFILE,
                "platform": "facebook",
                "message": "private transcript",
            },
        }
    ).encode()

    def send(raw=body, event_id="evt-1", signature=None):
        signature = (
            signature
            or hmac.new(credentials["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest()
        )
        return session.post(
            "/integrations/zernio/webhook",
            content=raw,
            headers={
                "X-Zernio-Signature": signature,
                "X-Zernio-Event-Id": event_id,
                "X-Zernio-Event": "account.connected",
                "Content-Type": "application/json",
            },
        )

    assert send(signature="bad").status_code == 401
    assert send().status_code == 200
    assert send().status_code == 200
    assert send(body.replace(b"private transcript", b"different transcript")).status_code == 409
    assert send(event_id="evt-other").status_code == 400
    assert send(body.replace(PROFILE.encode(), OTHER_PROFILE.encode())).status_code == 403
    with psycopg.connect(client[1]) as db:
        assert db.execute("SELECT count(*) FROM crm.social_webhook_events").fetchone()[0] == 1
    state = session.get("/crm/social/settings")
    assert "private transcript" not in state.text
    assert state.json()["events"][0]["id"] == "evt-1"
    assert send(b"x" * (256 * 1024 + 1)).status_code == 413


def test_provider_http_boundary_has_no_redirects_or_raw_errors(monkeypatch):
    from fastapi import HTTPException

    seen = []

    class Response:
        status = 302

        def read(self, maximum):
            return b'{"error":"api-secret"}'

    class Connection:
        def __init__(self, host, timeout):
            seen.append((host, timeout))

        def request(self, method, path, **kwargs):
            seen.append((method, path, kwargs))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(provider.http.client, "HTTPSConnection", Connection)
    with pytest.raises(HTTPException) as error:
        provider.request({"api_key": "api-secret"}, "GET", "/v1/accounts")
    assert error.value.detail == "zernio_unavailable"
    assert seen[0] == ("zernio.com", 4)
    assert len(seen) == 2


def test_absent_configuration_and_invalid_input_never_echo_secrets(client, monkeypatch):
    session, _ = client
    monkeypatch.delenv("ZERNIO_CONFIG_DIR")
    assert session.get("/crm/social/settings").json()["configured"] is False
    assert session.post("/crm/social/sync", json={}).status_code == 503
    response = session.post(
        "/crm/social/settings",
        json={"api_key": "sensitive-invalid-value", "profile_id": "not-a-profile"},
    )
    assert response.status_code == 422
    assert "sensitive-invalid-value" not in response.text


def test_cursor_pagination_marks_partial_without_false_disconnections(client, monkeypatch):
    session, _ = configured(client, monkeypatch, [account("old-account")])
    session.post("/crm/social/sync", json={})
    monkeypatch.setattr(
        provider,
        "request",
        lambda *a, **kw: {
            "accounts": [account("new-account", profile={"_id": PROFILE})],
            "pagination": {"nextCursor": "next-page"},
        },
    )
    response = session.post("/crm/social/sync", json={})
    assert response.status_code == 200
    assert response.json()["sync_warning"] == "account_list_truncated"
    assert {a["id"]: a["status"] for a in response.json()["connections"]} == {
        "old-account": "connected",
        "new-account": "connected",
    }
    vendor(monkeypatch, [account("new-account", needsReconnection=True)])
    response = session.post("/crm/social/sync", json={})
    assert all(a["status"] == "disconnected" for a in response.json()["connections"])


def test_foreign_accounts_cannot_complete_an_intent(client, monkeypatch):
    session, _ = configured(client, monkeypatch)
    intent = session.post("/crm/social/connect/facebook", json={}).json()["intent_id"]
    vendor(
        monkeypatch,
        [account(profile=OTHER_PROFILE), account("wrong-platform", platform="instagram")],
    )
    response = session.post("/crm/social/complete", json={"intent_id": intent})
    assert response.status_code == 200 and response.json()["status"] == "pending"
    assert all(a["id"] != "account-1" for a in response.json()["settings"]["connections"])


def test_runtime_role_cannot_delete_or_change_customer_schema(client):
    _, owner = client
    with psycopg.connect(owner) as db:
        for table in (
            "social_connections",
            "social_state",
            "social_connection_intents",
            "social_webhook_events",
        ):
            assert (
                db.execute(
                    "SELECT has_table_privilege('jardines_crm_app', %s, 'DELETE')",
                    ("crm." + table,),
                ).fetchone()[0]
                is False
            )
        assert (
            db.execute(
                "SELECT has_table_privilege('jardines_crm_app', 'crm.social_webhook_events', 'UPDATE')"
            ).fetchone()[0]
            is False
        )
        fields = db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='crm' AND table_name='contacts'"
        ).fetchall()
        assert {field[0] for field in fields} == {
            "id",
            "name",
            "phone",
            "source",
            "version",
            "created_at",
            "updated_at",
        }


def test_signed_test_event_and_database_failure_never_acknowledges(client, monkeypatch):
    from app.social import routes

    session, _ = configured(client, monkeypatch)
    secret = config.load()["webhook_secret"]

    def send(payload):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return session.post(
            "/integrations/zernio/webhook",
            content=body,
            headers={
                "X-Zernio-Signature": signature,
                "X-Zernio-Event-Id": payload["id"],
                "X-Zernio-Event": payload["event"],
            },
        )

    payload = {"id": "test-event", "event": "webhook.test"}
    real_connect = routes.connect

    def unavailable():
        raise psycopg.OperationalError("private database detail")

    monkeypatch.setattr(routes, "connect", unavailable)
    response = send(payload)
    assert response.status_code == 503 and "private database detail" not in response.text
    monkeypatch.setattr(routes, "connect", real_connect)
    assert send(payload).status_code == 200
    assert session.get("/crm/social/settings").json()["events"][0]["event"] == "webhook.test"


@pytest.mark.parametrize(
    "url",
    [
        "http://zernio.com/connect",
        "https://zernio.com.attacker.invalid/connect",
        "https://user@facebook.com/connect",
        "https://facebook.com:8443/connect",
        "https://evilfacebook.com/connect",
    ],
)
def test_authorization_url_rejects_host_confusion(url):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        provider.auth_url(url)


def test_configuration_rejects_symlink_and_weak_permissions(client, monkeypatch, tmp_path):
    session, _ = configured(client, monkeypatch)
    folder = Path(os.environ["ZERNIO_CONFIG_DIR"])
    file = folder / "credentials.json"
    file.chmod(0o644)
    assert session.get("/crm/social/settings").status_code == 503
    file.chmod(0o600)
    file.rename(folder / "actual.json")
    file.symlink_to(folder / "actual.json")
    assert session.get("/crm/social/settings").status_code == 503


def test_credential_replacement_invalidates_existing_intents(client, monkeypatch):
    session, _ = configured(client, monkeypatch)
    intent = session.post("/crm/social/connect/facebook", json={}).json()["intent_id"]
    response = session.post(
        "/crm/social/settings",
        json={"api_key": "replacement-provider-key", "profile_id": PROFILE, "replace": True},
    )
    assert response.status_code == 200
    assert session.post("/crm/social/complete", json={"intent_id": intent}).status_code == 404


def test_simultaneous_initial_configuration_does_not_implicitly_replace(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    session, _ = client
    vendor(monkeypatch)

    def configure(index):
        return session.post(
            "/crm/social/settings",
            json={"api_key": f"concurrent-provider-key-{index}", "profile_id": PROFILE},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(configure, [1, 2]))
    assert sorted(statuses) == [200, 409]


@pytest.mark.parametrize("operation", ["sync", "connect", "complete", "telegram_complete"])
def test_credential_rotation_serializes_provider_and_state_mutations(
    client, monkeypatch, operation
):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event

    session, _ = configured(client, monkeypatch)
    platform = "telegram" if operation == "telegram_complete" else "facebook"
    intent = session.post(f"/crm/social/connect/{platform}", json={}).json()["intent_id"]
    real_required, real_locked = config.required, config.locked
    vendor(monkeypatch, [account("new-account", platform=platform)])
    real_request = provider.request
    loaded, release, rotation_attempted, rotation_verified = (Event() for _ in range(4))
    observed = []
    provider_order = []

    def paused_required():
        credentials = real_required()
        loaded.set()
        assert release.wait(8)
        return credentials

    @contextmanager
    def observed_locked():
        if loaded.is_set():
            rotation_attempted.set()
        with real_locked():
            yield

    def recorded_request(credentials, method, path, payload=None):
        if path.startswith("/v1/profiles/"):
            with psycopg.connect(client[1]) as db:
                observed.append(
                    db.execute(
                        "SELECT count(*) FROM crm.social_connections WHERE account_id='new-account'"
                    ).fetchone()[0]
                )
                if operation in {"complete", "telegram_complete"}:
                    observed.append(
                        db.execute(
                            "SELECT state FROM crm.social_connection_intents WHERE id=%s", (intent,)
                        ).fetchone()[0]
                    )
            provider_order.append("rotation")
            rotation_verified.set()
        if method == "PATCH":
            provider_order.append("telegram_poll")
            return {
                "status": "connected",
                "account": {"_id": "new-account", "platform": "telegram"},
            }
        return real_request(credentials, method, path, payload)

    monkeypatch.setattr(config, "required", paused_required)
    monkeypatch.setattr(config, "locked", observed_locked)
    monkeypatch.setattr(provider, "request", recorded_request)
    path = {"sync": "/crm/social/sync", "connect": "/crm/social/connect/facebook"}.get(
        operation, "/crm/social/complete"
    )
    payload = {"intent_id": intent} if operation in {"complete", "telegram_complete"} else {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation = pool.submit(lambda: session.post(path, json=payload))
        try:
            assert loaded.wait(8)
            rotation = pool.submit(
                lambda: session.post(
                    "/crm/social/settings",
                    json={
                        "api_key": "replacement-provider-key",
                        "profile_id": PROFILE,
                        "replace": True,
                    },
                )
            )
            assert rotation_attempted.wait(8)
            # A broken implementation lets rotation verify while the old operation is paused.
            # A serialized implementation keeps it waiting until this operation is released.
            rotation_verified.wait(1)
        finally:
            release.set()
        mutation_response = mutation.result(timeout=8)
        rotation_response = rotation.result(timeout=8)
    assert mutation_response.status_code == 200
    assert rotation_response.status_code == 200
    assert observed[0] == 1, "Rotation committed before the earlier mutation finished"
    if operation in {"complete", "telegram_complete"}:
        assert observed[1] == "completed"
    if operation == "telegram_complete":
        assert provider_order == ["telegram_poll", "rotation"]
