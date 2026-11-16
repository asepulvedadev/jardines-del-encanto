"""Editable agent preferences, never credentials, permissions or runtime source."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from ..crm.models import Input


class Profile(Input):
    name: str = Field(default="Sara IA", min_length=1, max_length=80)
    instructions: str = Field(min_length=1, max_length=2000)
    knowledge: str = Field(default="", max_length=4000)
    greeting: str = Field(
        default="Hola, soy Sara, asistente virtual de Jardines del Encanto.", max_length=300
    )
    response_style: Literal["brief", "balanced", "detailed"] = "brief"

    @field_validator("name", "instructions", "knowledge", "greeting", mode="before")
    @classmethod
    def printable(cls, value):
        if not isinstance(value, str):
            raise ValueError("Invalid content")  # noqa: TRY004 - Pydantic v2 surfaces TypeError as 500.
        if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("Invalid content")
        return value.strip()


class ProfileUpdate(Input):
    version: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    instructions: str | None = Field(default=None, min_length=1, max_length=2000)
    knowledge: str | None = Field(default=None, max_length=4000)
    greeting: str | None = Field(default=None, max_length=300)
    response_style: Literal["brief", "balanced", "detailed"] | None = None


class Learning(Input):
    version: int = Field(ge=1, strict=True)
    content: str = Field(min_length=1, max_length=1000)


class SimulationCreate(Input):
    request_id: UUID
    title: str = Field(default="Simulación de atención", min_length=1, max_length=120)
    customer_turns: list[str] = Field(min_length=1, max_length=4)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("customer_turns")
    @classmethod
    def bounded_turns(cls, values):
        if any(
            not value.strip()
            or len(value) > 800
            or any(ord(c) < 32 and c not in "\n\r\t" for c in value)
            for value in values
        ):
            raise ValueError("Invalid synthetic conversation")
        return values


class SimulationID(Input):
    id: UUID
