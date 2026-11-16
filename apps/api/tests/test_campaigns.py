"""Internal campaign drafts only; synthetic users and isolated database."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_crm import authenticated  # noqa: F401

from app.campaigns.models import Document
from app.campaigns.service import seeds
from app.main import app


def document():
    return {
        "name": "Invitación de prueba",
        "audience": "invitation",
        "suggested_date": None,
        "body": "Hola {{nombre}}, conoce {{enlace_proyecto}}.",
        "image_id": "campaign-01",
        "variables": [
            {"key": "nombre", "kind": "text", "example": "María"},
            {
                "key": "enlace_proyecto",
                "kind": "link",
                "example": "https://jardinesdelencanto.site/",
            },
        ],
        "buttons": [
            {"kind": "url", "label": "Ver proyecto", "value": "{{enlace_proyecto}}"},
            {"kind": "reply", "label": "Quiero información", "value": "info"},
        ],
    }


def test_campaign_seeds_include_location_draft_and_seven_suggested_dates():
    items = seeds()
    assert len(items) == 16
    assert len({item["id"] for item in items}) == 16
    dates = []
    for item in items:
        doc = Document.model_validate(item["document"])
        assert item["status"] == "local_draft" and item["version"] == 0
        assert doc.buttons and doc.variables and doc.image_id
        if doc.audience == "registered":
            dates.append(doc.suggested_date.isoformat())
    assert dates == [f"2026-11-{day}" for day in range(16, 23)]


@pytest.mark.parametrize(
    "change",
    [
        {"body": "Hola {{no_existe}}"},
        {"body": "Hola {{nombre}"},
        {"image_id": "../../secret"},
        {"buttons": [{"kind": "url", "label": "Abrir", "value": "javascript:alert(1)"}]},
        {"buttons": [{"kind": "url", "label": "Abrir", "value": "{{nombre}}"}]},
        {"buttons": [{"kind": "reply", "label": "x" * 26, "value": "info"}]},
        {"status": "approved"},
    ],
)
def test_campaign_models_reject_unsafe_or_unresolved_content(change):
    with pytest.raises(ValidationError):
        Document.model_validate({**document(), **change})


def test_campaigns_require_authentication_and_offer_no_send_or_submit_route():
    with TestClient(app) as client:
        assert client.get("/crm/campaigns").status_code == 401
        assert client.get("/crm/campaigns/media/campaign-01").status_code == 401
        assert client.post("/crm/campaigns/submit").status_code in (404, 405)
        assert client.post("/crm/campaigns/send").status_code in (404, 405)
        assert client.post("/crm/campaigns", content=b"x" * 16385).status_code == 413


def test_campaigns_save_reload_custom_creation_and_conflict_preserve_changes(authenticated):
    client, _, _ = authenticated
    listed = client.get("/crm/campaigns")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 16
    seed = listed.json()["items"][0]
    changed = deepcopy(seed["document"])
    changed["name"] = "Nombre editado"
    path = f"/crm/campaigns/{seed['id']}"
    saved = client.patch(path, json={"version": 0, "document": changed})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert client.patch(path, json={"version": 0, "document": changed}).status_code == 409
    reloaded = client.get("/crm/campaigns").json()["items"][0]
    assert reloaded["document"]["name"] == "Nombre editado"
    assert reloaded["version"] == 1 and reloaded["status"] == "local_draft"
    changed["body"] += " Nos leemos pronto."
    assert client.patch(path, json={"version": 1, "document": changed}).json()["version"] == 2
    new = client.post("/crm/campaigns", json={"document": document()})
    assert new.status_code == 201, new.text
    assert new.json()["status"] == "local_draft"
    assert len(client.get("/crm/campaigns").json()["items"]) == 17
    assert (
        client.patch("/crm/campaigns/missing", json={"version": 0, "document": changed}).status_code
        == 404
    )


def test_campaign_media_is_private_allowlisted_and_csrf_is_unchanged(authenticated):
    client, _, _ = authenticated
    media = client.get("/crm/campaigns/media/campaign-01")
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert media.headers["cache-control"] == "no-store, private"
    assert client.get("/crm/campaigns/media/not-a-file").status_code == 404
    assert client.get("/crm/campaigns?url=https://evil.test").status_code == 422
    assert (
        client.post(
            "/crm/campaigns", headers={"X-CSRF-Token": "wrong"}, json={"document": document()}
        ).status_code
        == 403
    )


def test_campaign_concurrent_saves_have_one_winner(authenticated):
    client, _, _ = authenticated
    seed = client.get("/crm/campaigns").json()["items"][0]

    def save(name):
        changed = {**seed["document"], "name": name}
        return client.patch(
            f"/crm/campaigns/{seed['id']}", json={"version": 0, "document": changed}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["Primera versión", "Segunda versión"]))
    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(response.json() for response in results if response.status_code == 200)
    reloaded = client.get("/crm/campaigns").json()["items"][0]
    assert reloaded["document"] == winner["document"] and reloaded["version"] == 1


def test_campaign_list_stays_bounded_without_hiding_old_seed_overrides(authenticated):
    client, owner, _ = authenticated
    seed = client.get("/crm/campaigns").json()["items"][0]
    seed["document"]["name"] = "Referencia editada"
    assert (
        client.patch(
            f"/crm/campaigns/{seed['id']}", json={"version": 0, "document": seed["document"]}
        ).status_code
        == 200
    )
    with psycopg.connect(owner) as db:
        for number in range(101):
            db.execute(
                "INSERT INTO crm.campaign_drafts (slug,document,updated_by) "
                "SELECT %s,document,updated_by FROM crm.campaign_drafts WHERE slug=%s",
                (f"draft-fixture-{number}", seed["id"]),
            )
    listed = client.get("/crm/campaigns").json()
    assert listed["limited"] and len(listed["items"]) == 116
    assert listed["items"][0]["document"]["name"] == "Referencia editada"


def test_soacha_location_draft_keeps_original_campaigns_and_editable_map_link(authenticated):
    from urllib.parse import parse_qs, urlsplit

    from app.campaigns import service

    client, _, _ = authenticated
    items = client.get("/crm/campaigns").json()["items"]
    assert [item["id"] for item in items[:15]] == [f"campaign-{n:02}" for n in range(1, 16)]
    location = next(item for item in items if item["id"] == "campaign-16")
    assert location["status"] == "local_draft" and location["version"] == 0
    doc = location["document"]
    assert doc["image_id"] == "campaign-16"
    assert "Carrera 7 # 11 - 83 (Soacha)" in doc["body"]
    assert "ubicación" in doc["body"] and "SALIR" in doc["body"]
    link = next(v for v in doc["variables"] if v["key"] == "enlace_ubicacion")
    assert link["kind"] == "link"
    query = parse_qs(urlsplit(link["example"]).query)
    assert query["api"] == ["1"]
    assert "Carrera 7 # 11 - 83" in query["query"][0] and "Soacha" in query["query"][0]
    assert {"kind": "url", "label": "Cómo llegar", "value": "{{enlace_ubicacion}}"} in doc[
        "buttons"
    ]
    assert any(
        b["kind"] == "reply" and b["value"] == "confirmar_asistencia" for b in doc["buttons"]
    )
    assert client.get("/crm/campaigns/media/campaign-16").status_code == 200
    assert client.get("/crm/campaigns/media/campaign-17").status_code == 404
    assert (service.ROOT / "assets/campaign-16.png").stat().st_size <= 5 * 1024 * 1024
    changed = {**doc, "name": "Ubicación revisada"}
    saved = client.patch("/crm/campaigns/campaign-16", json={"version": 0, "document": changed})
    assert saved.status_code == 200 and saved.json()["status"] == "local_draft"
    assert client.get("/crm/campaigns/campaign-16/reviews").json()["items"] == []
