"""Source-controlled seed drafts with durable, optimistic-locking overrides."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .models import Document

ROOT = Path(__file__).parent


def record(slug, document, version=0, updated_at=None):
    return {
        "id": slug,
        "document": document,
        "version": version,
        "status": "local_draft",
        "updated_at": updated_at,
    }


def seeds():
    return [
        record(item["id"], Document.model_validate(item["document"]).model_dump(mode="json"))
        for item in json.loads((ROOT / "seeds.json").read_text())
    ]


def listing(db):
    defaults = seeds()
    identifiers = [item["id"] for item in defaults]
    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    rows = db.execute(
        "SELECT slug, document, version, updated_at FROM crm.campaign_drafts WHERE slug=ANY(%s)",
        (identifiers,),
    ).fetchall()
    custom = db.execute(
        "SELECT slug, document, version, updated_at FROM crm.campaign_drafts "
        "WHERE NOT (slug=ANY(%s)) ORDER BY updated_at DESC, slug LIMIT 101",
        (identifiers,),
    ).fetchall()
    overrides = {
        row["slug"]: record(row["slug"], row["document"], row["version"], row["updated_at"])
        for row in [*rows, *custom[:100]]
    }
    items = [overrides.pop(item["id"], item) for item in defaults]
    items = [*items, *overrides.values()]
    recent = db.execute(
        "SELECT DISTINCT ON (slug) slug,version,status,id FROM crm.campaign_reviews WHERE slug=ANY(%s) ORDER BY slug,created_at DESC,id DESC",
        ([item["id"] for item in items],),
    ).fetchall()
    by_slug = {
        row["slug"]: {key: row[key] for key in ("version", "status", "id")} for row in recent
    }
    for item in items:
        item["review"] = by_slug.get(item["id"])
    return {"items": items, "limited": len(custom) > 100}


def create(db, data, admin):
    slug = "draft-" + str(uuid4())
    row = db.execute(
        "INSERT INTO crm.campaign_drafts (slug, document, updated_by) VALUES (%s,%s,%s) "
        "RETURNING version, updated_at",
        (slug, Jsonb(data.document.model_dump(mode="json")), admin["id"]),
    ).fetchone()
    return record(slug, data.document.model_dump(mode="json"), **row)


def update(db, slug, data, admin):
    document = data.document.model_dump(mode="json")
    if data.version == 0 and slug in {item["id"] for item in seeds()}:
        row = db.execute(
            "INSERT INTO crm.campaign_drafts (slug,document,updated_by) VALUES (%s,%s,%s) "
            "ON CONFLICT (slug) DO NOTHING RETURNING version, updated_at",
            (slug, Jsonb(document), admin["id"]),
        ).fetchone()
    else:
        row = db.execute(
            "UPDATE crm.campaign_drafts SET document=%s, updated_by=%s, "
            "version=version+1, updated_at=now() WHERE slug=%s AND version=%s "
            "RETURNING version, updated_at",
            (Jsonb(document), admin["id"], slug, data.version),
        ).fetchone()
    if not row:
        exists = db.execute("SELECT 1 FROM crm.campaign_drafts WHERE slug=%s", (slug,)).fetchone()
        if not exists and slug not in {item["id"] for item in seeds()}:
            raise HTTPException(404, "not_found")
        raise HTTPException(409, "record_changed")
    item = record(slug, document, **row)
    item["review"] = db.execute(
        "SELECT version,status,id FROM crm.campaign_reviews WHERE slug=%s ORDER BY created_at DESC,id DESC LIMIT 1",
        (slug,),
    ).fetchone()
    return item
