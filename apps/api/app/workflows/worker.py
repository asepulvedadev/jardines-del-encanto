"""Durable once-only reservations; uncertain external effects are never replayed."""

import os
import threading
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control import service as control
from ..crm import models as crm_models
from ..crm import services
from ..crm.database import connect
from . import service

BOGOTA = ZoneInfo("America/Bogota")
_stop = threading.Event()
_thread = None
_heartbeat = 0.0


def enabled():
    return os.getenv("CRM_WORKFLOWS_WORKER_ENABLED") == "1"


def available():
    return (
        enabled() and _thread is not None and _thread.is_alive() and monotonic() - _heartbeat < 15
    )


def scheduled_at(schedule, instant):
    local = instant.astimezone(BOGOTA)
    start = datetime.strptime(schedule["start_time"], "%H:%M").time()
    end = datetime.strptime(schedule["end_time"], "%H:%M").time()
    for offset in range(8):
        date = (local + timedelta(days=offset)).date()
        if date.isoweekday() not in schedule["days"]:
            continue
        opening = datetime.combine(date, start, BOGOTA)
        closing = datetime.combine(date, end, BOGOTA)
        candidate = max(local, opening)
        if candidate < closing:
            return candidate.astimezone(UTC)
    raise ValueError("invalid_schedule")


def hold(db, row, reason, recipient=None, status="paused"):
    db.execute(
        "UPDATE crm.workflow_runs SET status=%s,version=version+1 WHERE id=%s AND status='active'",
        (status, row["id"]),
    )
    if recipient:
        db.execute(
            "UPDATE crm.workflow_recipients SET status=%s,error=%s WHERE run_id=%s AND contact_id=%s AND status='active'",
            (
                "unknown" if status == "unknown" else "blocked",
                reason,
                row["id"],
                recipient["contact_id"],
            ),
        )
    service.event(db, row["id"], status, reason, recipient["contact_id"] if recipient else None)


def recover(db):
    rows = db.execute(
        "SELECT r.* FROM crm.workflow_runs r WHERE EXISTS (SELECT 1 FROM crm.workflow_steps s WHERE s.run_id=r.id AND s.state='reserved' AND s.reserved_at<now()-interval '180 seconds') ORDER BY r.created_at FOR UPDATE SKIP LOCKED LIMIT 20"
    ).fetchall()
    for row in rows:
        stale = db.execute(
            "UPDATE crm.workflow_steps SET state='unknown',completed_at=now() WHERE run_id=%s AND state='reserved' AND reserved_at<now()-interval '180 seconds' RETURNING contact_id,node_id",
            (row["id"],),
        ).fetchall()
        for step in stale:
            db.execute(
                "UPDATE crm.workflow_recipients SET status='unknown',error='dispatch_outcome_unknown' WHERE run_id=%s AND contact_id=%s AND status<>'stopped'",
                (row["id"], step["contact_id"]),
            )
            service.event(
                db,
                row["id"],
                "unknown",
                "Reserva expirada: resultado incierto; NO se reenviará.",
                step["contact_id"],
                step["node_id"],
            )
        db.execute(
            "UPDATE crm.workflow_runs SET status='unknown',version=version+1 WHERE id=%s AND status NOT IN ('stopped','completed')",
            (row["id"],),
        )


def finish_run(db, row):
    remaining = db.execute(
        "SELECT count(*) AS total FROM crm.workflow_recipients WHERE run_id=%s AND status='active'",
        (row["id"],),
    ).fetchone()["total"]
    if not remaining:
        statuses = {
            r["status"]
            for r in db.execute(
                "SELECT DISTINCT status FROM crm.workflow_recipients WHERE run_id=%s", (row["id"],)
            ).fetchall()
        }
        target = (
            "unknown"
            if "unknown" in statuses
            else "blocked"
            if "blocked" in statuses
            else "completed"
        )
        db.execute(
            "UPDATE crm.workflow_runs SET status=%s,version=version+1 WHERE id=%s AND status='active'",
            (target, row["id"]),
        )


def advance(db, row, recipient, node, next_id, delay=0):
    db.execute(
        "UPDATE crm.workflow_recipients SET current_node_id=%s,status=%s,due_at=now()+(%s * interval '1 second'),error=NULL WHERE run_id=%s AND contact_id=%s AND status='active'",
        (next_id, "active" if next_id else "completed", delay, row["id"], recipient["contact_id"]),
    )
    finish_run(db, row)


def claim(db):
    control.lock(db)
    recover(db)
    instant = service.now()
    row = db.execute(
        "SELECT r.* FROM crm.workflow_runs r WHERE r.status='active' AND EXISTS(SELECT 1 FROM crm.workflow_recipients p WHERE p.run_id=r.id AND p.status='active' AND p.due_at<=now() AND NOT EXISTS(SELECT 1 FROM crm.workflow_steps s WHERE s.run_id=p.run_id AND s.contact_id=p.contact_id AND s.state='reserved')) ORDER BY r.created_at,r.id FOR UPDATE SKIP LOCKED LIMIT 1"
    ).fetchone()
    if not row:
        return None
    person = db.execute(
        "SELECT p.* FROM crm.workflow_recipients p WHERE p.run_id=%s AND p.status='active' AND p.due_at<=now() AND NOT EXISTS(SELECT 1 FROM crm.workflow_steps s WHERE s.run_id=p.run_id AND s.contact_id=p.contact_id AND s.state='reserved') ORDER BY p.due_at,p.contact_id FOR UPDATE SKIP LOCKED LIMIT 1",
        (row["id"],),
    ).fetchone()
    if not person:
        return None
    try:
        admin = service.authority(db, row)
        service.check_snapshot(db, row, admin, check_all=False)
        snapshot = row["snapshot"]
        doc = snapshot["document"]
        due = scheduled_at(doc["schedule"], instant)
        if due > instant:
            db.execute(
                "UPDATE crm.workflow_recipients SET due_at=%s WHERE run_id=%s AND status='active'",
                (due, row["id"]),
            )
            return None
        recipient = next(p for p in snapshot["audience"] if p["id"] == str(person["contact_id"]))
        node = service.render(
            next(n for n in doc["nodes"] if n["id"] == person["current_node_id"]), recipient
        )
        external = node["kind"] in service.EXTERNAL
        if external:
            midnight = (
                instant.astimezone(BOGOTA)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(UTC)
            )
            counts = db.execute(
                "SELECT count(*) AS total,count(*) FILTER(WHERE reserved_at>=%s) AS today FROM crm.workflow_steps WHERE run_id=%s AND external",
                (midnight, row["id"]),
            ).fetchone()
            if counts["total"] >= snapshot["max_external_actions"]:
                raise HTTPException(409, "workflow_action_limit")
            if counts["today"] >= doc["schedule"]["daily_limit"]:
                tomorrow = (
                    (instant.astimezone(BOGOTA) + timedelta(days=1))
                    .replace(hour=0, minute=0, second=0, microsecond=0)
                    .astimezone(UTC)
                )
                db.execute(
                    "UPDATE crm.workflow_recipients SET due_at=%s WHERE run_id=%s AND status='active'",
                    (scheduled_at(doc["schedule"], tomorrow), row["id"]),
                )
                return None
        request_id = uuid4()
        plan = snapshot["plans"][recipient["id"]][node["id"]]
        payload = service.check_plan(db, node, plan, admin, request_id)
        # Provider validation may cross the exclusive schedule boundary.
        fresh = service.now()
        due = scheduled_at(doc["schedule"], fresh)
        if due > fresh:
            db.execute(
                "UPDATE crm.workflow_recipients SET due_at=%s WHERE run_id=%s AND status='active'",
                (due, row["id"]),
            )
            return None
        reserved = db.execute(
            "INSERT INTO crm.workflow_steps(id,run_id,contact_id,node_id,state,external) VALUES(%s,%s,%s,%s,'reserved',%s) ON CONFLICT(run_id,contact_id,node_id) DO NOTHING RETURNING id",
            (request_id, row["id"], person["contact_id"], node["id"], external),
        ).fetchone()
        if not reserved:
            raise HTTPException(409, "workflow_step_already_reserved")
        service.event(
            db,
            row["id"],
            "reserved",
            "Acción reservada una sola vez.",
            person["contact_id"],
            node["id"],
        )
        if external:
            return {
                "id": request_id,
                "run_id": row["id"],
                "contact_id": person["contact_id"],
                "node": node,
                "payload": payload,
                "admin": admin,
            }
        current = service.contact(db, person["contact_id"])
        next_id, delay = node["next_id"], 0
        if node["kind"] == "condition":
            value = current.get(node["settings"]["field"])
            if value is None:
                raise HTTPException(409, "workflow_condition_data_missing")
            next_id = node["on_true"] if value == node["settings"]["value"] else node["on_false"]
        elif node["kind"] == "wait":
            delay = node["settings"]["hours"] * 3600
        elif node["kind"] == "crm_note":
            services.add_note(
                db, current["deal_id"], crm_models.NoteInput(body=node["settings"]["body"]), admin
            )
        elif node["kind"] == "crm_task":
            date = instant.astimezone(BOGOTA).date() + timedelta(days=node["settings"]["due_days"])
            services.create_task(
                db,
                crm_models.TaskInput(
                    contact_id=person["contact_id"], title=node["settings"]["title"], due_date=date
                ),
                admin,
            )
        db.execute(
            "UPDATE crm.workflow_steps SET state='completed',completed_at=now() WHERE id=%s",
            (request_id,),
        )
        service.event(
            db,
            row["id"],
            "completed",
            "Acción CRM completada."
            if node["kind"] in {"crm_note", "crm_task"}
            else "Paso completado.",
            person["contact_id"],
            node["id"],
        )
        advance(db, row, person, node, next_id, delay)
    except HTTPException:
        hold(db, row, "workflow_validation_changed", person)
    return None


def dispatch(item):
    if item["node"]["kind"] == "retell_call":
        from ..retell import service as retell

        result = retell.execute_reserved(item["payload"], item["admin"])
        return {
            "state": "completed" if result.get("status") == "completed" else "unknown",
            "receipt": {
                "provider": "retell",
                "submission": result.get("status"),
                "data": result.get("data", {}),
            },
        }
    from ..social import workflow

    return workflow.dispatch(item["payload"], str(item["id"]))


def finalize(db, item, result):
    row = service.run_row(db, item["run_id"], True)
    step = db.execute(
        "SELECT state FROM crm.workflow_steps WHERE id=%s FOR UPDATE", (item["id"],)
    ).fetchone()
    if not step or step["state"] != "reserved":
        return
    state = result.get("state")
    if state not in {"completed", "failed", "unknown"}:
        state = "unknown"
    from ..retell.service import safe_result

    receipt = safe_result(result.get("receipt", {}))
    db.execute(
        "UPDATE crm.workflow_steps SET state=%s,completed_at=now(),receipt=%s WHERE id=%s",
        (state, Jsonb(receipt), item["id"]),
    )
    person = db.execute(
        "SELECT * FROM crm.workflow_recipients WHERE run_id=%s AND contact_id=%s FOR UPDATE",
        (row["id"], item["contact_id"]),
    ).fetchone()
    service.event(
        db,
        row["id"],
        "submitted" if state == "completed" else state,
        "Proveedor aceptó la solicitud; no confirma entrega, respuesta ni venta."
        if state == "completed"
        else "Resultado no confirmado; se retiene sin reintento automático.",
        item["contact_id"],
        item["node"]["id"],
    )
    if state == "completed":
        advance(db, row, person, item["node"], item["node"]["next_id"])
    else:
        status = "unknown" if state == "unknown" else "blocked"
        db.execute(
            "UPDATE crm.workflow_recipients SET status=%s,error='dispatch_held' WHERE run_id=%s AND contact_id=%s AND status='active'",
            (status, row["id"], item["contact_id"]),
        )
        db.execute(
            "UPDATE crm.workflow_runs SET status=%s,version=version+1 WHERE id=%s AND status NOT IN ('stopped','completed')",
            (status, row["id"]),
        )


def tick():
    with connect() as db:
        item = claim(db)
    if not item:
        return False
    try:
        with connect() as db:
            control.lock(db)
            row = service.run_row(db, item["run_id"], True)
            if row["status"] != "active":
                finalize(
                    db,
                    item,
                    {"state": "failed", "receipt": {"submission": "cancelled_before_dispatch"}},
                )
                return False
            admin = service.authority(db, row)
            service.check_snapshot(db, row, admin, check_all=False)
            fresh = service.now()
            if scheduled_at(row["snapshot"]["document"]["schedule"], fresh) > fresh:
                # Keep the committed reservation held; never reopen it for retry.
                finalize(
                    db,
                    item,
                    {
                        "state": "failed",
                        "receipt": {"submission": "schedule_closed_before_dispatch"},
                    },
                )
                return False
        result = dispatch(item)
    except Exception:  # noqa: BLE001 - uncertain dispatch never reopens a reservation
        result = {"state": "unknown", "receipt": {}}
    with connect() as db:
        finalize(db, item, result)
    return True


def verified_reply(db, normalized):
    """Only called after existing webhook authentication and first deduplicated insert."""
    if not normalized:
        return
    control.lock(db)
    rows = db.execute(
        "SELECT * FROM crm.workflow_runs WHERE status IN ('active','paused') AND snapshot->'document'->>'stop_on_reply'='true' FOR UPDATE"
    ).fetchall()
    for row in rows:
        if not row["started_at"]:
            continue
        try:
            sent = datetime.fromisoformat(normalized["sent_at"])
            if (
                sent.tzinfo is None
                or sent < row["started_at"]
                or sent > service.now() + timedelta(minutes=5)
            ):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        for cid, plans in row["snapshot"]["plans"].items():
            exact = False
            for node_id, plan in plans.items():
                if not all(
                    plan.get(k) == normalized.get(k) and plan.get(k) is not None
                    for k in ("account_id", "participant_id", "profile_id", "platform")
                ):
                    continue
                conversation = plan.get("conversation_id")
                if conversation is None and plan.get("kind") == "whatsapp_template":
                    step = db.execute(
                        "SELECT receipt,reserved_at,state FROM crm.workflow_steps WHERE run_id=%s AND contact_id=%s AND node_id=%s",
                        (row["id"], cid, node_id),
                    ).fetchone()
                    if not step or sent < step["reserved_at"]:
                        continue
                    # New thread is bound to the reviewed phone. If a safe receipt supplied
                    # its channel ID, it is an additional required identity, never overwritten.
                    conversation = step["receipt"].get("conversation_id")
                    if not conversation:
                        exact = bool(normalized.get("conversation_id"))
                        break
                if conversation and conversation == normalized.get("conversation_id"):
                    exact = True
                    break
            if exact:
                changed = db.execute(
                    "UPDATE crm.workflow_recipients SET status='stopped',error='verified_inbound_reply' WHERE run_id=%s AND contact_id=%s AND status='active' RETURNING contact_id",
                    (row["id"], cid),
                ).fetchone()
                if changed:
                    service.event(
                        db,
                        row["id"],
                        "reply",
                        "Respuesta entrante verificada: se detuvieron los pasos siguientes.",
                        cid,
                    )
        finish_run(db, row)


def _loop():
    global _heartbeat
    while not _stop.is_set():
        try:
            with connect() as db:
                db.execute("SELECT id FROM crm.workflow_runs LIMIT 1")
            _heartbeat = monotonic()
            tick()
        except Exception:  # noqa: BLE001 - no provider error bodies in runtime logs
            _heartbeat = 0
        _stop.wait(1)
    _heartbeat = 0


def start():
    global _thread
    if enabled() and (_thread is None or not _thread.is_alive()):
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="crm-workflows", daemon=True)
        _thread.start()


def stop():
    global _heartbeat
    _stop.set()
    _heartbeat = 0
    if _thread:
        _thread.join(timeout=2)
