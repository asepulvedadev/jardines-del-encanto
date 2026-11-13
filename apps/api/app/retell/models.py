"""Bounded Retell inputs. No credential-bearing arguments enter proposals."""

import json
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from ..crm.models import Input

Endpoint = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,79}$", strict=True)]
ProviderID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{0,128}$", strict=True)]
SENSITIVE = re.compile(
    r"(?:api_?key|secret|password|credential|authorization|auth_config|headers?|token|private_key|ice_servers)",
    re.IGNORECASE,
)


def sensitive(key):
    return bool(SENSITIVE.search(key))


def check_arguments(value, depth=0):
    if depth > 20:
        raise ValueError("arguments_too_deep")
    if isinstance(value, dict):
        if len(value) > 200:
            raise ValueError("arguments_too_large")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 120 or sensitive(key):
                raise ValueError("secret_argument_not_allowed")
            check_arguments(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 100:
            raise ValueError("arguments_too_large")
        for child in value:
            check_arguments(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > 16000 or "\x00" in value:
            raise ValueError("argument_invalid")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("argument_invalid")


class Defaults(Input):
    agent_id: ProviderID = ""
    chat_agent_id: ProviderID = ""
    from_number: str = Field(default="", pattern=r"^(?:\+[1-9][0-9]{7,14})?$", strict=True)


class Revision(Input):
    revision: int = Field(ge=0, strict=True)


INVENTORY_ENDPOINTS = (
    "listAgents",
    "listVoices",
    "listCalls",
    "listPhoneNumbers",
    "listKnowledgeBases",
    "listTestCaseDefinitions",
    "listRetellLLM",
    "listConversationFlows",
    "listChats",
    "listContacts",
    "listApps",
)
AUTOMATIC_READ_ENDPOINTS = frozenset(INVENTORY_ENDPOINTS) | frozenset(
    {
        "getAgent",
        "getVoice",
        "getCall",
        "getPhoneNumber",
        "getKnowledgeBase",
        "getTestCaseDefinition",
        "getRetellLLM",
        "getConversationFlow",
        "getChat",
        "getContact",
        "getApp",
        "listAgentVersions",
    }
)


def check_read_arguments(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                re.search(r"url|uri|consent", key, re.IGNORECASE)
                or sensitive(re.sub(r"\W", "_", key))
                or sensitive(re.sub(r"[^A-Za-z0-9]", "", key))
            ):
                raise ValueError("automatic_read_argument_denied")
            check_read_arguments(child)
    elif isinstance(value, list):
        for child in value:
            check_read_arguments(child)
    elif isinstance(value, str) and (
        value.lstrip().startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value.lstrip())
    ):
        raise ValueError("automatic_read_url_denied")


class AutomaticRead(Revision):
    endpoint: Endpoint
    arguments: dict

    @model_validator(mode="after")
    def bounded_read(self):
        if self.endpoint not in AUTOMATIC_READ_ENDPOINTS:
            raise ValueError("automatic_read_operation_denied")
        check_arguments(self.arguments)
        check_read_arguments(self.arguments)
        if len(json.dumps(self.arguments, allow_nan=False).encode()) > 12000:
            raise ValueError("arguments_too_large")
        return self


class EditorRead(Revision):
    kind: Literal["agent", "instructions"]
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    version: int | None = Field(default=None, ge=0, le=2**53 - 1, strict=True)

    @model_validator(mode="after")
    def explicit_version(self):
        if "version" in self.model_fields_set and self.version is None:
            raise ValueError("invalid_version")
        return self


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


class Schema(Revision):
    endpoint: Endpoint


class SchemaBrowse(Input):
    endpoint: Endpoint
    path: str = Field(default="", max_length=500, pattern=r"^(?:/[A-Za-z0-9_~./-]*)?$")
    offset: int = Field(default=0, ge=0, le=10000, strict=True)


class Contact(Input):
    contact_id: UUID
    expected_phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$", strict=True)


class Execute(Input):
    endpoint: Endpoint
    arguments: dict
    contacts: list[Contact] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def bounded_arguments(self):
        check_arguments(self.arguments)
        if len(json.dumps(self.arguments, allow_nan=False).encode()) > 32768:
            raise ValueError("arguments_too_large")
        ids = [contact.contact_id for contact in self.contacts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_contacts")
        return self


class GatewayState(Revision):
    configured: bool = Field(strict=True)
    verified: bool = Field(strict=True)
    key_suffix: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{0,8}$")
    defaults: Defaults


class Operation(Input):
    endpoint: Endpoint
    method: Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
    path: str = Field(max_length=200)
    summary: str = Field(max_length=300)
    group: str = Field(max_length=80)
    risk: Literal["read", "write", "paid", "destructive", "security"]
    available: bool = Field(strict=True)
    blocked_reason: str | None = Field(default=None, max_length=100)


class Catalog(Revision):
    registry_revision: str = Field(min_length=1, max_length=120)
    operations: list[Operation] = Field(max_length=150)
    new_operations: list[dict] = Field(default_factory=list, max_length=150)
