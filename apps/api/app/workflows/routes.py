"""Authenticated human-only activation; typed bounded workflow routes."""

from uuid import UUID

from fastapi import APIRouter

from ..crm.database import connect
from ..crm.routes import Admin
from . import models, service

router = APIRouter(prefix="/crm/workflows")


@router.get("/catalog")
def catalog(admin: Admin):
    with connect() as db:
        return service.catalog(db)


@router.get("/definitions")
def definitions(admin: Admin):
    with connect() as db:
        return service.definitions(db)


@router.post("/definitions", status_code=201)
def create(data: models.DefinitionCreate, admin: Admin):
    with connect() as db:
        return service.create(db, data, admin)


@router.patch("/definitions/{record_id}")
def update(record_id: UUID, data: models.DefinitionUpdate, admin: Admin):
    with connect() as db:
        return service.update(db, record_id, data, admin)


@router.post("/options")
def options(data: models.Options, admin: Admin):
    with connect() as db:
        return service.options(db, data, admin)


@router.post("/definitions/{record_id}/prepare")
def prepare(record_id: UUID, data: models.Prepare, admin: Admin):
    with connect() as db:
        return service.prepare(db, record_id, data, admin)


@router.post("/runs/{record_id}/activate")
def activate(record_id: UUID, data: models.Activate, admin: Admin):
    with connect() as db:
        return service.activate(db, record_id, data, admin)


@router.post("/runs/{record_id}/pause")
def pause(record_id: UUID, data: models.Version, admin: Admin):
    with connect() as db:
        return service.transition(db, record_id, "pause", data, admin)


@router.post("/runs/{record_id}/resume")
def resume(record_id: UUID, data: models.Version, admin: Admin):
    with connect() as db:
        return service.transition(db, record_id, "resume", data, admin)


@router.post("/runs/{record_id}/stop")
def stop(record_id: UUID, data: models.Version, admin: Admin):
    with connect() as db:
        return service.transition(db, record_id, "stop", data, admin)


@router.get("/runs")
def runs(admin: Admin):
    with connect() as db:
        return service.runs(db)


@router.get("/runs/{record_id}")
def detail(record_id: UUID, admin: Admin):
    with connect() as db:
        return service.detail(db, record_id)
