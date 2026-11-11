from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from . import security
from .database import connect
from .models import ContactEdit, ContactInput, DealEdit, Login, NoteInput, TaskEdit, TaskInput

router = APIRouter(prefix="/crm")
Admin = Annotated[dict, Depends(security.session)]
STAGES = {
    "new": "Nuevo",
    "contacted": "Contactado",
    "visit": "Visita",
    "negotiation": "Negociación",
    "won": "Ganado",
    "lost": "Descartado",
}


def activity(db, deal_id, actor_id, kind, body):
    return db.execute(
        """INSERT INTO crm.activities(deal_id, actor_id, kind, body)
           VALUES (%s,%s,%s,%s) RETURNING *""",
        (deal_id, actor_id, kind, body),
    ).fetchone()


def updated_or_conflict(db, record, table, record_id):
    if record:
        return record
    # Only fixed application-owned identifiers reach this helper.
    from psycopg import sql

    exists = db.execute(
        sql.SQL("SELECT 1 FROM crm.{} WHERE id = %s").format(sql.Identifier(table)), (record_id,)
    ).fetchone()
    raise HTTPException(409 if exists else 404, "record_changed" if exists else "not_found")


@router.post("/auth/login")
def login(data: Login, request: Request, response: Response):
    security.require_origin(request)
    user = security.authenticate(data.username, data.password)
    return security.create_session(user, request, response)


@router.get("/auth/session")
def current_session(admin: Admin):
    return {
        "user": {"username": admin["username"], "role": admin["role"]},
        "csrf_token": admin["csrf_token"],
    }


@router.post("/auth/logout")
def logout(admin: Admin, response: Response):
    with connect() as db:
        db.execute("DELETE FROM crm.sessions WHERE token_hash = %s", (admin["token_hash"],))
    response.delete_cookie(
        security.cookie_name(),
        path="/",
        secure=security.secure_cookies(),
        httponly=True,
        samesite="lax",
    )
    return {"status": "ok"}


@router.get("/workspace")
def workspace(admin: Admin):
    with connect() as db:
        # A consistent snapshot avoids mixing counts and rows from concurrent writes.
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        contacts = db.execute(
            """SELECT c.*, r.code AS registration_code FROM crm.contacts c
               LEFT JOIN crm.landing_registrations r ON r.contact_id=c.id
               ORDER BY c.created_at DESC, c.id LIMIT 501"""
        ).fetchall()
        deals = db.execute(
            "SELECT * FROM crm.deals ORDER BY created_at DESC, id LIMIT 501"
        ).fetchall()
        tasks = db.execute(
            "SELECT * FROM crm.tasks ORDER BY completed, due_date, id LIMIT 501"
        ).fetchall()
        activities = db.execute(
            "SELECT * FROM crm.activities ORDER BY created_at DESC, id LIMIT 100"
        ).fetchall()
        counts = db.execute(
            """SELECT (SELECT count(*) FROM crm.contacts) AS contacts,
               (SELECT count(*) FROM crm.deals WHERE stage NOT IN ('won','lost')) AS active,
               (SELECT count(*) FROM crm.deals WHERE stage = 'won') AS won,
               (SELECT count(*) FROM crm.tasks WHERE NOT completed) AS pending,
               (SELECT count(*) FROM crm.tasks WHERE NOT completed
                AND due_date < (now() AT TIME ZONE 'America/Bogota')::date) AS overdue"""
        ).fetchone()
    return {
        "contacts": contacts[:500],
        "deals": deals[:500],
        "tasks": tasks[:500],
        "activities": activities,
        "counts": counts,
        "limited": any(len(rows) > 500 for rows in (contacts, deals, tasks)),
    }


@router.post("/contacts", status_code=201)
def create_contact(data: ContactInput, admin: Admin):
    with connect() as db:
        record = db.execute(
            "INSERT INTO crm.contacts(name, phone, source) VALUES (%s,%s,%s) RETURNING *",
            (data.name, data.phone, data.source),
        ).fetchone()
        deal = db.execute(
            "INSERT INTO crm.deals(contact_id) VALUES (%s) RETURNING id", (record["id"],)
        ).fetchone()
        activity(
            db,
            deal["id"],
            admin["id"],
            "created",
            "Cliente registrado. Negociación creada en Nuevo.",
        )
    return record


@router.patch("/contacts/{contact_id}")
def edit_contact(contact_id: UUID, data: ContactEdit, admin: Admin):
    with connect() as db:
        record = db.execute(
            """UPDATE crm.contacts SET name=%s, phone=%s, source=%s, version=version+1,
               updated_at=now() WHERE id=%s AND version=%s RETURNING *""",
            (data.name, data.phone, data.source, contact_id, data.version),
        ).fetchone()
        updated_or_conflict(db, record, "contacts", contact_id)
        deal = db.execute("SELECT id FROM crm.deals WHERE contact_id=%s", (contact_id,)).fetchone()
        activity(db, deal["id"], admin["id"], "contact_updated", "Datos del cliente actualizados.")
    return record


@router.get("/deals/{deal_id}/activities")
def deal_activities(deal_id: UUID, admin: Admin):
    with connect() as db:
        exists = db.execute("SELECT id FROM crm.deals WHERE id=%s", (deal_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "not_found")
        return db.execute(
            "SELECT * FROM crm.activities WHERE deal_id=%s ORDER BY created_at DESC, id LIMIT 100",
            (deal_id,),
        ).fetchall()


@router.patch("/deals/{deal_id}")
def move_deal(deal_id: UUID, data: DealEdit, admin: Admin):
    with connect() as db:
        record = db.execute(
            """UPDATE crm.deals SET stage=%s, version=version+1, updated_at=now()
               WHERE id=%s AND version=%s RETURNING *""",
            (data.stage, deal_id, data.version),
        ).fetchone()
        updated_or_conflict(db, record, "deals", deal_id)
        activity(
            db, deal_id, admin["id"], "stage_changed", f"Etapa actualizada a {STAGES[data.stage]}."
        )
    return record


@router.post("/deals/{deal_id}/notes", status_code=201)
def add_note(deal_id: UUID, data: NoteInput, admin: Admin):
    with connect() as db:
        if not db.execute("SELECT 1 FROM crm.deals WHERE id=%s", (deal_id,)).fetchone():
            raise HTTPException(404, "not_found")
        record = activity(db, deal_id, admin["id"], "note", data.body)
    return record


@router.post("/tasks", status_code=201)
def create_task(data: TaskInput, admin: Admin):
    with connect() as db:
        deal = db.execute(
            "SELECT id FROM crm.deals WHERE contact_id=%s", (data.contact_id,)
        ).fetchone()
        if not deal:
            raise HTTPException(404, "not_found")
        record = db.execute(
            "INSERT INTO crm.tasks(contact_id, title, due_date) VALUES (%s,%s,%s) RETURNING *",
            (data.contact_id, data.title, data.due_date),
        ).fetchone()
        activity(
            db,
            deal["id"],
            admin["id"],
            "task_created",
            f"Seguimiento: {data.title} · {data.due_date:%d/%m/%Y}.",
        )
    return record


@router.patch("/tasks/{task_id}")
def complete_task(task_id: UUID, data: TaskEdit, admin: Admin):
    with connect() as db:
        record = db.execute(
            """UPDATE crm.tasks SET completed=%s, version=version+1
               WHERE id=%s AND version=%s RETURNING *""",
            (data.completed, task_id, data.version),
        ).fetchone()
        updated_or_conflict(db, record, "tasks", task_id)
        deal = db.execute(
            "SELECT id FROM crm.deals WHERE contact_id=%s", (record["contact_id"],)
        ).fetchone()
        activity(
            db,
            deal["id"],
            admin["id"],
            "task_completed" if data.completed else "task_reopened",
            f"{'Completado' if data.completed else 'Reabierto'}: {record['title']}.",
        )
    return record
