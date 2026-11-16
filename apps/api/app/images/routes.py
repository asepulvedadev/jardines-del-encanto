"""Authenticated private image generation and byte previews; no public URLs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from ..crm import security
from ..crm.database import connect
from . import assets, models, service

router = APIRouter(prefix="/crm/images")
Admin = Annotated[dict, Depends(security.session)]
HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


@router.get("/catalog")
def catalog(admin: Admin):
    with connect() as db:
        return service.catalog(db, admin)


@router.get("/assets/{asset_id}/content")
def asset_content(asset_id: str, admin: Admin):
    entry, data = assets.get(asset_id)
    return Response(content=data, media_type=entry["mime_type"], headers=HEADERS)


@router.post("", status_code=202)
def generate(args: models.Generate, admin: Admin):
    with connect() as db:
        return service.enqueue(db, args, admin)


@router.get("/{image_id}")
def status(image_id: UUID, admin: Admin):
    with connect() as db:
        return service.status(db, image_id, admin)


@router.get("/{image_id}/content")
def content(image_id: UUID, admin: Admin):
    with connect() as db:
        data = service.content(db, image_id, admin)
    return Response(content=data, media_type="image/png", headers=HEADERS)
