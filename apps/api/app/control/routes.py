"""Authenticated human control plane; automation never bypasses confirmation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from ..crm import security
from ..crm.database import connect
from ..hermes import broker
from . import models, service

router = APIRouter(prefix="/crm/control")
Admin = Annotated[dict, Depends(security.session)]


@router.get("/catalog")
def catalog(admin: Admin):
    with connect() as db:
        return service.catalog(db)


@router.post("/items", status_code=201)
def create(data: models.ItemCreate, admin: Admin):
    with connect() as db:
        return service.create_item(db, data, admin)


@router.patch("/items/{item_id}")
def update(item_id: UUID, data: models.ItemUpdate, admin: Admin):
    with connect() as db:
        return service.update_item(db, item_id, data, admin)


@router.post("/items/{item_id}/run")
def run(item_id: UUID, data: models.Run, admin: Admin):
    with connect() as db:
        service.lock(db)
        return broker.run_item(db, item_id, data.arguments, admin)


@router.patch("/connections/{key}")
def connection(key: str, data: models.ConnectionUpdate, admin: Admin):
    with connect() as db:
        return service.update_connection(db, key, data, admin)
