"""Multichannel review inputs remain explicit, bounded and backwards compatible."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.workflows.models import Message, Prepare


def test_multichannel_bindings_are_unique_per_selected_contact_and_account():
    contact, other = uuid4(), uuid4()
    binding = {"contact_id": contact, "account_id": "facebook", "conversation_id": "thread-fb"}
    second = {**binding, "account_id": "instagram", "conversation_id": "thread-ig"}
    args = {"version": 1, "contact_ids": [contact], "consent_confirmed": True}
    parsed = Prepare(**args, channel_bindings=[binding, second])
    assert len(parsed.channel_bindings) == 2
    assert Prepare(**args, bindings=[binding]).channel_bindings == []
    for channels, legacy in (
        ([binding, binding], []),
        ([binding], [binding]),
        ([{**binding, "contact_id": other}], []),
    ):
        with pytest.raises(ValidationError):
            Prepare(**args, channel_bindings=channels, bindings=legacy)


def test_takeover_consent_is_false_by_default_and_strict():
    args = {"account_id": "fb", "platform": "facebook", "text": "Hola"}
    assert Message(**args).allow_provider_takeover is False
    assert Message(**args, allow_provider_takeover=True).allow_provider_takeover is True
    for value in ("true", 1, None):
        with pytest.raises(ValidationError):
            Message(**args, allow_provider_takeover=value)
