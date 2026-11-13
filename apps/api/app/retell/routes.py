"""Administrator-only Retell configuration and one-shot browser session claims."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from ..control.models import Empty
from ..crm import security
from ..crm.database import connect
from . import editor, inventory, models, service

router = APIRouter(prefix="/crm/retell")
Admin = Annotated[dict, Depends(security.session)]


@router.get("/settings")
def settings(admin: Admin):
    with connect() as db:
        return service.settings(db)


@router.get("/results")
async def results(request: Request, admin: Admin):
    if request.query_params:
        raise HTTPException(422, "invalid_input")
    # Reject the first nonempty chunk without buffering an unbounded GET body.
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(422, "invalid_input")
    with connect() as db:
        return service.results(db, admin)


@router.post("/settings")
def configure(data: models.Configure, admin: Admin):
    return service.configure(data, admin)


@router.post("/disconnect")
def disconnect(data: models.Revision, admin: Admin):
    return service.configure(data, admin, disconnect=True)


@router.post("/catalog")
def catalog(data: models.Revision, admin: Admin):
    with connect() as db:
        return service.catalog(db, data.revision)


@router.post("/schema")
def schema(data: models.Schema, admin: Admin):
    with connect() as db:
        return service.schema(db, data)


@router.post("/sessions/{proposal_id}/claim")
def claim(proposal_id: UUID, data: Empty, admin: Admin):
    return service.claim(proposal_id, admin)


@router.post("/inventory")
def automatic_inventory(data: models.Revision, request: Request, admin: Admin):
    if request.query_params:
        raise HTTPException(422, "invalid_input")
    return inventory.synchronize(data, admin)


@router.post("/read")
def automatic_read(data: models.AutomaticRead, request: Request, admin: Admin):
    if request.query_params:
        raise HTTPException(422, "invalid_input")
    return inventory.read(data, admin)


@router.post("/editor")
def editor_snapshot(data: models.EditorRead, request: Request, admin: Admin):
    if request.query_params:
        raise HTTPException(422, "invalid_input")
    return editor.snapshot(data, admin)
