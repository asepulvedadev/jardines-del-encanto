"""Owner-scoped receipts, bounded spend and immutable reference provenance."""

import hashlib
import json

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control import service as control
from . import assets, models

MODEL = "gpt-image-2.5-flare"
DAILY_CAP = 5
BRAND_BRIEF = (
    "Create an explicitly AI-generated visual concept for Jardines del Encanto. "
    "Brand: forest green #062619 and leaf #507010 on calm light surfaces. "
    "Use professional Colombian Spanish for requested visible text. "
    "Preserve the exact geometry, lettering, proportions and original colors of supplied logos. "
    "Reference photos document real supplied views, but generated output is a CONCEPT, "
    "not evidence of actual property condition, lot boundaries, amenities or construction. "
    "Do not invent commercial facts, prices, availability, guarantees or testimonials. "
    "If requested content conflicts with these brand and factual boundaries, keep these boundaries. "
)


def receipt(row):
    completed = row["status"] == "completed"
    return {
        "kind": "image",
        "id": str(row["id"]),
        "status": row["status"],
        "url": f"/api/crm/images/{row['id']}/content" if completed else None,
        "mime_type": "image/png",
        "size": row.get("byte_size") if completed else None,
        "concept": True,
        "reference_ids": row["reference_ids"],
        "reference_versions": row["reference_versions"],
        "model": MODEL,
        "image_size": row["image_size"],
        "error": row.get("error"),
    }


def catalog(db, admin):
    return {
        "assets": assets.catalog(),
        "model": MODEL,
        "quality": "low",
        "count": 1,
        "output_format": "png",
        "daily_cap": DAILY_CAP,
        "concept": True,
    }


def enqueue(db, args, admin):
    args = models.Generate.model_validate(args) if isinstance(args, dict) else args
    control.lock(db)
    control.require_connections(db, "hermes")
    digest = hashlib.sha256(
        json.dumps(
            args.model_dump(mode="json", exclude={"request_id"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    old = db.execute(
        "SELECT *,octet_length(data) AS byte_size FROM crm.sara_image_jobs WHERE owner_id=%s AND request_id=%s",
        (admin["id"], args.request_id),
    ).fetchone()
    if old:
        if old["payload_hash"] != digest:
            raise HTTPException(409, "image_request_conflict")
        return receipt(old)
    total = db.execute(
        "SELECT count(*) AS total FROM crm.sara_image_jobs WHERE owner_id=%s AND created_at>now()-interval '24 hours'",
        (admin["id"],),
    ).fetchone()["total"]
    if total >= DAILY_CAP:
        raise HTTPException(429, "image_daily_limit", headers={"Retry-After": "86400"})
    from ..hermes.developer import queue_origin

    origin_kind, origin_run_id = queue_origin(admin)
    versions = {key: assets.get(key)[0]["sha256"] for key in args.reference_ids}
    # Validate the entire bounded bridge frame before spending a queue slot.
    body = {
        "prompt": BRAND_BRIEF + "\nUser concept request:\n" + args.prompt,
        "reference_images": assets.references(args.reference_ids),
        "size": args.size,
    }
    if len(json.dumps(body).encode()) > 4 * 1024 * 1024:
        raise HTTPException(422, "image_references_too_large")
    row = db.execute(
        """INSERT INTO crm.sara_image_jobs(owner_id,request_id,payload_hash,prompt,reference_ids,reference_versions,image_size,origin_kind,origin_run_id)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *,NULL AS byte_size""",
        (
            admin["id"],
            args.request_id,
            digest,
            args.prompt,
            Jsonb(args.reference_ids),
            Jsonb(versions),
            args.size,
            origin_kind,
            origin_run_id,
        ),
    ).fetchone()
    return receipt(row)


def status(db, identifier, admin):
    row = db.execute(
        "SELECT *,octet_length(data) AS byte_size FROM crm.sara_image_jobs WHERE id=%s AND owner_id=%s",
        (identifier, admin["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    result = receipt(row)
    if row["origin_kind"] == "whatsapp_developer":
        delivery = db.execute(
            "SELECT state,error FROM crm.sara_image_deliveries WHERE image_id=%s AND owner_id=%s",
            (identifier, admin["id"]),
        ).fetchone()
        result["whatsapp_delivery"] = {
            "state": delivery["state"]
            if delivery
            else (
                "waiting_for_generation"
                if row["status"] in {"queued", "processing"}
                else "not_available"
            ),
            "error": delivery["error"] if delivery else None,
            "accepted": bool(delivery and delivery["state"] == "completed"),
        }
    return result


def content(db, identifier, admin):
    row = db.execute(
        "SELECT data FROM crm.sara_image_jobs WHERE id=%s AND owner_id=%s AND status='completed'",
        (identifier, admin["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    return bytes(row["data"])
