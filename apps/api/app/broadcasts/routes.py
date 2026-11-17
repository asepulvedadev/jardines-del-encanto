from uuid import UUID

from fastapi import APIRouter

from ..crm import services as crm
from ..crm.database import connect
from ..crm.models import Input
from ..crm.routes import Admin
from . import models, service

router = APIRouter(prefix="/crm/broadcasts")


@router.get("")
def listing(admin: Admin):
    with connect() as db:
        return service.listing(db)


@router.get("/catalog")
def catalog(admin: Admin):
    return service.catalog()


@router.post("/templates")
def templates(data: models.Account, admin: Admin):
    return service.catalog(data.account_id)


@router.post("/preview")
def preview(data: models.Preview, admin: Admin):
    return service.parse_csv(data)


@router.post("", status_code=201)
def create(data: models.Create, admin: Admin):
    return service.create(data, admin)


@router.post("/filter")
def filtered(data: models.Filter, admin: Admin):
    with connect() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return crm.workspace(db, admin, broadcast_filter=data)


@router.get("/{identifier}")
def detail(identifier: UUID, admin: Admin):
    with connect() as db:
        return service.detail(db, identifier)


@router.post("/{identifier}/send")
def send(identifier: UUID, data: models.Confirm, admin: Admin):
    return service.send(identifier, data, admin)


@router.post("/{identifier}/refresh")
def refresh(identifier: UUID, data: Input, admin: Admin):
    return service.refresh(identifier)
