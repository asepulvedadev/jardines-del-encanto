"""Administrator-only aggregate reporting; no upstream proxy or public credentials."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ..crm import security
from . import service
from .models import SummaryInput

router = APIRouter(prefix="/crm/analytics")
Admin = Annotated[dict, Depends(security.session)]


@router.get("/summary")
def summary(request: Request, admin: Admin):
    params = request.query_params
    if any(key != "days" for key in params) or len(params.getlist("days")) > 1:
        raise HTTPException(422, "invalid_input")
    days = params.get("days", "7")
    if days not in {"1", "7", "30"}:
        raise HTTPException(422, "invalid_input")
    return service.summary(SummaryInput(days=int(days)))
