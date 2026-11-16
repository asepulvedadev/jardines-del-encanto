"""No GET side effects, implicit read receipts, background replies or generic proxy."""

from uuid import UUID

from fastapi import APIRouter

from ..crm.routes import Admin
from ..social import config
from . import service
from .models import REGISTRY, AccountQuery, Confirmation, Execute

router = APIRouter(prefix="/crm/inbox")


@router.get("/lead-capture")
def lead_capture_status(admin: Admin):
    from ..social.lead_capture_worker import status

    return status()


@router.get("/catalog")
def catalog(admin: Admin):
    return REGISTRY


@router.get("/accounts")
def accounts(admin: Admin):
    service.enabled()
    return {"items": service.accounts(config.required())}


@router.post("/read")
def read(data: Execute, admin: Admin):
    return service.read(data)


@router.post("/prepare", status_code=201)
def prepare(data: Execute, admin: Admin):
    return service.prepare(data, admin)


@router.get("/actions")
def history(admin: Admin):
    return service.history(admin)


@router.get("/actions/{identifier}")
def action(identifier: UUID, admin: Admin):
    return service.action(identifier, admin)


@router.post("/actions/{identifier}/confirm")
def confirm(identifier: UUID, data: Confirmation, admin: Admin):
    return service.confirm(identifier, admin)


@router.post("/templates")
def templates(data: AccountQuery, admin: Admin):
    return service.templates(data.account_id)
