"""Offline regression checks: no real recipients or vendor sends."""

# ruff: noqa: F811

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app


def test_private_routes_require_session():
    with TestClient(app) as client:
        assert client.get("/crm/broadcasts").status_code == 401
        assert client.post("/crm/broadcasts/preview", json={}).status_code == 401


def test_csv_normalizes_deduplicates_and_reports_rows():
    from app.broadcasts.models import Preview
    from app.broadcasts.service import parse_csv

    result = parse_csv(
        Preview(
            csv_text="\ufeffnombre;celular\nAna;300 123 4567\nAna;+57 3001234567\nError;abc\n",
            name_column="nombre",
            phone_column="celular",
        )
    )
    assert result["recipients"] == [{"name": "Ana", "phone": "+573001234567"}]
    assert result["duplicates"] == 1
    assert result["invalid"] == [{"row": 4, "reason": "invalid_contact"}]


def test_csv_requires_explicit_columns_and_limits():
    from app.broadcasts.models import Preview
    from app.broadcasts.service import parse_csv

    for csv in ["name,phone\nAna,3001234567", "nombre,nombre,celular\nAna,Ana,3001234567"]:
        with pytest.raises(HTTPException):
            parse_csv(Preview(csv_text=csv, name_column="nombre", phone_column="celular"))
    with pytest.raises(HTTPException):
        parse_csv(
            Preview(
                csv_text="nombre,celular\n" + "Ana,3001234567\n" * 501,
                name_column="nombre",
                phone_column="celular",
            )
        )


def test_template_shape_requires_exact_parameters_and_approved_status():
    from app.broadcasts.service import compile_template

    template = {
        "name": "feria",
        "language": "es",
        "status": "APPROVED",
        "components": [{"type": "BODY", "text": "Hola {{1}}"}],
    }
    schema, payload, rendered = compile_template(template, {"body:1": "vecino"})
    assert schema == [{"key": "body:1", "label": "Texto 1", "kind": "text"}]
    assert payload["variableMapping"]["1"] == {"field": "custom", "customValue": "vecino"}
    assert rendered == "Hola vecino"
    for bad in ({}, {"body:1": "vecino", "body:2": "extra"}):
        with pytest.raises(HTTPException):
            compile_template(template, bad)
    template["status"] = "PAUSED"
    with pytest.raises(HTTPException):
        compile_template(template, {"body:1": "vecino"})


def test_media_and_dynamic_button_parameters_not_silently_dropped():
    from app.broadcasts.service import compile_template

    template = {
        "name": "feria",
        "language": "es",
        "status": "APPROVED",
        "components": [
            {"type": "HEADER", "format": "IMAGE"},
            {"type": "BODY", "text": "Ven a la feria"},
            {
                "type": "BUTTONS",
                "buttons": [{"type": "URL", "url": "https://example.com/{{1}}", "text": "Ver"}],
            },
        ],
    }
    schema, payload, _ = compile_template(
        template, {"header:media": "https://example.com/photo.jpg", "button:0": "feria"}
    )
    assert len(schema) == 2
    assert payload["components"][0]["parameters"][0] == {
        "type": "image",
        "image": {"link": "https://example.com/photo.jpg"},
    }
    assert payload["components"][-1]["parameters"][0]["text"] == "feria"
    with pytest.raises(HTTPException):
        compile_template(template, {"header:media": "http://localhost/file", "button:0": "feria"})


def test_send_confirmation_must_name_exact_campaign_and_count():
    from pydantic import ValidationError

    from app.broadcasts.models import Confirm

    with pytest.raises(ValidationError):
        Confirm(version=1, count=1, confirmed=False)


# All integration data is synthetic and restricted by the shared fixture to
# a dedicated jardines_crm_test database. Provider calls are offline fakes.
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from test_crm import authenticated  # noqa: F401


@pytest.fixture
def vendor(monkeypatch):
    from copy import deepcopy

    from app.broadcasts import service

    template = {
        "name": "feria",
        "language": "es",
        "status": "APPROVED",
        "components": [{"type": "BODY", "text": "Hola {{1}}"}],
    }
    creds = {"api_key": "offline-fixture-only", "profile_id": "a" * 24}
    monkeypatch.setattr(service, "credentials", lambda: creds)
    monkeypatch.setattr(service, "templates", lambda *args: deepcopy([template]))
    monkeypatch.setattr(service, "account", lambda *args: {"id": "b" * 24, "platform": "whatsapp"})
    calls = []

    def request(credentials, method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/v1/contacts/bulk":
            return {
                "success": True,
                "total": len(payload["contacts"]),
                "errors": [],
                "created": 1,
                "skipped": 0,
            }
        if path == "/v1/broadcasts":
            return {"success": True, "broadcast": {"id": "c" * 24}}
        if method == "GET" and "/recipients?" in path:
            return {
                "success": True,
                "recipients": [{"platformIdentifier": "573001234567", "status": "pending"}],
                "pagination": {"total": 1, "hasMore": False},
            }
        if method == "GET":
            return {
                "success": True,
                "broadcast": {
                    "id": "c" * 24,
                    "accountId": "b" * 24,
                    "platform": "whatsapp",
                    "status": "draft",
                    "recipientCount": 1,
                },
            }
        if path.endswith("/recipients"):
            return {"success": True, "added": 1, "skipped": 0}
        if path.endswith("/send"):
            return {"success": True, "status": "sending", "recipientCount": 1}
        raise AssertionError(path)

    monkeypatch.setattr(service.provider, "request", request)
    return service, calls, request


def payload(csv="nombre,celular\nNueva,3001234567\n"):
    return {
        "id": str(uuid4()),
        "name": "Campaña de prueba",
        "account_id": "b" * 24,
        "template_name": "feria",
        "template_language": "es",
        "values": {"body:1": "vecino"},
        "csv_text": csv,
        "name_column": "nombre",
        "phone_column": "celular",
        "consent_confirmed": True,
        "consent_note": "Formulario de prueba con autorización",
    }


def test_import_dedup_labels_and_dashboard_preserve_existing(authenticated, vendor):
    client, _, _ = authenticated
    original = client.post(
        "/crm/contacts",
        json={"name": "Existente", "phone": "+573001234568", "source": "social_campaign"},
    ).json()
    deal = client.get("/crm/workspace").json()["deals"][0]
    client.patch("/crm/deals/" + deal["id"], json={"stage": "won", "version": deal["version"]})
    p = payload(
        "nombre,celular\nNueva,3001234567\nDuplicada,+573001234567\nCambio de nombre,3001234568\n"
    )
    response = client.post("/crm/broadcasts", json=p)
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "draft" and response.json()["recipient_count"] == 2
    assert vendor[1] == []  # Local draft/import creates no external broadcast or message.
    assert client.post("/crm/broadcasts", json=p).json()["id"] == p["id"]
    assert client.post("/crm/broadcasts", json={**p, "name": "Otro"}).status_code == 409
    workspace = client.get("/crm/workspace").json()
    assert workspace["counts"]["contacts"] == 2
    assert workspace["counts"]["cold_leads"] == 1 and workspace["counts"]["campaign_leads"] == 1
    existing = next(c for c in workspace["contacts"] if c["id"] == original["id"])
    assert (
        existing["name"] == "Existente"
        and existing["source"] == "social_campaign"
        and existing["cold_lead"] is False
    )
    assert existing["broadcast_tags"] == ["Campaña de prueba"]
    assert (
        next(d for d in workspace["deals"] if d["contact_id"] == existing["id"])["stage"] == "won"
    )
    cold = client.post("/crm/broadcasts/filter", json={"cold_only": True}).json()
    assert len(cold["contacts"]) == 1 and cold["contacts"][0]["name"] == "Nueva"
    assert cold["counts"]["contacts"] == 2
    all_campaign = client.post("/crm/broadcasts/filter", json={"campaign_id": p["id"]}).json()
    assert len(all_campaign["contacts"]) == 2 and len(all_campaign["deals"]) == 2


def test_send_requires_count_confirmation_and_does_not_replay(authenticated, vendor):
    client, _, _ = authenticated
    p = payload()
    saved = client.post("/crm/broadcasts", json=p).json()
    path = "/crm/broadcasts/" + p["id"] + "/send"
    assert client.post(path, json={"version": 1, "count": 2, "confirmed": True}).status_code == 409
    assert client.post(path, json={"version": 1, "count": 1, "confirmed": False}).status_code == 422
    assert vendor[1] == []
    response = client.post(path, json={"version": saved["version"], "count": 1, "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "submitted"
    assert client.post(path, json={"version": 1, "count": 1, "confirmed": True}).status_code == 409
    assert sum(1 for call in vendor[1] if call[1].endswith("/send")) == 1
    bulk = next(c[2] for c in vendor[1] if c[1] == "/v1/contacts/bulk")
    assert "isSubscribed" not in bulk["contacts"][0]
    draft = next(c[2] for c in vendor[1] if c[1] == "/v1/broadcasts")
    assert draft["segmentFilters"]["isSubscribed"] is True
    recipients = next(c[2] for c in vendor[1] if c[1].endswith("/recipients"))
    assert recipients == {"useSegment": True}


def test_unknown_delivery_is_retained_and_never_retried(authenticated, vendor, monkeypatch):
    client, _, _ = authenticated
    service, calls, original = vendor
    p = payload()
    client.post("/crm/broadcasts", json=p)

    def request(*args):
        if args[2].endswith("/send"):
            calls.append((args[1], args[2], args[3]))
            raise HTTPException(502, "broadcast_unknown")
        return original(*args)

    monkeypatch.setattr(service.provider, "request", request)
    path = "/crm/broadcasts/" + p["id"]
    r = client.post(path + "/send", json={"version": 1, "count": 1, "confirmed": True})
    assert r.json()["state"] == "unknown" and r.json()["provider_id"] == "c" * 24
    assert (
        client.post(path + "/send", json={"version": 2, "count": 1, "confirmed": True}).status_code
        == 409
    )
    assert sum(1 for c in calls if c[1].endswith("/send")) == 1
    assert client.post(path + "/refresh", json={}).json()["state"] == "unknown"


def test_wrong_audience_or_tenant_never_sends(authenticated, vendor, monkeypatch):
    client, _, _ = authenticated
    service, calls, original = vendor
    p = payload()
    client.post("/crm/broadcasts", json=p)

    def request(*args):
        if args[1] == "GET":
            return {
                "success": True,
                "broadcast": {
                    "accountId": "another-account",
                    "platform": "whatsapp",
                    "status": "draft",
                },
            }
        return original(*args)

    monkeypatch.setattr(service.provider, "request", request)
    result = client.post(
        "/crm/broadcasts/" + p["id"] + "/send", json={"version": 1, "count": 1, "confirmed": True}
    )
    assert (
        result.json()["state"] == "unknown"
        and result.json()["last_error"] == "broadcast_scope_mismatch"
    )
    assert not any(c[1].endswith("/send") for c in calls)


def test_concurrent_confirmation_has_one_external_send(authenticated, vendor):
    client, _, _ = authenticated
    p = payload()
    client.post("/crm/broadcasts", json=p)
    path = "/crm/broadcasts/" + p["id"] + "/send"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post(path, json={"version": 1, "count": 1, "confirmed": True}),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert sum(1 for c in vendor[1] if c[1].endswith("/send")) == 1


@pytest.mark.parametrize(
    "change", [{"platformIdentifier": "573001234599"}, {"isSubscribed": False}, {"isBlocked": True}]
)
def test_equal_count_substitution_and_explicit_optout_never_send(
    authenticated, vendor, monkeypatch, change
):
    client, _, _ = authenticated
    service, calls, original = vendor
    p = payload()
    client.post("/crm/broadcasts", json=p)

    def request(*args):
        if args[1] == "GET" and "/recipients?" in args[2]:
            calls.append((args[1], args[2], None))
            return {
                "success": True,
                "recipients": [
                    {"platformIdentifier": "573001234567", "status": "pending", **change}
                ],
                "pagination": {"total": 1, "hasMore": False},
            }
        return original(*args)

    monkeypatch.setattr(service.provider, "request", request)
    result = client.post(
        "/crm/broadcasts/" + p["id"] + "/send", json={"version": 1, "count": 1, "confirmed": True}
    )
    assert (
        result.json()["state"] == "unknown"
        and result.json()["last_error"] == "broadcast_audience_invalid"
    )
    assert not any(c[1].endswith("/send") for c in calls)


def test_template_revocation_and_body_size_guards(authenticated, vendor, monkeypatch):
    client, _, _ = authenticated
    service, calls, _ = vendor
    p = payload()
    client.post("/crm/broadcasts", json=p)
    monkeypatch.setattr(service, "templates", lambda *args: [])
    assert (
        client.post(
            "/crm/broadcasts/" + p["id"] + "/send",
            json={"version": 1, "count": 1, "confirmed": True},
        ).status_code
        == 409
    )
    assert calls == []
    assert (
        client.post("/crm/broadcasts/preview", content=b"x" * (1024 * 1024 + 1)).status_code == 413
    )
    assert client.get("/crm/broadcasts?arbitrary=1").status_code == 422
    assert (
        client.post(
            "/crm/broadcasts/preview", headers={"X-CSRF-Token": "wrong"}, json={}
        ).status_code
        == 403
    )


def test_media_link_validation_rejects_invalid_ports_and_private_targets():
    from app.broadcasts.service import compile_template

    template = {
        "name": "feria",
        "language": "es",
        "status": "APPROVED",
        "components": [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Hola"}],
    }
    for link in (
        "https://example.com:bad/image.jpg",
        "https://10.0.0.1/image.jpg",
        "https://app.local/image.jpg",
        "https://[::1]/image.jpg",
    ):
        with pytest.raises(HTTPException) as error:
            compile_template(template, {"header:media": link})
        assert error.value.status_code == 422


def test_server_tag_filter_finds_contacts_outside_unfiltered_first_page(authenticated, vendor):
    import psycopg

    client, owner, _ = authenticated
    p = payload()
    saved = client.post("/crm/broadcasts", json=p).json()
    with psycopg.connect(owner) as db, db.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO crm.contacts(name,phone,source) VALUES(%s,%s,'other')",
            [(f"Filler {i}", f"+1202556{i:04d}") for i in range(501)],
        )
    unfiltered = client.get("/crm/workspace").json()
    assert unfiltered["limited"] is True and len(unfiltered["contacts"]) == 500
    assert not any(c["phone"] == "+573001234567" for c in unfiltered["contacts"])
    scoped = client.post("/crm/broadcasts/filter", json={"campaign_id": saved["id"]}).json()
    assert len(scoped["contacts"]) == 1 and scoped["contacts"][0]["phone"] == "+573001234567"
    assert scoped["counts"]["contacts"] == 502


def test_overlapping_imports_reuse_contact_identity_concurrently(authenticated, vendor):
    client, _, _ = authenticated
    requests = [
        payload("nombre,celular\nAna,3001234567\nBea,3001234568\n"),
        payload("nombre,celular\nBea,3001234568\nAna,3001234567\n"),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: client.post("/crm/broadcasts", json=p), requests))
    assert [r.status_code for r in results] == [201, 201]
    work = client.get("/crm/workspace").json()
    assert work["counts"]["contacts"] == 2 and work["counts"]["cold_leads"] == 2
    assert len(work["deals"]) == 2
    assert {
        frozenset(r["contact_id"] for r in response.json()["recipients"]) for response in results
    } == {frozenset(c["id"] for c in work["contacts"])}
