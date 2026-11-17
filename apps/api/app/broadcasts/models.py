from typing import Literal
from uuid import UUID

from pydantic import Field

from ..crm.models import Input


class Preview(Input):
    csv_text: str = Field(min_length=1, max_length=512_000)
    name_column: str = Field(min_length=1, max_length=120)
    phone_column: str = Field(min_length=1, max_length=120)


class Create(Preview):
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    account_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,160}$")
    template_name: str = Field(min_length=1, max_length=512)
    template_language: str = Field(min_length=1, max_length=20)
    values: dict[str, str] = Field(default_factory=dict, max_length=40)
    consent_confirmed: Literal[True]
    consent_note: str = Field(min_length=8, max_length=500)


class Account(Input):
    account_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,160}$")


class Confirm(Input):
    version: int = Field(ge=1)
    count: int = Field(ge=1, le=500)
    confirmed: Literal[True]


class Filter(Input):
    campaign_id: UUID | None = None
    cold_only: bool = False
