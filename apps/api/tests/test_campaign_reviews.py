"""Review submissions use synthetic accounts and never contact Zernio or Meta."""

# ruff: noqa: F811
from copy import deepcopy

import pytest
from fastapi import HTTPException
from test_campaigns import document
from test_crm import authenticated  # noqa: F401

from app.campaigns import reviews
from app.campaigns.models import Document

ACCOUNT = "a" * 24
CREDS = {"api_key": "synthetic-secret", "profile_id": "b" * 24}


@pytest.fixture
def provider(monkeypatch):
    calls = []
    monkeypatch.setattr(reviews.config, "required", lambda: CREDS)
    monkeypatch.setattr(
        reviews, "accounts", lambda credentials: [{"id": ACCOUNT, "label": "WhatsApp de prueba"}]
    )
    monkeypatch.setenv("CAMPAIGN_MEDIA_ORIGIN", "https://media.example.invalid")

    def request(credentials, method, path, payload=None):
        calls.append((method, path, deepcopy(payload)))
        if method == "POST":
            return {
                "success": True,
                "template": {
                    "id": "123456",
                    "name": payload["name"],
                    "language": "es_CO",
                    "status": "PENDING",
                    "category": "MARKETING",
                },
            }
        return {"success": True, "templates": []}

    monkeypatch.setattr(reviews, "request", request)
    return calls


def saved(client):
    response = client.post("/crm/campaigns", json={"document": document()})
    assert response.status_code == 201
    return response.json()


def test_review_payload_preserves_named_body_image_and_grouped_buttons():
    doc = Document.model_validate(document())
    payload = reviews.payload(
        doc, ACCOUNT, "jardines_test", "https://media.example.invalid/sample.png"
    )
    assert payload["parameter_format"] == "NAMED"
    assert payload["category"] == "MARKETING" and payload["language"] == "es_CO"
    header, body, buttons = payload["components"]
    assert header["example"]["header_handle"] == ["https://media.example.invalid/sample.png"]
    assert body["text"] == doc.body
    assert body["example"]["body_text_named_params"][0] == {
        "param_name": "nombre",
        "example": "María",
    }
    # Full-link variables freeze their origin; only a suffix remains dynamic.
    assert buttons["buttons"][0] == {
        "type": "url",
        "text": "Ver proyecto",
        "url": "https://jardinesdelencanto.site/{{1}}",
        "example": ["?"],
    }
    assert buttons["buttons"][1] == {"type": "quick_reply", "text": "Quiero información"}


def test_review_requires_explicit_confirmation_saved_version_and_csrf(authenticated, provider):
    client, _, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    data = {"version": item["version"], "account_id": ACCOUNT}
    preview = client.post(base + "/review-preview", json=data)
    assert preview.status_code == 200, preview.text
    assert preview.json()["name"].startswith("jardines_")
    assert provider == []
    assert client.post(base + "/reviews", json=data).status_code == 422
    assert client.post(base + "/reviews", json={**data, "confirm": False}).status_code == 422
    assert (
        client.post(
            base + "/reviews", json={**data, "confirm": True}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.post(base + "/reviews", json={**data, "version": 999, "confirm": True}).status_code
        == 409
    )
    assert provider == []


def test_review_submits_once_persists_snapshot_and_shares_only_selected_image(
    authenticated, provider
):
    client, _, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    data = {"version": 1, "account_id": ACCOUNT, "confirm": True}
    response = client.post(base + "/reviews", json=data)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "PENDING" and row["version"] == 1
    assert "token" not in response.text and "synthetic-secret" not in response.text
    assert len(provider) == 1 and provider[0][0] == "POST"
    url = provider[0][2]["components"][0]["example"]["header_handle"][0]
    path = url.removeprefix("https://media.example.invalid/api")
    # Capability URL works without a session, private originals still require one.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        media = anonymous.get(path)
        assert media.status_code == 200 and media.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert media.headers["cache-control"].startswith("no-store")
        assert anonymous.get(path[:-1] + ("a" if path[-1] != "a" else "b")).status_code == 404
        assert anonymous.get("/crm/campaigns/media/campaign-01").status_code == 401
    assert client.post(base + "/reviews", json=data).status_code == 409
    assert len(provider) == 1
    assert client.get(base + "/reviews").json()["items"][0]["id"] == row["id"]
    changed = document()
    changed["body"] = "Texto editado sin modificar la versión enviada."
    assert client.patch(base, json={"version": 1, "document": changed}).status_code == 200
    history = client.get(base + "/reviews").json()["items"][0]
    assert history["version"] == 1 and history["snapshot"]["body"] == document()["body"]


def test_unknown_outcome_blocks_retry_and_refresh_is_read_only(
    authenticated, provider, monkeypatch
):
    client, _, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"

    def unknown(*args, **kwargs):
        raise HTTPException(502, "review_provider_unavailable")

    monkeypatch.setattr(reviews, "request", unknown)
    result = client.post(
        base + "/reviews", json={"version": 1, "account_id": ACCOUNT, "confirm": True}
    )
    assert result.status_code == 201 and result.json()["status"] == "UNKNOWN"
    assert (
        client.post(
            base + "/reviews", json={"version": 1, "account_id": ACCOUNT, "confirm": True}
        ).status_code
        == 409
    )
    row = result.json()

    def lookup(credentials, method, path, payload=None):
        assert method == "GET" and payload is None
        return {
            "success": True,
            "templates": [
                {
                    "id": "9988",
                    "name": row["name"],
                    "language": "es_CO",
                    "status": "APPROVED",
                    "category": "MARKETING",
                }
            ],
        }

    monkeypatch.setattr(reviews, "request", lookup)
    updated = client.post(base + f"/reviews/{row['id']}/refresh", json={})
    assert updated.status_code == 200 and updated.json()["status"] == "APPROVED"


def test_media_expiry_snapshot_hash_and_read_authentication(authenticated, provider):
    import psycopg
    from fastapi.testclient import TestClient

    from app.main import app

    client, owner_url, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    row = client.post(
        base + "/reviews", json={"version": 1, "account_id": ACCOUNT, "confirm": True}
    ).json()
    path = provider[0][2]["components"][0]["example"]["header_handle"][0].removeprefix(
        "https://media.example.invalid/api"
    )
    with TestClient(app) as anonymous:
        assert anonymous.get(base + "/reviews").status_code == 401
        assert anonymous.get("/crm/campaigns/review-accounts").status_code == 401
        assert (
            anonymous.post(
                base + "/reviews", json={"version": 1, "account_id": ACCOUNT, "confirm": True}
            ).status_code
            == 401
        )
        with psycopg.connect(owner_url) as db:
            db.execute(
                "UPDATE crm.campaign_reviews SET image_sha256=%s WHERE id=%s", ("0" * 64, row["id"])
            )
        assert anonymous.get(path).status_code == 404
        with psycopg.connect(owner_url) as db:
            db.execute(
                "UPDATE crm.campaign_reviews SET media_expires_at=now()-interval '1 second' WHERE id=%s",
                (row["id"],),
            )
        assert anonymous.get(path).status_code == 404


def test_parallel_submission_reserves_before_network_and_never_duplicates(
    authenticated, provider, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    client, owner_url, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    original = reviews.request

    def observed(*args, **kwargs):
        with psycopg.connect(owner_url) as db:
            assert (
                db.execute(
                    "SELECT status FROM crm.campaign_reviews WHERE slug=%s", (item["id"],)
                ).fetchone()[0]
                == "SUBMITTING"
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(reviews, "request", observed)
    data = {"version": 1, "account_id": ACCOUNT, "confirm": True}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda _: client.post(base + "/reviews", json=data), range(2))
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert len(provider) == 1


def test_reviewer_validation_and_profile_isolation_preserve_local_draft(
    authenticated, provider, monkeypatch
):
    client, _, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    data = {"version": 1, "account_id": ACCOUNT, "confirm": True}
    assert client.post(base + "/reviews", json={**data, "confirm": "true"}).status_code == 422
    assert client.post(base + "/reviews", json={**data, "account_id": "other"}).status_code == 422
    monkeypatch.setenv("CAMPAIGN_MEDIA_ORIGIN", "http://localhost:4320")
    assert client.post(base + "/reviews", json=data).status_code == 422
    assert provider == [] and client.get(base + "/reviews").json()["items"] == []
    monkeypatch.setenv("CAMPAIGN_MEDIA_ORIGIN", "https://media.example.invalid")
    row = client.post(base + "/reviews", json=data).json()
    before = client.get(base + "/reviews").json()
    monkeypatch.setattr(reviews.config, "required", lambda: {**CREDS, "profile_id": "c" * 24})
    assert client.post(base + f"/reviews/{row['id']}/refresh", json={}).status_code == 409
    assert client.get(base + "/reviews").json() == before
    assert len(provider) == 1


def test_dynamic_link_example_preserves_query_and_button_group_errors():
    doc = document()
    doc["variables"][1]["example"] = "https://jardinesdelencanto.site?ref=visita#info"
    result = reviews.payload(
        Document.model_validate(doc),
        ACCOUNT,
        "jardines_test",
        "https://media.example.invalid/a.png",
    )
    assert result["components"][-1]["buttons"][0]["example"] == ["?ref=visita#info"]
    doc["buttons"].append({"kind": "url", "label": "Otro enlace", "value": "{{enlace_proyecto}}"})
    with pytest.raises(HTTPException, match="review_button_groups_required"):
        reviews.payload(
            Document.model_validate(doc),
            ACCOUNT,
            "jardines_test",
            "https://media.example.invalid/a.png",
        )


def test_review_transport_is_fixed_host_bounded_no_redirects_and_redacts_errors(monkeypatch):
    calls = []

    class Response:
        status = 302

        def read(self, maximum):
            assert maximum == 1024 * 1024 + 1
            return b"private-provider-body"

    class Connection:
        def request(self, *args, **kwargs):
            calls.append((args, kwargs))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    def connection(host, timeout):
        assert host == "zernio.com" and timeout == 6
        return Connection()

    monkeypatch.setattr(reviews, "https_connection", connection)
    with pytest.raises(HTTPException) as error:
        reviews.request(CREDS, "POST", "/v1/whatsapp/templates", {"name": "test"})
    assert error.value.detail == "review_provider_unavailable"
    assert calls[0][0][1] == "/api/v1/whatsapp/templates"
    assert len(calls) == 1
    with pytest.raises(ValueError):
        reviews.request(CREDS, "POST", "/v1/inbox/conversations", {})
    assert len(calls) == 1


def test_refresh_does_not_replace_a_newer_concurrent_observation(
    authenticated, provider, monkeypatch
):
    import psycopg

    client, owner_url, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    row = client.post(
        base + "/reviews", json={"version": 1, "account_id": ACCOUNT, "confirm": True}
    ).json()

    def stale(credentials, method, path, payload=None):
        assert method == "GET"
        with psycopg.connect(owner_url) as db:
            db.execute(
                "UPDATE crm.campaign_reviews SET status='APPROVED',checked_at=now() WHERE id=%s",
                (row["id"],),
            )
        return {
            "templates": [
                {
                    "id": row["provider_id"],
                    "name": row["name"],
                    "language": "es_CO",
                    "status": "PENDING",
                    "category": "MARKETING",
                }
            ]
        }

    monkeypatch.setattr(reviews, "request", stale)
    refreshed = client.post(base + f"/reviews/{row['id']}/refresh", json={})
    assert refreshed.status_code == 200 and refreshed.json()["status"] == "APPROVED"
    listing = client.get("/crm/campaigns").json()["items"]
    assert next(x for x in listing if x["id"] == item["id"])["review"]["status"] == "APPROVED"


def test_refresh_rejects_mismatched_provider_identity_without_changing_status(
    authenticated, provider, monkeypatch
):
    client, _, _ = authenticated
    item = saved(client)
    base = f"/crm/campaigns/{item['id']}"
    row = client.post(
        base + "/reviews", json={"version": 1, "account_id": ACCOUNT, "confirm": True}
    ).json()
    before = client.get(base + "/reviews").json()
    monkeypatch.setattr(
        reviews,
        "request",
        lambda *args: {
            "templates": [
                {
                    "id": "different",
                    "name": row["name"],
                    "language": "es_CO",
                    "status": "APPROVED",
                    "category": "MARKETING",
                }
            ]
        },
    )
    assert client.post(base + f"/reviews/{row['id']}/refresh", json={}).status_code == 502
    assert client.get(base + "/reviews").json() == before


def test_public_media_capabilities_never_enter_uvicorn_access_logs():
    import logging

    from app.campaigns.routes import ReviewMediaLogFilter

    secret_path = "/crm/campaigns/review-media/11111111-1111-4111-8111-111111111111/" + "x" * 43

    def record(path):
        return logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s %s HTTP/%s" %s',
            ("127.0.0.1", "GET", path, "1.1", 200),
            None,
        )

    assert not ReviewMediaLogFilter().filter(record(secret_path))
    assert ReviewMediaLogFilter().filter(record("/crm/campaigns/media/campaign-01"))
    assert ReviewMediaLogFilter().filter(record("/crm/auth/session"))
