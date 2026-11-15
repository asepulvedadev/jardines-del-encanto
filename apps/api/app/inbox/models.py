"""Pinned, closed vendor schemas with mandatory server-owned profile/account scope."""

import ipaddress
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, field_validator

from ..crm.models import Input

REGISTRY = json.loads(Path(__file__).with_name("registry.json").read_text())
OPERATIONS = REGISTRY["operations"]


class AccountQuery(Input):
    account_id: str = Field(min_length=1, max_length=160)


class Execute(Input):
    operation: str = Field(max_length=80)
    account_id: str = Field(min_length=1, max_length=160)
    path: dict = Field(default_factory=dict)
    query: dict = Field(default_factory=dict)
    body: dict = Field(default_factory=dict)

    @field_validator("path", "query", "body")
    @classmethod
    def bounded(cls, value):
        if len(json.dumps(value, allow_nan=False).encode()) > 48000:
            raise ValueError("input_too_large")
        bounds(value)
        return value


class Confirmation(Input):
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True:
            raise ValueError("explicit_confirmation_required")
        return value


def bounds(value, depth=0):
    if depth > 16:
        raise ValueError("input_too_deep")
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError("input_too_large")
        for key, child in value.items():
            if (
                not isinstance(key, str)
                or len(key) > 100
                or re.search(
                    r"authorization|api.?key|password|secret|^headers$", key, re.IGNORECASE
                )
            ):
                raise ValueError("unsafe_input")
            bounds(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 100:
            raise ValueError("input_too_large")
        for child in value:
            bounds(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > 16000 or "\x00" in value:
            raise ValueError("invalid_input")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("invalid_input")


def safe_url(value):
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").rstrip(".")
        if parsed.scheme != "https" or parsed.username or parsed.password or not host:
            return None
        if (
            parsed.port not in (None, 443)
            or "." not in host
            or host.endswith((".local", ".internal", ".localhost"))
        ):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except (ValueError, TypeError):
        return None


def validate(command, credentials):
    operation = OPERATIONS.get(command.operation)
    if not operation:
        raise HTTPException(422, "inbox_operation_invalid")
    args = {key: dict(getattr(command, key)) for key in ("path", "query", "body")}
    for location, schema in operation["input"].items():
        props = schema.get("properties", {})
        for key, value in (
            ("accountId", command.account_id),
            ("profileId", credentials["profile_id"]),
        ):
            if key in args[location] and args[location][key] != value:
                raise HTTPException(422, "inbox_scope_mismatch")
            if key in props:
                args[location][key] = value
        if command.operation == "getMessageAttachment" and location == "query":
            args[location].setdefault("format", "json")
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(
            args[location]
        ):
            raise HTTPException(422, "inbox_input_invalid")
    for value in args["path"].values():
        if isinstance(value, str) and (
            not value
            or len(value) > 1024
            or value in {".", ".."}
            or any(ord(c) < 32 for c in value)
        ):
            raise HTTPException(422, "inbox_input_invalid")

    def links(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key.lower().endswith(("url", "uri", "link"))
                    and isinstance(child, str)
                    and key not in {"rootUri", "likeUri"}
                    and not safe_url(child)
                ):
                    raise HTTPException(422, "inbox_unsafe_url")
                links(child)
        elif isinstance(value, list):
            for child in value:
                links(child)

    links(args)
    return operation, args
