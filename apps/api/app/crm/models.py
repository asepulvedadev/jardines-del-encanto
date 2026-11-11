import re
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Source = Literal["in_person", "social_campaign", "web", "referral", "whatsapp", "other"]
Stage = Literal["new", "contacted", "won"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    # Passwords must never be normalized or whitespace-stripped.
    password: str = Field(min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ContactInput(Input):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    source: Source

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value):
        if not re.fullmatch(r"\+?[0-9 ()-]+", value):
            raise ValueError("invalid_phone")
        digits = re.sub(r"\D", "", value)
        if len(digits) == 10 and digits.startswith("3"):
            digits = "57" + digits
        if not re.fullmatch(r"[1-9][0-9]{7,14}", digits):
            raise ValueError("invalid_phone")
        return "+" + digits


class ContactEdit(ContactInput):
    version: int = Field(ge=1)


class DealEdit(Input):
    stage: Stage
    version: int = Field(ge=1)


class NoteInput(Input):
    body: str = Field(min_length=1, max_length=2000)


class TaskInput(Input):
    contact_id: UUID
    title: str = Field(min_length=1, max_length=160)
    due_date: date


class TaskEdit(Input):
    completed: bool
    version: int = Field(ge=1)
