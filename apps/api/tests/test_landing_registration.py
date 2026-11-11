"""Anonymous capture tests against the isolated jardines_crm_test database only."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_crm import ORIGIN, authenticated  # noqa: F401

from app.main import app

PATH = "/public/registrations"
PAYLOAD = {"name": "Persona de prueba", "phone": "3001234567", "consent": True}


def submit(body=None, headers=None):
    with TestClient(app, base_url=ORIGIN) as client:
        return client.post(PATH, json=body or PAYLOAD, headers=headers or {"Origin": ORIGIN})


@pytest.fixture
def capture_db(authenticated):  # noqa: F811 - imported shared pytest fixture
    _, url, _ = authenticated
    with psycopg.connect(url) as db:
        db.execute("TRUNCATE crm.landing_limits")
    return authenticated


def test_public_capture_creates_web_lead_and_persistent_cupo(capture_db):
    admin, _, _ = capture_db
    response = submit()
    assert response.status_code == 201
    assert set(response.json()) == {"code"}
    code = response.json()["code"]
    assert code.startswith("JDE-") and len(code) == 16
    assert response.headers["cache-control"] == "no-store, private"
    state = admin.get("/crm/workspace").json()
    assert len(state["contacts"]) == len(state["deals"]) == 1
    assert state["contacts"][0]["source"] == "web"
    assert state["contacts"][0]["phone"] == "+573001234567"
    assert state["contacts"][0]["registration_code"] == code
    assert state["deals"][0]["stage"] == "new"
    assert submit({**PAYLOAD, "phone": "+57 (300) 123-4567"}).json() == {"code": code}
    assert admin.get("/crm/workspace").json() == state
    with TestClient(app) as client:
        assert client.get("/crm/workspace").status_code == 401
        assert client.get(PATH).status_code == 405


def test_parallel_capture_is_unique_and_does_not_overwrite_existing_contact(capture_db):
    admin, _, _ = capture_db
    record = admin.post(
        "/crm/contacts",
        json={"name": "Nombre original", "phone": PAYLOAD["phone"], "source": "in_person"},
    ).json()
    deal = admin.get("/crm/workspace").json()["deals"][0]
    admin.patch(f"/crm/deals/{deal['id']}", json={"stage": "won", "version": 1})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(), range(4)))
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["code"] for r in responses}) == 1
    state = admin.get("/crm/workspace").json()
    assert len(state["contacts"]) == len(state["deals"]) == 1
    assert state["contacts"][0]["name"] == record["name"]
    assert state["contacts"][0]["source"] == "in_person"
    assert state["deals"][0]["stage"] == "won"


def test_rejections_do_not_create_records_or_echo_private_input(capture_db):
    admin, _, _ = capture_db
    before = admin.get("/crm/workspace").json()
    for body in [
        {**PAYLOAD, "consent": False},
        {**PAYLOAD, "consent": 1},
        {**PAYLOAD, "phone": "bad"},
        {**PAYLOAD, "email": "private@example.invalid"},
        {**PAYLOAD, "website": "spam"},
    ]:
        response = submit(body)
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_input"}
    assert submit(headers={"Origin": "https://evil.invalid"}).status_code == 403
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post(PATH, json=PAYLOAD).status_code == 403
        assert (
            client.post(
                PATH,
                content="x" * 2100,
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert (
            client.post(
                PATH, content="{}", headers={"Origin": ORIGIN, "Content-Type": "text/plain"}
            ).status_code
            == 415
        )
    assert admin.get("/crm/workspace").json() == before


def test_throttle_is_durable_and_does_not_create_leads(capture_db):
    admin, url, _ = capture_db
    # The fixture has already validated this isolated database name before any writes.
    with psycopg.connect(url) as db:
        db.execute("INSERT INTO crm.landing_limits(key, attempts) VALUES ('global', 100)")
    assert submit().status_code == 429
    assert admin.get("/crm/workspace").json()["counts"]["contacts"] == 0


def test_concurrent_new_phone_creates_one_record(capture_db):
    admin, _, _ = capture_db
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(), range(4)))
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["code"] for r in responses}) == 1
    state = admin.get("/crm/workspace").json()
    assert len(state["contacts"]) == len(state["deals"]) == 1


def test_code_collision_retries_and_exhaustion_rolls_back(capture_db, monkeypatch):
    from app.crm import landing

    admin, _, _ = capture_db
    original = submit().json()["code"]
    monkeypatch.setattr(landing.secrets, "token_hex", lambda _: original[4:].lower())
    other = {**PAYLOAD, "phone": "3001234568"}
    before = admin.get("/crm/workspace").json()
    assert submit(other).status_code == 503
    assert admin.get("/crm/workspace").json() == before
    values = iter([original[4:].lower(), "123456abcdef"])
    monkeypatch.setattr(landing.secrets, "token_hex", lambda _: next(values))
    response = submit(other)
    assert response.status_code == 201
    assert response.json() == {"code": "JDE-123456ABCDEF"}
    assert len(admin.get("/crm/workspace").json()["contacts"]) == 2
