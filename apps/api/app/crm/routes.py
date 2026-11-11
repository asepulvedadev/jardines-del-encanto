from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from . import security, services
from .database import connect
from .models import ContactEdit, ContactInput, DealEdit, Login, NoteInput, TaskEdit, TaskInput

router = APIRouter(prefix="/crm")
Admin = Annotated[dict, Depends(security.session)]
# Preserve the existing injectable activity boundary for human-route fault checks.
activity = services.activity


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
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return services.workspace(db, admin)


@router.post("/contacts", status_code=201)
def create_contact(data: ContactInput, admin: Admin):
    with connect() as db:
        return services.create_contact(db, data, admin, record_activity=activity)


@router.patch("/contacts/{contact_id}")
def edit_contact(contact_id: UUID, data: ContactEdit, admin: Admin):
    with connect() as db:
        return services.edit_contact(db, contact_id, data, admin)


@router.get("/deals/{deal_id}/activities")
def deal_activities(deal_id: UUID, admin: Admin):
    with connect() as db:
        return services.deal_activities(db, deal_id, admin)


@router.patch("/deals/{deal_id}")
def move_deal(deal_id: UUID, data: DealEdit, admin: Admin):
    with connect() as db:
        return services.move_deal(db, deal_id, data, admin)


@router.post("/deals/{deal_id}/notes", status_code=201)
def add_note(deal_id: UUID, data: NoteInput, admin: Admin):
    with connect() as db:
        return services.add_note(db, deal_id, data, admin)


@router.post("/tasks", status_code=201)
def create_task(data: TaskInput, admin: Admin):
    with connect() as db:
        return services.create_task(db, data, admin)


@router.patch("/tasks/{task_id}")
def complete_task(task_id: UUID, data: TaskEdit, admin: Admin):
    with connect() as db:
        return services.complete_task(db, task_id, data, admin)
