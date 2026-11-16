"""Claim once, commit, then perform exactly one external image call."""

import os
import threading

from fastapi import HTTPException

from ..control import service as control
from ..crm.database import connect
from . import assets, bridge, delivery, service

_stop = threading.Event()
_thread = None


def claim(db):
    control.lock(db)
    db.execute("""UPDATE crm.sara_image_jobs SET status='unknown',error='image_outcome_unknown',finished_at=now()
                  WHERE status='processing' AND claimed_at<now()-interval '180 seconds'""")
    row = db.execute(
        "SELECT * FROM crm.sara_image_jobs WHERE status='queued' ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1"
    ).fetchone()
    if not row:
        return None
    try:
        control.require_connections(db, "hermes")
        from ..hermes.developer import queue_authority

        queue_authority(db, row)
        owner = db.execute(
            "SELECT id FROM crm.users WHERE id=%s AND enabled AND role='admin'", (row["owner_id"],)
        ).fetchone()
        if not owner:
            raise HTTPException(409, "image_authority_changed")
        if row["reference_versions"] != {
            key: assets.get(key)[0]["sha256"] for key in row["reference_ids"]
        }:
            raise HTTPException(409, "image_reference_changed")
    except HTTPException:
        db.execute(
            "UPDATE crm.sara_image_jobs SET status='failed',error='image_authority_or_reference_changed',finished_at=now() WHERE id=%s AND status='queued'",
            (row["id"],),
        )
        return None
    db.execute(
        "UPDATE crm.sara_image_jobs SET status='processing',claimed_at=now() WHERE id=%s AND status='queued'",
        (row["id"],),
    )
    return row


def tick():
    with connect() as db:
        row = claim(db)
    if not row:
        return False
    # Database context has committed and closed before any provider I/O.
    target, error, data = "failed", "image_reference_unavailable", None
    try:
        payload = {
            "prompt": service.BRAND_BRIEF + "\nUser concept request:\n" + row["prompt"],
            "reference_images": assets.references(row["reference_ids"]),
            "size": row["image_size"],
        }
    except HTTPException:
        payload = None
    if payload is not None:
        try:
            data = bridge.generate(payload)
            target, error = "completed", None
        except Exception:  # noqa: BLE001 - Any uncertain external result is terminal, never retried.
            target, error, data = "unknown", "image_outcome_unknown", None
    with connect() as db:
        completed = db.execute(
            "UPDATE crm.sara_image_jobs SET status=%s,error=%s,data=%s,finished_at=now() WHERE id=%s AND status='processing' RETURNING *",
            (target, error, data, row["id"]),
        ).fetchone()
        if target == "completed" and row.get("origin_kind") == "whatsapp_developer" and completed:
            delivery.enqueue(db, completed)
    return True


def run():
    while not _stop.is_set():
        try:
            worked = tick()
        except Exception:  # noqa: BLE001 - No vendor or database details cross the worker boundary.
            worked = False
        if not worked:
            _stop.wait(2)


def start():
    global _thread
    if os.getenv("CRM_IMAGES_WORKER_ENABLED") != "1" or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=run, name="sara-images", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=1)
