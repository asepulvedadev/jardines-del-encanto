"""Temporary deterministic lead intake. No LLM, outbound action or guessed identity."""

import hashlib
import json
import os
import re
import unicodedata

from ..control.service import require_connections
from ..crm.models import ContactInput
from ..crm.services import activity
from ..inbox import provider as inbox_provider  # noqa: F401 - worker/test boundary
from ..inbox import service as inbox_service  # noqa: F401 - worker/test boundary
from . import config

# Owner-approved project accounts, not every account in the shared Zernio profile.
ACCOUNTS = {
    "6afa29ac3307a7365be18160": "whatsapp",
    "6af6692c45ef03d5f9965518": "facebook",
}
EXCLUDED_PHONES = {"+573044643461", "+573008348478"}


def enabled():
    # This release explicitly activates the owner's temporary production safety net.
    default = "1" if os.getenv("CRM_ORIGIN") == "https://jardinesdelencanto.site" else "0"
    return os.getenv("CRM_LEAD_CAPTURE_ENABLED", default) == "1"


def name(value):
    if not isinstance(value, str):
        return None
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 1 <= len(value) <= 120 or not any(c.isalpha() for c in value):
        return None
    if any(ord(c) < 32 for c in value):
        return None
    return value


def phone(value):
    if not isinstance(value, str):
        return None
    try:
        return ContactInput.normalize_phone(value.strip())
    except ValueError:
        return None


def scoped(row):
    return (
        isinstance(row, dict)
        and isinstance(row.get("accountId"), str)
        and ACCOUNTS.get(row["accountId"]) == row.get("platform")
        and all(
            isinstance(row.get(k), str) and 0 < len(row[k]) <= limit
            for k, limit in (("id", 512), ("participantId", 512))
        )
    )


def incoming(row, messages):
    result = []
    for message in messages:
        if not isinstance(message, dict) or message.get("direction") != "incoming":
            continue
        if any(message.get(k) != row.get(k) for k in ("accountId", "platform")):
            continue
        if message.get("conversationId") != row["id"] or message.get("isDeleted") is True:
            continue
        sender = message.get("senderId")
        if not isinstance(sender, str):
            continue
        participant = row["participantId"]
        if sender != participant and not (
            row["platform"] == "whatsapp"
            and re.fullmatch(r"\+?573\d{9}", participant)
            and sender.lstrip("+") == participant.lstrip("+")
        ):
            continue
        result.append(message)
    return result


def extract(row, messages, complete=True):
    rows = incoming(row, messages)
    result = {
        "name": None,
        "phone": None,
        "form_phone": False,
        "fallback_phone": None,
        "scope_match": row.get("platform") == "whatsapp",
        "foreign_project": False,
        "reason": "no_incoming",
    }
    scope_decided = row.get("platform") == "whatsapp"
    for message in rows:
        text = message.get("message")
        if not isinstance(text, str):
            continue
        # Only labeled, self-declared values; never mine arbitrary numbers from prose.
        text = unicodedata.normalize("NFKC", text[:32000])
        lower = text.casefold()
        # Newest incoming project evidence wins; an explicit other brand always
        # outranks a generic campaign date within the same message.
        if not scope_decided:
            if "jardines del encanto" in lower:
                result["scope_match"], scope_decided = True, True
            elif "casanova" in lower:
                result["foreign_project"], scope_decided = True, True
            elif "22 de noviembre" in lower and "full name:" in lower and "phone number:" in lower:
                result["scope_match"], scope_decided = True, True
        found_name = re.search(
            r"Full name:[ \t]*([^\n]+?)(?=[ \t]*(?:Phone number:|City:|¿)|\r?\n|$)",
            text,
            re.IGNORECASE,
        )
        found_phone = re.search(
            r"Phone number:[ \t]*([^\n]+?)(?=[ \t]*(?:Full name:|City:|¿)|\r?\n|$)",
            text,
            re.IGNORECASE,
        )
        if found_name and result["name"] is None:
            result["name"] = name(found_name[1])
        if found_phone and not result["form_phone"]:
            result["form_phone"] = True
            result["phone"] = phone(found_phone[1])
    if rows:
        # Numeric Messenger IDs and WhatsApp BSUIDs are NEVER telephone numbers.
        if row["platform"] == "whatsapp":
            explicit = next(
                (m.get("senderPhoneNumber") for m in rows if m.get("senderPhoneNumber")), None
            )
            result["fallback_phone"] = phone(explicit)
            if result["fallback_phone"] is None and re.fullmatch(
                r"\+?573\d{9}", row["participantId"]
            ):
                result["fallback_phone"] = phone(row["participantId"])
        if complete:
            result["name"] = result["name"] or name(row.get("participantName"))
            if not result["form_phone"]:
                result["phone"] = result["fallback_phone"]
    if rows:
        result["reason"] = (
            "missing_phone"
            if not result["phone"]
            else "missing_name"
            if not result["name"]
            else None
        )
    return result


def marker(row):
    return hashlib.sha256(
        json.dumps(
            {
                k: row.get(k)
                for k in ("id", "participantId", "participantName", "lastMessageAt", "lastMessage")
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()


def remember(db, profile, row):
    if not scoped(row):
        return None
    return db.execute(
        """INSERT INTO crm.lead_capture_threads
           (profile_id,account_id,conversation_id,platform,participant_id,participant_name,observed_marker)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT(profile_id,account_id,conversation_id) DO UPDATE SET
             participant_name=EXCLUDED.participant_name,
             scan_cursor=CASE WHEN lead_capture_threads.observed_marker<>EXCLUDED.observed_marker THEN NULL ELSE lead_capture_threads.scan_cursor END,
             candidate_name=CASE WHEN lead_capture_threads.observed_marker<>EXCLUDED.observed_marker THEN NULL ELSE lead_capture_threads.candidate_name END,
             candidate_phone=CASE WHEN lead_capture_threads.observed_marker<>EXCLUDED.observed_marker THEN NULL ELSE lead_capture_threads.candidate_phone END,
             form_phone=CASE WHEN lead_capture_threads.observed_marker<>EXCLUDED.observed_marker THEN false ELSE lead_capture_threads.form_phone END,
             next_attempt=CASE WHEN lead_capture_threads.observed_marker<>EXCLUDED.observed_marker THEN now() ELSE lead_capture_threads.next_attempt END,
             observed_marker=EXCLUDED.observed_marker,updated_at=now()
           WHERE lead_capture_threads.participant_id=EXCLUDED.participant_id
           RETURNING *""",
        (
            profile,
            row["accountId"],
            row["id"],
            row["platform"],
            row["participantId"],
            name(row.get("participantName")),
            marker(row),
        ),
    ).fetchone()


def ingest(db, profile, row, messages, complete=True, cursor=None, expected_marker=None):
    if not enabled() or not scoped(row) or profile != config.required()["profile_id"]:
        return None
    require_connections(db, "zernio", row["platform"])
    if expected_marker is None and not remember(db, profile, row):
        return None
    key = (profile, row["accountId"], row["id"])
    saved = db.execute(
        "SELECT * FROM crm.lead_capture_threads WHERE profile_id=%s AND account_id=%s AND conversation_id=%s FOR UPDATE",
        key,
    ).fetchone()
    if not saved or (expected_marker and saved["observed_marker"] != expected_marker):
        return None
    result = extract(row, messages, complete)
    if result["foreign_project"]:
        # Newest explicit other-project evidence is conclusive; older pages cannot
        # turn that fair inquiry into a Jardines lead using a generic date marker.
        complete, cursor = True, None
    result["scope_match"] = (result["scope_match"] or saved["scope_match"]) and not result[
        "foreign_project"
    ]
    # Preserve a self-declared field across opaque message-history pages.
    if saved["candidate_name"]:
        result["name"] = saved["candidate_name"]
    if saved["form_phone"]:
        result["phone"], result["form_phone"] = saved["candidate_phone"], True
    elif complete and not result["form_phone"]:
        result["phone"] = result["phone"] or saved["candidate_phone"]
    if complete and result["phone"] and not result["name"]:
        result["name"] = name(row.get("participantName"))
    status, contact_id = "pending", saved["contact_id"]
    reason = result["reason"]
    if row["platform"] == "facebook" and not result["scope_match"]:
        status, reason = (
            ("out_of_scope", "other_project")
            if result["foreign_project"] and complete
            else ("pending", "project_unconfirmed" if complete else "history_pending")
        )
    elif result["phone"] in EXCLUDED_PHONES:
        status, reason = "out_of_scope", "internal_contact"
    elif result["name"] and result["phone"]:
        actor = db.execute(
            "SELECT id FROM crm.users WHERE username=%s AND enabled",
            (os.getenv("CRM_LEAD_CAPTURE_ACTOR", "adminjardines"),),
        ).fetchone()
        if actor:
            person = db.execute(
                "INSERT INTO crm.contacts(name,phone,source) VALUES (%s,%s,%s) ON CONFLICT(phone) DO NOTHING RETURNING id",
                (
                    result["name"],
                    result["phone"],
                    "whatsapp" if row["platform"] == "whatsapp" else "social_campaign",
                ),
            ).fetchone()
            created = person is not None
            person = (
                person
                or db.execute(
                    "SELECT id FROM crm.contacts WHERE phone=%s", (result["phone"],)
                ).fetchone()
            )
            contact_id = person["id"]
            deal = db.execute(
                "INSERT INTO crm.deals(contact_id) VALUES (%s) ON CONFLICT(contact_id) DO NOTHING RETURNING id",
                (contact_id,),
            ).fetchone()
            if created and deal:
                activity(
                    db,
                    deal["id"],
                    actor["id"],
                    "created",
                    "Lead registrado automáticamente desde un mensaje entrante verificado. Negociación creada en Nuevo.",
                )
            status, reason = "registered", None
        else:
            reason = "capture_actor_unavailable"
    elif not complete:
        reason = "history_pending"
    db.execute(
        """UPDATE crm.lead_capture_threads SET candidate_name=%s,candidate_phone=%s,form_phone=%s,
           scope_match=%s,status=%s,reason=%s,contact_id=%s,scan_cursor=%s,
           checked_marker=CASE WHEN %s THEN observed_marker ELSE checked_marker END,
           attempts=attempts+1,next_attempt=now()+interval '60 seconds',updated_at=now()
           WHERE profile_id=%s AND account_id=%s AND conversation_id=%s""",
        (
            result["name"],
            result["phone"]
            or (
                (result["fallback_phone"] or saved["candidate_phone"])
                if not result["form_phone"]
                else None
            ),
            result["form_phone"],
            result["scope_match"],
            status,
            reason,
            contact_id,
            cursor,
            complete and reason != "capture_actor_unavailable",
            *key,
        ),
    )
    return {"status": status, "reason": reason}


def webhook(db, payload, profile):
    """Called only inside the signed webhook transaction; does not contact Zernio."""
    from .workflow import normalize_event

    event = normalize_event(payload)
    if not enabled() or not event or event["profile_id"] != profile:
        return
    row = {
        "id": event["conversation_id"],
        "accountId": event["account_id"],
        "platform": event["platform"],
        "participantId": event["participant_id"],
        "participantName": payload["message"]["sender"].get("name"),
        "lastMessageAt": event["sent_at"],
    }
    message = {
        "id": event["message_id"],
        "accountId": row["accountId"],
        "conversationId": row["id"],
        "platform": row["platform"],
        "senderId": row["participantId"],
        "direction": "incoming",
        "message": payload["message"].get("text"),
        "senderPhoneNumber": payload["message"]["sender"].get("phoneNumber"),
    }
    # A single webhook is not complete history. Missing identity is repaired by polling.
    ingest(db, profile, row, [message], complete=False)


def tick():
    from .lead_capture_worker import tick as run

    return run()
