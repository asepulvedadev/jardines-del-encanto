"""Bounded reporting periods; vendor credentials are never action arguments."""

from typing import Literal

from pydantic import field_validator

from ..crm.models import Input


class SummaryInput(Input):
    days: Literal[1, 7, 30] = 7

    @field_validator("days", mode="before")
    @classmethod
    def strict_days(cls, value):
        if type(value) is not int:
            raise ValueError("invalid_period")
        return value
