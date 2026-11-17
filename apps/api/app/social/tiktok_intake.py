"""Explicitly activated TikTok conversation sequencing; Sara generates every reply."""

import re
from datetime import UTC, datetime, timedelta

from . import config, workflow

RECEIPTS = ("introduction_receipt", "confirmation_receipt", "website_receipt", "group_receipt")


def settings(db):
    return db.execute(
        "SELECT *,jsonb_build_object(account_id,'tiktok') AS accounts,false AS facebook_takeover "
        "FROM crm.tiktok_intake_config WHERE singleton"
    ).fetchone()


def configure(db, *, owner_id, profile_id, account_id, proof_event_id):
    """Private owner operation: require a recent signed DM and matching live Inbox proof."""
    from . import onboarding, onboarding_transport

    current = onboarding.settings(db)
    if (
        not current
        or not current["enabled"]
        or current["owner_id"] != owner_id
        or current["profile_id"] != profile_id
        or not db.execute(
            "SELECT 1 FROM crm.users WHERE id=%s AND enabled AND role='admin'", (owner_id,)
        ).fetchone()
    ):
        raise ValueError("tiktok_activation_not_authorized")
    receipt = db.execute(
        "SELECT body FROM crm.social_webhook_events WHERE event_id=%s AND event='message.received' AND profile_id=%s AND platform='tiktok'",
        (proof_event_id, profile_id),
    ).fetchone()
    event = onboarding.normalize(receipt["body"], profile_id) if receipt else None
    if (
        not event
        or event["account_id"] != account_id
        or event["platform"] != "tiktok"
        or not datetime.now(UTC) - timedelta(minutes=15)
        < workflow._time(event["sent_at"])
        <= datetime.now(UTC)
    ):
        raise ValueError("tiktok_recent_signed_dm_required")
    credentials = config.required()
    if (
        credentials["profile_id"] != profile_id
        or workflow._digest(credentials) != current["credential_revision"]
    ):
        raise ValueError("tiktok_activation_scope_changed")
    onboarding.control.require_connections(db, "hermes", "zernio", "tiktok")
    candidate = {
        **event,
        "id": None,
        "profile_id": profile_id,
        "source": event,
        "created_at": datetime.now(UTC),
        **{key: {} for key in RECEIPTS},
    }
    onboarding_transport._verified_source(db, candidate, current, credentials)
    onboarding.control.lock(db)
    if onboarding.settings(db) != current:
        raise ValueError("tiktok_activation_scope_changed")
    db.execute(
        """INSERT INTO crm.tiktok_intake_config(singleton,owner_id,profile_id,account_id,
        credential_revision,group_url,proof_event_id) VALUES(true,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(singleton) DO UPDATE SET owner_id=EXCLUDED.owner_id,profile_id=EXCLUDED.profile_id,
        account_id=EXCLUDED.account_id,credential_revision=EXCLUDED.credential_revision,
        group_url=EXCLUDED.group_url,proof_event_id=EXCLUDED.proof_event_id,enabled=true,
        version=crm.tiktok_intake_config.version+1,enabled_at=now()""",
        (
            owner_id,
            profile_id,
            account_id,
            current["credential_revision"],
            current["group_url"],
            proof_event_id,
        ),
    )


def phase(row, incoming):
    if not row["welcome_required"]:
        return "question" if incoming else None
    if row["introduction_receipt"].get("status") != "accepted":
        return "introduction"
    if not row["contact_id"]:
        return "question" if incoming else None
    for step in ("confirmation", "website", "group"):
        if row[step + "_receipt"].get("status") != "accepted":
            return step
    return "question" if incoming else None


def identity(row):
    """Natural self-identification; unlabelled candidate names require confirmation."""
    from . import onboarding

    text = row["source"]["text"].strip()
    explicit = onboarding.details(text, {}, {})
    self_name = re.fullmatch(r"(?:me llamo|mi nombre es)\s+(.+)", text, re.IGNORECASE)
    if self_name:
        name = onboarding.valid_name(self_name[1])
        if name:
            explicit["name"] = name
    value = {**row["details"], **explicit}
    confirmed = (
        set(explicit) == {"name", "phone"}
        or (row["asked"] and "name" in explicit)
        or (
            row["asked"]
            and onboarding.folded(text).strip(" .!")
            in {"si", "confirmo", "correcto", "si confirmo", "si son correctos"}
        )
    )
    # Bare full-name replies are candidates, not automatic CRM writes. Avoid
    # interpreting project questions/interest as identity; confirmation is required.
    if (
        row["asked"]
        and "name" not in value
        and not explicit
        and re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?: [A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4}", text)
    ):
        value["name"] = text
        confirmed = False
    return value, confirmed


def history(db, row, envelope):
    """Conservative rolling 48h budget, including other senders and uncertain reservations."""
    messages = envelope.get("messages")
    if not isinstance(messages, list) or len(messages) >= 50:
        raise ValueError("welcome_tiktok_history_incomplete")
    for part in (envelope, *(envelope.get(key, {}) for key in ("pagination", "meta", "metadata"))):
        if (
            not isinstance(part, dict)
            or part.get("success") is False
            or any(
                part.get(k)
                for k in (
                    "hasMore",
                    "nextCursor",
                    "next_cursor",
                    "partial",
                    "partialFailure",
                    "partial_failure",
                    "warning",
                    "warnings",
                    "accountsFailed",
                    "accountsSkipped",
                    "failedAccounts",
                )
            )
        ):
            raise ValueError("welcome_tiktok_history_incomplete")
        if isinstance(part.get("total"), int) and part["total"] > len(messages):
            raise ValueError("welcome_tiktok_history_incomplete")
    since = datetime.now(UTC) - timedelta(hours=48)
    reservations = db.execute(
        "SELECT * FROM crm.tiktok_reply_reservations WHERE profile_id=%s AND account_id=%s AND participant_id=%s AND reserved_at>%s",
        (row["profile_id"], row["account_id"], row["participant_id"], since),
    ).fetchall()
    known = {r["message_id"] for r in reservations if r["message_id"]}
    own = {row[key].get("message_id") for key in RECEIPTS if row[key].get("status") == "accepted"}
    own.update(
        r["message_id"] for r in reservations if r["onboarding_id"] == row["id"] and r["message_id"]
    )
    outgoing = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("direction") not in {
            "incoming",
            "outgoing",
        }:
            raise ValueError("welcome_tiktok_history_incomplete")
        if message["direction"] == "outgoing" and workflow._time(message.get("createdAt")) > since:
            identifier = workflow._identifier(message.get("id"))
            outgoing.add(identifier)
            if workflow._time(message["createdAt"]) >= row["created_at"] and identifier not in own:
                raise ValueError("welcome_tiktok_other_reply")
    reserved_phase = row.get("state", "").removesuffix("_reserved")
    current = sum(
        1
        for r in reservations
        if row.get("state", "").endswith("_reserved")
        and r["onboarding_id"] == row["id"]
        and r["phase"] == reserved_phase
        and r["source_message_id"] == row["source"]["message_id"]
        and not r["message_id"]
    )
    if (
        row.get("state", "").endswith("_reserved")
        and len(reservations) + len(outgoing - known) - current >= 10
    ):
        raise ValueError("welcome_tiktok_reply_budget")


def reserve(db, row, step):
    db.execute("SELECT pg_advisory_xact_lock(9142080)")
    count = db.execute(
        "SELECT count(*) AS n FROM crm.tiktok_reply_reservations WHERE profile_id=%s AND account_id=%s AND participant_id=%s AND reserved_at>now()-interval '48 hours'",
        (row["profile_id"], row["account_id"], row["participant_id"]),
    ).fetchone()["n"]
    if count >= 10:
        raise ValueError("welcome_tiktok_reply_budget")
    db.execute(
        "INSERT INTO crm.tiktok_reply_reservations(onboarding_id,profile_id,account_id,participant_id,phase,source_message_id) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            row["id"],
            row["profile_id"],
            row["account_id"],
            row["participant_id"],
            step,
            row["source"]["message_id"],
        ),
    )
