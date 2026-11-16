"""Administrator configuration and isolated simulation inspection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from ..crm import security
from ..crm.database import connect
from . import profile, simulations
from . import profile_models as models

router = APIRouter(prefix="/crm/sara")
Admin = Annotated[dict, Depends(security.session)]


@router.get("/config")
def get_config(admin: Admin):
    with connect() as db:
        return profile.get(db)


@router.patch("/config")
def edit_config(data: models.ProfileUpdate, admin: Admin):
    with connect() as db:
        return profile.update(db, data, admin)


@router.get("/config/versions")
def versions(admin: Admin):
    with connect() as db:
        return {
            "versions": db.execute(
                "SELECT version,document,source,author,created_at FROM crm.sara_profile_versions ORDER BY version DESC LIMIT 30"
            ).fetchall()
        }


@router.post("/simulations", status_code=201)
def create_simulation(data: models.SimulationCreate, admin: Admin):
    with connect() as db:
        return simulations.create(db, data, admin)


@router.get("/simulations")
def list_simulations(admin: Admin):
    with connect() as db:
        return {
            "simulations": [
                simulations.view(row)
                for row in db.execute(
                    "SELECT * FROM crm.sara_simulations WHERE owner_id=%s ORDER BY created_at DESC,id DESC LIMIT 20",
                    (admin["id"],),
                ).fetchall()
            ]
        }


@router.get("/simulations/{identifier}")
def simulation_status(identifier: UUID, admin: Admin):
    with connect() as db:
        return simulations.status(db, identifier, admin)
