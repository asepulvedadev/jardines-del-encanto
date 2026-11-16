from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from ..crm.models import Input

ASSET_IDS = frozenset(
    {"logo-white", "logo-transparent", "photo-aerial", "photo-entrance", "photo-gate"}
)


class Generate(Input):
    request_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    reference_ids: list[str] = Field(default_factory=list, max_length=3)
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024"

    @field_validator("prompt", mode="before")
    @classmethod
    def clean_prompt(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("reference_ids")
    @classmethod
    def references(cls, value):
        if len(value) != len(set(value)) or any(key not in ASSET_IDS for key in value):
            raise ValueError("invalid_reference")
        return value
