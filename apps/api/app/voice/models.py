"""Strict shared voice operations; credentials never enter broker arguments."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from ..crm.models import Input

ProviderID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)]
DefaultID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{0,128}$", strict=True)]


class Defaults(Input):
    voice_id: DefaultID = ""
    model_id: DefaultID = ""
    agent_id: DefaultID = ""
    phone_number_id: DefaultID = ""


class Revision(Input):
    revision: int = Field(ge=0, strict=True)


class Configure(Revision):
    api_key: SecretStr | None = None
    defaults: Defaults | None = None

    @model_validator(mode="after")
    def bounded_key(self):
        if self.api_key is not None:
            key = self.api_key.get_secret_value()
            if not 16 <= len(key) <= 512 or not key.isascii() or not key.isprintable():
                raise ValueError("invalid_key")
        if self.api_key is None and self.defaults is None:
            raise ValueError("empty_configuration")
        return self


class TTS(Input):
    text: str = Field(min_length=1, max_length=1500)
    voice_id: ProviderID
    model_id: ProviderID

    @field_validator("text")
    @classmethod
    def text_without_nul(cls, value):
        if "\x00" in value:
            raise ValueError("invalid_text")
        return value


class STT(Input):
    attachment_id: UUID


class AgentSession(Input):
    agent_id: ProviderID


class OutboundCall(AgentSession):
    phone_number_id: ProviderID
    contact_id: UUID
    expected_phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$", strict=True)


OPERATIONS = {"tts": TTS, "stt": STT, "agent_session": AgentSession, "outbound_call": OutboundCall}


class Execute(Input):
    operation: Literal["tts", "stt", "agent_session", "outbound_call"]
    arguments: dict

    @model_validator(mode="after")
    def typed_arguments(self):
        self.arguments = (
            OPERATIONS[self.operation].model_validate(self.arguments).model_dump(mode="json")
        )
        return self


class GatewayState(Revision):
    configured: bool = Field(strict=True)
    verified: bool = Field(strict=True)
    key_suffix: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{0,8}$")
    defaults: Defaults


class CatalogEntry(Input):
    id: ProviderID
    name: str = Field(min_length=1, max_length=120)


class Catalog(Revision):
    voices: list[CatalogEntry] = Field(max_length=50)
    models: list[CatalogEntry] = Field(max_length=50)
    agents: list[CatalogEntry] = Field(max_length=50)
    phone_numbers: list[CatalogEntry] = Field(max_length=50)
    limited: bool = Field(strict=True)
    errors: list[Literal["voices", "models", "agents", "phone_numbers"]] = Field(max_length=4)
