"""Durable one-shot attachment outbox for verified developer-origin image jobs only."""

import hashlib
import os
import threading

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control import service as control
from ..crm.database import connect
from ..hermes.developer import queue_authority
from ..social import media

_stop = threading.Event()
_thread = None
BINDING_KEYS = (
    "job_id",
    "agent_version",
    "account_id",
    "profile_id",
    "conversation_id",
    "participant_id",
    "credential_revision",
)


def _grant(db, image):
    return db.execute(
        "SELECT * FROM crm.whatsapp_developer_authority WHERE run_id=%s AND owner_id=%s",
        (image["origin_run_id"], image["owner_id"]),
    ).fetchone()


def _binding(grant):
    return {key: str(grant[key]) for key in BINDING_KEYS}


def enqueue(db, image):
    if image["origin_kind"] != "whatsapp_developer" or image["status"] != "completed":
        return
    grant = _grant(db, image)
    if not grant:
        return  # No authority can be manufactured for an orphaned source.
    data = bytes(image["data"])
    oversized = len(data) > media.MAX_ATTACHMENT
    db.execute(
        """INSERT INTO crm.sara_image_deliveries(image_id,owner_id,origin_run_id,binding,
        content_hash,byte_size,state,error,finished_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,
        CASE WHEN %s THEN now() ELSE NULL END) ON CONFLICT(image_id) DO NOTHING""",
        (
            image["id"],
            image["owner_id"],
            image["origin_run_id"],
            Jsonb(_binding(grant)),
            hashlib.sha256(data).hexdigest(),
            len(data),
            "blocked" if oversized else "pending",
            "image_exceeds_whatsapp_limit" if oversized else None,
            oversized,
        ),
    )


def _image(db, row):
    image = db.execute(
        "SELECT * FROM crm.sara_image_jobs WHERE id=%s", (row["image_id"],)
    ).fetchone()
    if (
        not image
        or image["status"] != "completed"
        or image["origin_kind"] != "whatsapp_developer"
        or image["origin_run_id"] != row["origin_run_id"]
        or image["owner_id"] != row["owner_id"]
    ):
        raise HTTPException(409, "image_delivery_authority_changed")
    queue_authority(db, image)
    grant = _grant(db, image)
    data = bytes(image["data"])
    if (
        not grant
        or _binding(grant) != row["binding"]
        or hashlib.sha256(data).hexdigest() != row["content_hash"]
        or len(data) != row["byte_size"]
    ):
        raise HTTPException(409, "image_delivery_content_changed")
    return image, grant


def _finish(db, identifier, state, error=None, receipt=None):
    db.execute(
        """UPDATE crm.sara_image_deliveries SET state=%s,error=%s,receipt=%s,finished_at=now()
        WHERE image_id=%s AND state IN ('preparing','reserved')""",
        (state, error, Jsonb(receipt or {}), identifier),
    )


def claim(db):
    control.lock(db)
    db.execute("""UPDATE crm.sara_image_deliveries SET state='unknown',
        error='image_delivery_unknown',finished_at=now()
        WHERE state IN ('preparing','reserved') AND claimed_at<now()-interval '3 minutes'""")
    row = db.execute("""SELECT * FROM crm.sara_image_deliveries WHERE state='pending'
        ORDER BY created_at,image_id FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
    if row:
        db.execute(
            """UPDATE crm.sara_image_deliveries SET state='preparing',claimed_at=now()
            WHERE image_id=%s AND state='pending'""",
            (row["image_id"],),
        )
    return row


def tick():
    with connect() as db:
        row = claim(db)
    if not row:
        return False
    reserved = False
    try:
        with connect() as db:
            image, source = _image(db, row)
        # Source identity is always the persisted grant, never model arguments.
        # Release the control xact lock before bounded read-only vendor preparation.
        plan = media.prepare(None, {**source, "id": source["job_id"]}, image)
        # Lock order matches all channel/control revocation: agent -> control -> credentials.
        with connect() as guard:
            guard.execute("SELECT pg_advisory_lock(9142040)")
            guard.execute("SELECT pg_advisory_lock(2026111105)")
            guard.commit()
            try:
                # Same connection: queue_authority acquires the control xact lock itself.
                image, source = _image(guard, row)
                fresh = guard.execute(
                    "SELECT state FROM crm.sara_image_deliveries WHERE image_id=%s FOR UPDATE",
                    (row["image_id"],),
                ).fetchone()
                if (
                    not fresh
                    or fresh["state"] != "preparing"
                    or plan["reply"]["credential_revision"] != source["credential_revision"]
                ):
                    raise HTTPException(409, "image_delivery_authority_changed")
                guard.execute(
                    "UPDATE crm.sara_image_deliveries SET state='reserved' WHERE image_id=%s",
                    (row["image_id"],),
                )
                guard.commit()
                reserved = True
                result = media.submit(
                    plan, bytes(image["data"]), "sara-image-" + str(row["image_id"])
                )
                _finish(
                    guard,
                    row["image_id"],
                    result["state"],
                    result.get("error"),
                    result.get("receipt"),
                )
                guard.commit()
            finally:
                guard.rollback()  # Clear a failed transaction before unlocking; close is a backstop.
                guard.execute("SELECT pg_advisory_unlock(2026111105)")
                guard.execute("SELECT pg_advisory_unlock(9142040)")
                guard.commit()
    except Exception:  # noqa: BLE001 - Never leak vendor diagnostics or replay a reserved send.
        with connect() as db:
            _finish(
                db,
                row["image_id"],
                "unknown" if reserved else "blocked",
                "image_delivery_unknown"
                if reserved
                else "image_delivery_authority_or_target_changed",
            )
    return True


def _loop():
    while not _stop.is_set():
        try:
            worked = tick()
        except Exception:  # noqa: BLE001 - An uncertain reservation remains durable, never retried.
            worked = False
        if not worked:
            _stop.wait(2)


def start():
    global _thread
    if os.getenv("CRM_WHATSAPP_IMAGES_WORKER_ENABLED") != "1" or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="sara-whatsapp-images", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=1)
