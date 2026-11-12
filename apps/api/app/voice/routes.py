"""Administrator-only voice settings, private artifacts and one-shot session material."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from ..control.models import Empty
from ..crm import security
from ..crm.database import connect
from ..sara.models import AttachmentInput
from . import models, service

router = APIRouter(prefix="/crm/voice")
Admin = Annotated[dict, Depends(security.session)]


@router.get("/settings")
def settings(admin: Admin):
    with connect() as db:
        return service.settings(db)


@router.post("/settings")
def configure(data: models.Configure, admin: Admin):
    return service.configure(data, admin)


@router.post("/disconnect")
def disconnect(data: models.Revision, admin: Admin):
    return service.configure(data, admin, disconnect=True)


@router.post("/catalog")
def catalog(data: models.Revision, admin: Admin):
    return service.refresh(data, admin)


@router.post("/attachments", status_code=201)
def attachment(data: AttachmentInput, admin: Admin):
    return service.stage(data, admin)


@router.post("/sessions/{proposal_id}/claim")
def claim(proposal_id: UUID, data: Empty, admin: Admin):
    return service.claim(proposal_id, admin)


@router.get("/artifacts/{artifact_id}/content")
def content(artifact_id: UUID, admin: Admin):
    with connect() as db:
        row = db.execute(
            "SELECT data,mime_type FROM crm.voice_artifacts WHERE id=%s AND owner_id=%s AND kind='output'",
            (artifact_id, admin["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    return Response(
        content=bytes(row["data"]),
        media_type=row["mime_type"],
        headers={
            "Content-Disposition": 'attachment; filename="sara-audio.mp3"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
