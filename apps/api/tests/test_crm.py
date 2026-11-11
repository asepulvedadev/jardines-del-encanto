"""Public API regression tests; database tests require an isolated PostgreSQL database."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app

ORIGIN = "http://127.0.0.1:4320"


def test_crm_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/crm/workspace")
        assert response.status_code == 401
        assert response.json() == {"detail": "authentication_required"}


@pytest.fixture
def authenticated(monkeypatch):
    url = os.getenv("CRM_TEST_DATABASE_URL")
    owner_url = os.getenv("CRM_TEST_MIGRATION_DATABASE_URL")
    if not url or not owner_url:
        pytest.skip("Set isolated CRM_TEST_DATABASE_URL and CRM_TEST_MIGRATION_DATABASE_URL")
    for candidate in (url, owner_url):
        if psycopg.conninfo.conninfo_to_dict(candidate).get("dbname") != "jardines_crm_test":
            pytest.fail("Refusing to reset any database other than jardines_crm_test")
    from app.crm.manage import migrate
    from app.crm.security import password_hash

    migrate(owner_url)
    password = secrets.token_urlsafe(24)
    with psycopg.connect(owner_url) as db:
        db.execute("TRUNCATE crm.users, crm.login_limits, crm.contacts CASCADE")
        db.execute(
            "INSERT INTO crm.users (username, password_hash) VALUES (%s, %s)",
            ("testadmin", password_hash.hash(password)),
        )
    monkeypatch.setenv("CRM_DATABASE_URL", url)
    monkeypatch.setenv("CRM_ORIGIN", ORIGIN)
    monkeypatch.setenv("CRM_ALLOW_INSECURE_HTTP", "1")
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/crm/auth/login",
            headers={"Origin": ORIGIN},
            json={"username": "testadmin", "password": password},
        )
        assert response.status_code == 200
        csrf = response.json()["csrf_token"]
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
        yield client, owner_url, password


def customer(client, phone="3001234567"):
    response = client.post(
        "/crm/contacts",
        json={
            "name": "Cliente de prueba",
            "phone": phone,
            "source": "web",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_customer_has_only_three_business_fields_and_creates_pipeline_entry(authenticated):
    client, _, _ = authenticated
    record = customer(client)
    assert record["name"] == "Cliente de prueba"
    assert record["phone"] == "+573001234567"
    assert record["source"] == "web"
    state = client.get("/crm/workspace").json()
    assert len(state["contacts"]) == 1
    assert len(state["deals"]) == 1
    assert state["deals"][0]["contact_id"] == record["id"]
    assert state["deals"][0]["stage"] == "new"
    assert (
        client.post(
            "/crm/contacts",
            json={"name": "Otro", "phone": "3001234567", "source": "web", "email": "not-collected"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/crm/contacts", json={"name": "Otro", "phone": "3001234567", "source": "web"}
        ).status_code
        == 409
    )


def test_pipeline_move_is_persisted_and_conflicts_preserve_data(authenticated):
    client, _, _ = authenticated
    customer(client)
    deal = client.get("/crm/workspace").json()["deals"][0]
    path = f"/crm/deals/{deal['id']}"
    moved = client.patch(path, json={"stage": "contacted", "version": deal["version"]})
    assert moved.status_code == 200
    assert moved.json()["stage"] == "contacted"
    before = client.get("/crm/workspace").json()
    assert client.patch(path, json={"stage": "won", "version": deal["version"]}).status_code == 409
    assert client.get("/crm/workspace").json() == before
    assert client.patch(path, json={"stage": "invalid", "version": 2}).status_code == 422
    assert client.get("/crm/workspace").json() == before


def test_contact_edit_note_and_followup_survive_a_new_session(authenticated):
    client, _, password = authenticated
    contact = customer(client)
    contact = client.patch(
        f"/crm/contacts/{contact['id']}",
        json={
            "name": "Nombre actualizado",
            "phone": "3007654321",
            "source": "in_person",
            "version": contact["version"],
        },
    ).json()
    deal = client.get("/crm/workspace").json()["deals"][0]
    assert (
        client.post(f"/crm/deals/{deal['id']}/notes", json={"body": "Llamar mañana"}).status_code
        == 201
    )
    task = client.post(
        "/crm/tasks",
        json={
            "contact_id": contact["id"],
            "title": "Confirmar visita",
            "due_date": date.today().isoformat(),
        },
    )
    assert task.status_code == 201
    task = task.json()
    result = client.patch(
        f"/crm/tasks/{task['id']}", json={"completed": True, "version": task["version"]}
    )
    assert result.status_code == 200
    assert result.json()["completed"] is True
    assert client.post("/crm/auth/logout").status_code == 200
    assert client.get("/crm/workspace").status_code == 401
    response = client.post("/crm/auth/login", json={"username": "testadmin", "password": password})
    assert response.status_code == 200
    state = client.get("/crm/workspace").json()
    assert state["contacts"][0]["name"] == "Nombre actualizado"
    assert state["tasks"][0]["completed"] is True
    assert any(a["body"] == "Llamar mañana" for a in state["activities"])


def test_mutations_require_origin_and_csrf_and_logout_revokes_session(authenticated):
    client, _, _ = authenticated
    cookie = client.cookies.get("jardines_session")
    payload = {"name": "Rechazado", "phone": "3001234567", "source": "web"}
    before = client.get("/crm/workspace").json()
    assert (
        client.post(
            "/crm/contacts", json=payload, headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post("/crm/contacts", json=payload, headers={"X-CSRF-Token": "invalid"}).status_code
        == 403
    )
    assert client.get("/crm/workspace").json() == before
    assert client.post("/crm/auth/logout").status_code == 200
    client.cookies.set("jardines_session", cookie)
    assert client.get("/crm/workspace").status_code == 401


def test_session_expiry_and_disabled_admin_are_enforced(authenticated):
    client, owner, _ = authenticated
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.sessions SET expires_at = now() - interval '1 second'")
    assert client.get("/crm/workspace").status_code == 401


def test_login_throttles_and_never_returns_password_or_hash(authenticated):
    client, _, _ = authenticated
    client.post("/crm/auth/logout")
    for _ in range(5):
        result = client.post(
            "/crm/auth/login", json={"username": "unknown", "password": "not-a-password"}
        )
        assert result.status_code == 401
        assert "not-a-password" not in result.text
        assert "argon2" not in result.text
    assert (
        client.post(
            "/crm/auth/login", json={"username": "unknown", "password": "not-a-password"}
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/crm/auth/login",
            headers={"Origin": "https://attacker.invalid"},
            json={"username": "testadmin", "password": "test"},
        ).status_code
        == 403
    )


def test_secure_cookie_session_storage_and_cache_policy(authenticated, monkeypatch):
    client, owner, password = authenticated
    raw_cookie = client.cookies.get("jardines_session")
    with psycopg.connect(owner) as db:
        hashes = db.execute("SELECT token_hash FROM crm.sessions").fetchall()
        user_hash = db.execute(
            "SELECT password_hash FROM crm.users WHERE username='testadmin'"
        ).fetchone()[0]
    assert all(value[0] != raw_cookie for value in hashes)
    assert user_hash.startswith("$argon2id$")
    assert password not in user_hash
    response = client.get("/crm/workspace")
    assert response.headers["cache-control"] == "no-store, private"
    monkeypatch.setenv("CRM_ORIGIN", "https://crm.example.invalid")
    monkeypatch.delenv("CRM_ALLOW_INSECURE_HTTP")
    response = client.post(
        "/crm/auth/login",
        headers={"Origin": "https://crm.example.invalid"},
        json={"username": "testadmin", "password": password},
    )
    assert response.status_code == 200
    header = response.headers["set-cookie"]
    assert header.startswith("__Host-jardines_session=")
    assert "Secure" in header and "HttpOnly" in header and "SameSite=lax" in header
    assert "Domain=" not in header


def test_disabled_admin_and_idle_session_are_rejected(authenticated):
    client, owner, _ = authenticated
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.users SET enabled=false")
    assert client.get("/crm/workspace").status_code == 401
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.users SET enabled=true")
        db.execute("UPDATE crm.sessions SET last_seen = now() - interval '31 minutes'")
    assert client.get("/crm/workspace").status_code == 401


def test_runtime_role_cannot_modify_schema_users_or_history(authenticated):
    client, _, _ = authenticated
    customer(client)
    from app.crm.database import connect

    for statement in [
        "CREATE TABLE crm.forbidden (id int)",
        "DELETE FROM crm.users",
        "UPDATE crm.activities SET body='altered'",
        "DELETE FROM crm.contacts",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as db:
            db.execute(statement)


@pytest.mark.parametrize(
    "source", ["in_person", "social_campaign", "web", "referral", "whatsapp", "other"]
)
def test_all_supported_acquisition_channels_persist(authenticated, source):
    client, _, _ = authenticated
    response = client.post(
        "/crm/contacts", json={"name": "Prueba de origen", "phone": "3009876543", "source": source}
    )
    assert response.status_code == 201
    assert client.get("/crm/workspace").json()["contacts"][0]["source"] == source


def test_concurrent_updates_accept_only_one_version(authenticated):
    client, _, _ = authenticated
    customer(client)
    before = client.get("/crm/workspace").json()
    deal = before["deals"][0]
    cookies, headers = dict(client.cookies), dict(client.headers)

    def move(stage):
        with TestClient(app, cookies=cookies, headers=headers) as other:
            return other.patch(
                f"/crm/deals/{deal['id']}", json={"stage": stage, "version": deal["version"]}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(move, ["contacted", "won"]))
    assert sorted(results) == [200, 409]
    after = client.get("/crm/workspace").json()
    assert after["deals"][0]["version"] == 2
    assert len(after["activities"]) == len(before["activities"]) + 1


def test_contact_and_task_stale_rejections_leave_business_state_identical(authenticated):
    client, _, _ = authenticated
    contact = customer(client)
    contact_path = f"/crm/contacts/{contact['id']}"
    payload = {"name": "Updated", "phone": contact["phone"], "source": "other", "version": 1}
    assert client.patch(contact_path, json=payload).status_code == 200
    before = client.get("/crm/workspace").json()
    assert (
        client.patch(contact_path, json={**payload, "name": "Should not persist"}).status_code
        == 409
    )
    assert client.get("/crm/workspace").json() == before
    task = client.post(
        "/crm/tasks",
        json={"contact_id": contact["id"], "title": "Test task", "due_date": "2026-11-11"},
    ).json()
    path = f"/crm/tasks/{task['id']}"
    assert client.patch(path, json={"completed": True, "version": 1}).status_code == 200
    before = client.get("/crm/workspace").json()
    assert client.patch(path, json={"completed": False, "version": 1}).status_code == 409
    assert client.get("/crm/workspace").json() == before


def test_activity_failure_rolls_back_customer_and_deal(authenticated, monkeypatch):
    client, _, _ = authenticated
    from app.crm import routes

    before = client.get("/crm/workspace").json()

    def fail(*args, **kwargs):
        raise psycopg.errors.CheckViolation("independent fault injection")

    monkeypatch.setattr(routes, "activity", fail)
    response = client.post(
        "/crm/contacts", json={"name": "Must rollback", "phone": "3006543210", "source": "web"}
    )
    assert response.status_code == 503
    assert "fault" not in response.text
    assert client.get("/crm/workspace").json() == before


@pytest.mark.parametrize("removed_stage", ["visit", "negotiation", "lost"])
def test_pipeline_rejects_removed_stages_without_changing_state(authenticated, removed_stage):
    client, _, _ = authenticated
    customer(client)
    before = client.get("/crm/workspace").json()
    deal = before["deals"][0]
    response = client.patch(
        f"/crm/deals/{deal['id']}", json={"stage": removed_stage, "version": deal["version"]}
    )
    assert response.status_code == 422
    assert client.get("/crm/workspace").json() == before


def test_database_rejects_removed_pipeline_stages(authenticated):
    client, url, _ = authenticated
    customer(client)
    deal = client.get("/crm/workspace").json()["deals"][0]
    for stage in ("visit", "negotiation", "lost"):
        with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(url) as db:
            db.execute("UPDATE crm.deals SET stage=%s WHERE id=%s", (stage, deal["id"]))


def test_three_stage_migration_refuses_to_reclassify_legacy_records(authenticated):
    from pathlib import Path

    client, url, _ = authenticated
    customer(client)
    deal = client.get("/crm/workspace").json()["deals"][0]
    migration = (Path(__file__).parents[1] / "migrations/004_three_pipeline_stages.sql").read_text()
    with psycopg.connect(url) as db:
        try:
            db.execute("ALTER TABLE crm.deals DROP CONSTRAINT deals_stage_check")
            db.execute("UPDATE crm.deals SET stage='visit' WHERE id=%s", (deal["id"],))
            db.execute("SAVEPOINT before_reduction")
            with pytest.raises(psycopg.errors.RaiseException):
                db.execute(migration)
            db.execute("ROLLBACK TO SAVEPOINT before_reduction")
            assert (
                db.execute("SELECT stage FROM crm.deals WHERE id=%s", (deal["id"],)).fetchone()[0]
                == "visit"
            )
        finally:
            db.rollback()
    assert client.get("/crm/workspace").json()["deals"][0]["stage"] == "new"
