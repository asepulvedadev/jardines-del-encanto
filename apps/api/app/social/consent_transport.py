"""Fixed contact-only unsubscribe operation. Never sends messages or enables opt-in."""

import json
import re

from .transport import https_connection


def contact_request(credentials, method, identifier, body=None):
    if method not in {"GET", "PATCH"} or not re.fullmatch(r"[a-f0-9]{24}", identifier):
        raise ValueError("opt_out_contact_invalid")
    if method == "PATCH" and body != {"isSubscribed": False}:
        raise ValueError("opt_out_operation_invalid")
    connection = https_connection("zernio.com", timeout=8)
    try:
        headers = {
            "Authorization": "Bearer " + credentials["api_key"],
            "Accept": "application/json",
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        connection.request(method, "/api/v1/contacts/" + identifier, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if (
            not 200 <= response.status < 300
            or len(raw) > 2 * 1024 * 1024
            or "application/json" not in response.getheader("Content-Type", "")
        ):
            raise RuntimeError("opt_out_provider_unavailable")
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError("opt_out_provider_unconfirmed")
        return result
    finally:
        connection.close()


def unsubscribe(credentials, row):
    from ..inbox import service
    from .onboarding_transport import read

    if (
        row["platform"] != "whatsapp"
        or service.account(credentials, row["account_id"])["platform"] != "whatsapp"
    ):
        raise ValueError("opt_out_account_invalid")
    thread = read(credentials, row, "getInboxConversation").get("data")
    if not isinstance(thread, dict) or any(
        thread.get(remote) != row[local]
        for remote, local in (
            ("id", "conversation_id"),
            ("accountId", "account_id"),
            ("platform", "platform"),
            ("participantId", "participant_id"),
        )
    ):
        raise ValueError("opt_out_thread_invalid")
    identifier = thread.get("contactId")
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{24}", identifier):
        raise ValueError("opt_out_contact_missing")
    result = contact_request(credentials, "GET", identifier)
    contact, channels = result.get("contact"), result.get("channels")
    if (
        not isinstance(contact, dict)
        or contact.get("id") != identifier
        or not isinstance(channels, list)
        or not channels
    ):
        raise ValueError("opt_out_contact_unverified")
    # Subscription is contact-wide: never alter a shared contact belonging to a
    # different brand/account. Those cases require an explicit operator review.
    if any(not isinstance(c, dict) or c.get("accountId") != row["account_id"] for c in channels):
        raise ValueError("opt_out_contact_shared")
    if not any(
        c.get("platform") == "whatsapp"
        and str(c.get("platformIdentifier", "")).lstrip("+") == row["participant_id"].lstrip("+")
        for c in channels
    ):
        raise ValueError("opt_out_channel_unverified")
    if contact.get("isSubscribed") is False:
        return
    contact_request(credentials, "PATCH", identifier, {"isSubscribed": False})
    verified = contact_request(credentials, "GET", identifier).get("contact")
    if (
        not isinstance(verified, dict)
        or verified.get("id") != identifier
        or verified.get("isSubscribed") is not False
    ):
        raise RuntimeError("opt_out_provider_unconfirmed")
