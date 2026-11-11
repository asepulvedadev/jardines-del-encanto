"""Administrator-only project MCP authorization; no generic tool execution API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..crm import security
from . import mcp

router = APIRouter(prefix="/crm/social/mcp")
Admin = Annotated[dict, Depends(security.session)]


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartInput(EmptyInput):
    replace: bool = False


class CallbackInput(EmptyInput):
    state: SecretStr = Field(min_length=1, max_length=128)
    code: SecretStr | None = Field(default=None, max_length=4096)
    issuer: str | None = Field(default=None, max_length=256)
    error: str | None = Field(default=None, max_length=256)


@router.get("/status")
def status(admin: Admin):
    return mcp.status()


@router.post("/start")
def start(data: StartInput, admin: Admin):
    return mcp.begin(admin, data.replace)


@router.post("/complete")
def complete(data: CallbackInput, admin: Admin):
    return mcp.complete(
        admin,
        data.state.get_secret_value(),
        data.code.get_secret_value() if data.code else None,
        data.issuer,
        data.error,
    )


@router.post("/check")
def check(data: EmptyInput, admin: Admin):
    return mcp.check()


@router.post("/disconnect")
def disconnect(data: EmptyInput, admin: Admin):
    return mcp.disconnect()
