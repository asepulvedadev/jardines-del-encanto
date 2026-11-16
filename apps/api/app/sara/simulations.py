"""Durable, owner-scoped synthetic conversations with no business tool execution."""

import hashlib
import json
import os
import threading

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control import service as control
from ..crm.database import connect
from ..hermes import bridge
from . import profile

_stop = threading.Event()
_thread = None
DAILY_CAP = 3


def view(row):
    return {
        key: row[key]
        for key in ("id", "title", "status", "profile_version", "transcript", "error", "created_at")
    } | {"synthetic": True}


def create(db, args, admin):
    control.lock(db)
    control.require_connections(db, "hermes")
    body = args.model_dump(mode="json", exclude={"request_id"})
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    old = db.execute(
        "SELECT * FROM crm.sara_simulations WHERE owner_id=%s AND request_id=%s",
        (admin["id"], args.request_id),
    ).fetchone()
    if old:
        if old["input_hash"] != digest:
            raise HTTPException(409, "simulation_request_conflict")
        return view(old)
    count = db.execute(
        "SELECT count(*) AS total FROM crm.sara_simulations WHERE owner_id=%s AND created_at>now()-interval '24 hours'",
        (admin["id"],),
    ).fetchone()["total"]
    if count >= DAILY_CAP:
        raise HTTPException(429, "simulation_daily_limit", headers={"Retry-After": "86400"})
    from ..hermes.developer import queue_origin

    origin_kind, origin_run_id = queue_origin(admin)
    config = profile.get(db)
    row = db.execute(
        """INSERT INTO crm.sara_simulations(owner_id,request_id,title,input,input_hash,profile_version,profile,origin_kind,origin_run_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            admin["id"],
            args.request_id,
            args.title,
            Jsonb(body),
            digest,
            config["version"],
            Jsonb({key: config[key] for key in profile.Profile.model_fields}),
            origin_kind,
            origin_run_id,
        ),
    ).fetchone()
    return view(row)


def status(db, identifier, admin):
    row = db.execute(
        "SELECT * FROM crm.sara_simulations WHERE id=%s AND owner_id=%s", (identifier, admin["id"])
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    return view(row)


def claim(db):
    control.lock(db)
    db.execute(
        "UPDATE crm.sara_simulations SET status='unknown',error='simulation_outcome_unknown',finished_at=now() WHERE status='processing' AND claimed_at<now()-interval '5 minutes'"
    )
    row = db.execute(
        "SELECT * FROM crm.sara_simulations WHERE status='queued' ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1"
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
            raise HTTPException(409, "authority_changed")
    except HTTPException:
        db.execute(
            "UPDATE crm.sara_simulations SET status='failed',error='simulation_authority_changed',finished_at=now() WHERE id=%s",
            (row["id"],),
        )
        return None
    db.execute(
        "UPDATE crm.sara_simulations SET status='processing',claimed_at=now() WHERE id=%s",
        (row["id"],),
    )
    return row


def tick():
    with connect() as db:
        row = claim(db)
    if not row:
        return False
    transcript, outcome, error = [], "completed", None
    try:
        for turn in row["input"]["customer_turns"]:
            # Recheck revocation between turns; no real contact, tool, or message dispatch.
            with connect() as db:
                control.lock(db)
                control.require_connections(db, "hermes")
                from ..hermes.developer import queue_authority

                queue_authority(db, row)
                if not db.execute(
                    "SELECT id FROM crm.users WHERE id=%s AND enabled AND role='admin'",
                    (row["owner_id"],),
                ).fetchone():
                    raise HTTPException(409, "authority_changed")
            transcript.append({"role": "user", "content": turn})
            answer = bridge.request(
                "/public-reply",
                {
                    "messages": transcript.copy(),
                    "instructions": profile.instructions(row["profile"]),
                    "knowledge": row["profile"]["knowledge"],
                },
                timeout=45,
            )
            if (
                set(answer) != {"ok", "tools", "response", "model"}
                or answer["model"] != "gpt-6-luna"
                or answer["ok"] is not True
                or type(answer["tools"]) is not int
                or answer["tools"] != 0
                or not isinstance(answer["response"], str)
                or not 1 <= len(answer["response"]) <= 1500
            ):
                raise ValueError("Invalid simulation reply")
            transcript.append({"role": "assistant", "content": answer["response"]})
    except Exception:  # noqa: BLE001 - Never replay an uncertain model request.
        outcome, error = "unknown", "simulation_outcome_unknown"
    with connect() as db:
        db.execute(
            "UPDATE crm.sara_simulations SET status=%s,transcript=%s,error=%s,finished_at=now() WHERE id=%s AND status='processing'",
            (outcome, Jsonb(transcript), error, row["id"]),
        )
    return True


def run():
    while not _stop.is_set():
        try:
            worked = tick()
        except Exception:  # noqa: BLE001 - Do not log private prompts or provider errors.
            worked = False
        if not worked:
            _stop.wait(2)


def start():
    global _thread
    if os.getenv("CRM_SIMULATIONS_WORKER_ENABLED") != "1" or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=run, name="sara-simulations", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=1)
