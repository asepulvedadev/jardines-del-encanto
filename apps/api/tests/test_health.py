from unittest.mock import patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def database_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("CRM_DATABASE_URL", raising=False)
    secret = tmp_path / "db_password"
    secret.write_text("unit-test-only")
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret))


def test_liveness_has_no_database_dependency():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_fails_closed_when_database_unavailable():
    with patch(
        "app.main.psycopg.connect",
        side_effect=psycopg.OperationalError("private connection details"),
    ):
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "private" not in response.text


def test_readiness_checks_database():
    with patch("app.main.psycopg.connect") as connect:
        response = client.get("/health/ready")
    assert response.status_code == 200
    connect.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")


def test_no_crm_or_api_docs_exposed():
    for path in ["/customers", "/docs", "/openapi.json"]:
        assert client.get(path).status_code == 404


def test_crm_readiness_checks_configured_schema(monkeypatch):
    monkeypatch.setenv("CRM_DATABASE_URL", "postgresql://runtime@localhost/isolated")
    with patch("app.main.psycopg.connect") as connect:
        response = client.get("/health/ready")
    assert response.status_code == 200
    connect.return_value.__enter__.return_value.execute.assert_called_once_with(
        "SELECT 1 FROM crm.contacts LIMIT 1"
    )
