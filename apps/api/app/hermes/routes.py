"""Private bridge handoff; internal endpoints accept only one scoped bearer identity."""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from ..control import models, service
from ..crm import security
from ..crm.database import connect
from . import bridge, broker

router = APIRouter(prefix="/crm/hermes")
internal_router = APIRouter(prefix="/internal/hermes")
Admin = Annotated[dict, Depends(security.session)]


def service_identity(request: Request):
    bearer = request.headers.get("authorization", "")
    if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", bearer):
        raise HTTPException(401, "service_authentication_required")
    return bearer


InternalAuth = Annotated[str, Depends(service_identity)]


@router.get("/status")
def status(admin: Admin):
    state = bridge.health()
    with connect() as db:
        pref = db.execute(
            "SELECT enabled FROM crm.control_connections WHERE key='hermes'"
        ).fetchone()
        count = len(broker.tools(db)[0]["function"]["parameters"]["properties"]["action"]["enum"])
    return {**state, "enabled": pref["enabled"], "tools_count": count}


@router.post("/actions")
def actions(data: models.Action, admin: Admin):
    with connect() as db:
        return broker.dispatch(db, data.action, data.arguments, admin)


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: UUID, data: models.Version, admin: Admin):
    return broker.resolve(proposal_id, data.version, admin, True)


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: UUID, data: models.Version, admin: Admin):
    return broker.resolve(proposal_id, data.version, admin, False)


@router.post("/chat")
def chat(data: models.Chat, admin: Admin):
    if not bridge.health()["available"]:
        raise HTTPException(503, "hermes_unavailable")
    with connect() as db:
        service.require_connections(db, "hermes")
        run_id, token = broker.issue(db, admin, data.message)
    try:
        bridge.request("/run", {"token": token}, timeout=90)
    except HTTPException:
        with connect() as db:
            db.execute(
                "UPDATE crm.hermes_runs SET state='failed' WHERE id=%s AND state!='finished'",
                (run_id,),
            )
        raise HTTPException(503, "hermes_unavailable") from None
    with connect() as db:
        run = db.execute("SELECT * FROM crm.hermes_runs WHERE id=%s", (run_id,)).fetchone()
        if not run or run["state"] != "finished":
            raise HTTPException(503, "hermes_unavailable")
        return broker.run_result(db, run)


@internal_router.post("/claim")
def claim(data: models.Empty, bearer: InternalAuth):
    with connect() as db:
        run = broker.identity(db, bearer)
        return broker.claim(db, run)


@internal_router.post("/call")
def call(data: models.BrokerCall, bearer: InternalAuth):
    with connect() as db:
        run = broker.identity(db, bearer)
        return broker.call(db, run, data)


@internal_router.post("/finish")
def finish(data: models.Finish, bearer: InternalAuth):
    with connect() as db:
        run = broker.identity(db, bearer)
        return broker.finish(db, run, data)
