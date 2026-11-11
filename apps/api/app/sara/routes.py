"""Authenticated owner-scoped Sara conversation/document routes, without live calls."""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from ..control import service as control
from ..crm import security
from ..crm.database import connect
from ..hermes.routes import status as hermes_status
from . import attachments, models, service

router = APIRouter(prefix="/crm/sara")
Admin = Annotated[dict, Depends(security.session)]


@router.get("/status")
def status(admin: Admin):
    state = hermes_status(admin)
    ready = bool(state["available"] and state.get("history_available", False))
    return {key: state[key] for key in ("enabled", "model", "tools_count")} | {
        "available": ready,
        "voice_available": bool(
            ready and state["enabled"] and state.get("transcription_available", False)
        ),
    }


@router.get("/conversations")
def conversations(admin: Admin, before: UUID | None = None):
    with connect() as db:
        clause, values = "", [admin["id"]]
        if before:
            row = service.owned_conversation(db, before, admin)
            clause = " AND (updated_at,id)<(%s,%s)"
            values.extend((row["updated_at"], row["id"]))
        rows = db.execute(
            "SELECT * FROM crm.sara_conversations WHERE owner_id=%s"
            + clause
            + " ORDER BY updated_at DESC,id DESC LIMIT 31",
            values,
        ).fetchall()
        return {
            "conversations": [service.conversation_view(row) for row in rows[:30]],
            "next_cursor": rows[29]["id"] if len(rows) > 30 else None,
        }


@router.post("/conversations", status_code=201)
def create_conversation(data: models.ConversationCreate, admin: Admin):
    with connect() as db:
        return service.conversation_view(
            db.execute(
                """INSERT INTO crm.sara_conversations(owner_id,title)
            VALUES (%s,%s) RETURNING *""",
                (admin["id"], data.title),
            ).fetchone()
        )


@router.patch("/conversations/{conversation_id}")
def edit_conversation(conversation_id: UUID, data: models.ConversationEdit, admin: Admin):
    with connect() as db:
        service.owned_conversation(db, conversation_id, admin, lock=True)
        return service.conversation_view(
            db.execute(
                """UPDATE crm.sara_conversations SET title=%s,
            updated_at=now() WHERE id=%s AND owner_id=%s RETURNING *""",
                (data.title, conversation_id, admin["id"]),
            ).fetchone()
        )


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: UUID, admin: Admin, before: UUID | None = None):
    return service.messages(conversation_id, before, admin)


@router.post("/conversations/{conversation_id}/messages")
def send(conversation_id: UUID, data: models.MessageInput, admin: Admin):
    return service.send(conversation_id, data, admin)


@router.get("/skills")
def skills(admin: Admin):
    with connect() as db:
        return {
            "skills": [
                {
                    key: value
                    for key, value in control.item_view(db, row).items()
                    if key in ("id", "name", "description", "enabled", "effective")
                }
                | {"content": row["definition"]["content"]}
                for row in control.rows(db)
                if row["kind"] == "skill"
            ]
        }


@router.post("/attachments", status_code=201)
def upload(data: models.AttachmentInput, admin: Admin):
    return attachments.create(data, admin)


@router.get("/attachments/{attachment_id}/content")
def download(attachment_id: UUID, admin: Admin):
    with connect() as db:
        row = db.execute(
            "SELECT data,filename,mime_type FROM crm.sara_attachments WHERE id=%s AND owner_id=%s",
            (attachment_id, admin["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
    return Response(
        bytes(row["data"]),
        media_type=row["mime_type"],
        headers={
            "Content-Disposition": "attachment; filename=attachment; filename*=UTF-8''"
            + quote(row["filename"], safe=""),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
