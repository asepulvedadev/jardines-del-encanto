"""Bounded named variables and draft buttons, independent of provider approval."""

import ipaddress
import re
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ..crm.models import Input

TOKEN = re.compile(r"\{\{([a-z][a-z0-9_]{0,39})\}\}")
ASSETS = {f"campaign-{number:02}" for number in range(1, 16)}


def https_link(value: str) -> bool:
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or not host
            or "." not in host
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
            or any(char.isspace() or ord(char) < 32 for char in value)
            or any(char in value for char in "{}\\")
            or host.endswith((".local", ".localhost", ".internal"))
            or re.fullmatch(r"[\d.]+", host)
        ):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            return True
    except ValueError:
        return False


class Variable(Input):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    kind: Literal["text", "link"]
    example: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_example(self):
        if "{" in self.example or "}" in self.example:
            raise ValueError("nested_variables")
        if self.kind == "link" and not https_link(self.example):
            raise ValueError("invalid_link")
        return self


class Button(Input):
    kind: Literal["reply", "url"]
    label: str = Field(min_length=1, max_length=25)
    value: str = Field(min_length=1, max_length=1000)


class Document(Input):
    name: str = Field(min_length=1, max_length=100)
    audience: Literal["invitation", "information", "registered"]
    suggested_date: date | None = None
    body: str = Field(min_length=1, max_length=1024)
    image_id: str | None = None
    variables: list[Variable] = Field(default_factory=list, max_length=12)
    buttons: list[Button] = Field(default_factory=list, max_length=3)

    @field_validator("image_id")
    @classmethod
    def valid_asset(cls, value):
        if value is not None and value not in ASSETS:
            raise ValueError("unknown_image")
        return value

    @model_validator(mode="after")
    def validate_variables(self):
        variables = {variable.key: variable for variable in self.variables}
        if len(variables) != len(self.variables):
            raise ValueError("duplicate_variable")
        if len({button.label.casefold() for button in self.buttons}) != len(self.buttons):
            raise ValueError("duplicate_button")
        for text in [self.body, *[button.value for button in self.buttons]]:
            keys = TOKEN.findall(text)
            clean = TOKEN.sub("", text)
            if "{" in clean or "}" in clean or any(key not in variables for key in keys):
                raise ValueError("unresolved_variable")
        for button in self.buttons:
            if button.kind == "url":
                match = TOKEN.fullmatch(button.value)
                if match:
                    if variables[match[1]].kind != "link":
                        raise ValueError("link_variable_required")
                elif not https_link(button.value):
                    raise ValueError("invalid_link")
            elif len(button.value) > 80 or TOKEN.search(button.value):
                raise ValueError("invalid_reply_key")
        return self


class Create(Input):
    document: Document


class Update(Create):
    version: int = Field(ge=0, le=2147483646, strict=True)


class ReviewPreview(Input):
    version: int = Field(ge=1, le=2147483646, strict=True)
    account_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,160}$")


class ReviewSubmit(ReviewPreview):
    confirm: Literal[True]

    @field_validator("confirm", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("confirmation_required")
        return value
