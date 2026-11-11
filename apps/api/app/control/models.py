"""Strict, bounded application extension definitions and action arguments."""

import json
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from ..crm.models import ContactEdit, Input, NoteInput, TaskEdit


class Empty(Input):
    pass


class RecordID(Input):
    deal_id: UUID


class ContactUpdate(ContactEdit):
    contact_id: UUID


class DealUpdate(Input):
    deal_id: UUID
    stage: Literal["new", "contacted", "won"]
    version: int = Field(ge=1, strict=True)


class NoteCreate(NoteInput):
    deal_id: UUID


class TaskUpdate(TaskEdit):
    task_id: UUID


class SocialConnect(Input):
    platform: Literal["facebook", "instagram", "tiktok", "whatsapp", "telegram"]


class SkillDefinition(Input):
    content: str = Field(min_length=1, max_length=16000)


class ToolDefinition(Input):
    action: str = Field(min_length=1, max_length=100)
    defaults: dict = Field(default_factory=dict)


class PluginDefinition(Input):
    actions: list[str] = Field(min_length=1, max_length=20)
    instructions: str = Field(default="", max_length=16000)


class Step(Input):
    action: str = Field(min_length=1, max_length=100)
    arguments: dict = Field(default_factory=dict)


class ScriptDefinition(Input):
    steps: list[Step] = Field(min_length=1, max_length=8)


class ConnectionDefinition(Input):
    adapter: Literal["application"]
    actions: list[str] = Field(min_length=1, max_length=20)


DEFINITIONS = {
    "skill": SkillDefinition,
    "tool": ToolDefinition,
    "plugin": PluginDefinition,
    "script": ScriptDefinition,
    "connection": ConnectionDefinition,
}


class ItemCreate(Input):
    kind: Literal["skill", "tool", "plugin", "script", "connection"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    definition: dict
    enabled: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_definition(self):
        if len(json.dumps(self.definition, ensure_ascii=False).encode()) > 65000:
            raise ValueError("definition_too_large")
        self.definition = DEFINITIONS[self.kind].model_validate(self.definition).model_dump()
        return self


class ItemUpdate(Input):
    version: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    definition: dict | None = None
    enabled: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def no_null_changes(self):
        if any(getattr(self, key) is None for key in self.model_fields_set if key != "version"):
            raise ValueError("null_change")
        return self


class ItemActionUpdate(ItemUpdate):
    id: UUID


class ConnectionUpdate(Input):
    version: int = Field(ge=1, strict=True)
    enabled: bool = Field(strict=True)


class ConnectionActionUpdate(ConnectionUpdate):
    key: Literal["hermes", "zernio", "facebook", "instagram", "tiktok", "whatsapp", "telegram"]


class Action(Input):
    action: str = Field(min_length=1, max_length=100)
    arguments: dict = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def bounded_arguments(cls, value):
        if len(json.dumps(value, ensure_ascii=False).encode()) > 24000:
            raise ValueError("arguments_too_large")
        return value


class Run(Input):
    arguments: dict = Field(default_factory=dict)


class Version(Input):
    version: int = Field(ge=1, strict=True)


class Chat(Input):
    message: str = Field(min_length=1, max_length=8000)


class BrokerCall(Action):
    call_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")


class Finish(Input):
    reply: str = Field(min_length=1, max_length=16000)


class Workspace(Input):
    query: str = Field(default="", max_length=120)
    limit: int = Field(default=50, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, le=500, strict=True)
