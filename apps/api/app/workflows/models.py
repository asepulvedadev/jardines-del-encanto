"""Bounded declarative DAGs. Definitions never contain executable code or URLs."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from ..crm.models import Input

Identifier = str


class Position(Input):
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)


class Template(Input):
    account_id: str = Field(min_length=1, max_length=160)
    template_name: str = Field(min_length=1, max_length=160)
    language: str = Field(min_length=2, max_length=20)
    parameters: list[str] = Field(default_factory=list, max_length=30)


class Message(Input):
    account_id: str = Field(min_length=1, max_length=160)
    platform: Literal["facebook", "instagram", "telegram", "tiktok", "whatsapp"]
    text: str = Field(min_length=1, max_length=2000)
    allow_provider_takeover: bool = Field(default=False, strict=True)


class Call(Input):
    agent_id: str = Field(min_length=1, max_length=160)
    from_number: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")


class Wait(Input):
    hours: float = Field(ge=0, le=720, allow_inf_nan=False)


class Condition(Input):
    field: Literal["stage", "source"]
    operator: Literal["equals"]
    value: str = Field(min_length=1, max_length=160)


class Note(Input):
    body: str = Field(min_length=1, max_length=2000)


class Task(Input):
    title: str = Field(min_length=1, max_length=160)
    due_days: int = Field(ge=0, le=365, strict=True)


class Empty(Input):
    pass


SETTINGS = {
    "whatsapp_template": Template,
    "social_message": Message,
    "retell_call": Call,
    "wait": Wait,
    "condition": Condition,
    "crm_note": Note,
    "crm_task": Task,
    "end": Empty,
}


def check_text(value):
    if isinstance(value, dict):
        for child in value.values():
            check_text(child)
    elif isinstance(value, list):
        for child in value:
            check_text(child)
    elif isinstance(value, str):
        clean = value.replace("{{nombre}}", "").replace("{{celular}}", "")
        if "{{" in clean or "}}" in clean:
            raise ValueError("unsupported_placeholder")


class Node(Input):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal[
        "whatsapp_template",
        "social_message",
        "retell_call",
        "wait",
        "condition",
        "crm_note",
        "crm_task",
        "end",
    ]
    label: str = Field(min_length=1, max_length=120)
    position: Position
    next_id: str | None = Field(default=None, max_length=80)
    on_true: str | None = Field(default=None, max_length=80)
    on_false: str | None = Field(default=None, max_length=80)
    settings: dict

    @model_validator(mode="after")
    def settings_and_edges(self):
        self.settings = SETTINGS[self.kind].model_validate(self.settings).model_dump()
        check_text(self.settings)
        if self.kind == "condition":
            if not self.on_true or not self.on_false or self.next_id:
                raise ValueError("condition_edges_required")
        elif self.on_true or self.on_false or (self.kind == "end" and self.next_id):
            raise ValueError("unexpected_edges")
        elif self.kind != "end" and not self.next_id:
            raise ValueError("next_required")
        return self


class Schedule(Input):
    timezone: Literal["America/Bogota"]
    days: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(min_length=1, max_length=7)
    start_time: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end_time: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    daily_limit: int = Field(default=20, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def valid(self):
        if (
            len(set(self.days)) != len(self.days)
            or any(type(d) is not int or not 1 <= d <= 7 for d in self.days)
            or self.start_time >= self.end_time
        ):
            raise ValueError("invalid_schedule")
        return self


class Document(Input):
    entry_id: str = Field(min_length=1, max_length=80)
    nodes: list[Node] = Field(min_length=1, max_length=20)
    schedule: Schedule
    stop_on_reply: bool = Field(strict=True)

    @model_validator(mode="after")
    def graph(self):
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes) or self.entry_id not in nodes:
            raise ValueError("invalid_entry")
        seen, visiting = set(), set()

        def walk(key):
            if key not in nodes or key in visiting:
                raise ValueError("invalid_graph")
            if key in seen:
                return
            visiting.add(key)
            node = nodes[key]
            for target in (node.next_id, node.on_true, node.on_false):
                if target:
                    walk(target)
            visiting.remove(key)
            seen.add(key)

        walk(self.entry_id)
        if seen != set(nodes):
            raise ValueError("unreachable_nodes")
        return self


class DefinitionCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    document: Document


class DefinitionUpdate(Input):
    version: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    document: Document | None = None

    @model_validator(mode="after")
    def no_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("null_change")
        return self


class Binding(Input):
    contact_id: UUID
    conversation_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=160)


class Prepare(Input):
    version: int = Field(ge=1, strict=True)
    contact_ids: list[UUID] = Field(min_length=1, max_length=50)
    bindings: list[Binding] = Field(default_factory=list, max_length=50)
    channel_bindings: list[Binding] = Field(default_factory=list, max_length=150)
    consent_confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def unique(self):
        ids = [b.contact_id for b in self.bindings]
        channel_keys = [(b.contact_id, b.account_id) for b in self.channel_bindings]
        legacy_keys = {(b.contact_id, b.account_id) for b in self.bindings}
        if (
            len(set(self.contact_ids)) != len(self.contact_ids)
            or len(set(ids)) != len(ids)
            or not set(ids) <= set(self.contact_ids)
            or len(set(channel_keys)) != len(channel_keys)
            or bool(set(channel_keys) & legacy_keys)
            or not {b.contact_id for b in self.channel_bindings} <= set(self.contact_ids)
        ):
            raise ValueError("duplicate_or_unbound_contact")
        return self


class Activate(Input):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent_confirmed: bool = Field(strict=True)


class Version(Input):
    version: int = Field(ge=1, strict=True)


class Options(Input):
    provider: Literal["zernio", "retell"]
    account_id: str | None = Field(default=None, min_length=1, max_length=160)


class Record(Input):
    id: UUID


class DefinitionActionUpdate(DefinitionUpdate):
    id: UUID
