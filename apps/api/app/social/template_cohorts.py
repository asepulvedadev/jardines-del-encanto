"""GET-only attribution of replies to the owner's native Base 1 broadcast.

Audience membership alone is not a lead: require a successful per-recipient send
and a later incoming message in the exact brand/account/participant namespace.
"""

import re
from datetime import UTC, datetime

from ..broadcasts import provider
from ..crm.database import connect
from ..crm.models import ContactInput
from . import lead_capture as capture
from .lead_capture_worker import read
from .workflow import _digest

ACCOUNT = "6afa29ac3307a7365be18160"
NATIVE_NAME = "Jardines · Base 1 · Feria 22 nov 2026"
NATIVE_TAG = "jardines-base1-20261117"
TEMPLATE = "jardines_db36df695b5e19dabfbe7ca17b628228_v4"
LABEL = "Templates · Base 1"
LOCK = 9142073


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except ValueError:
        return None


def reply_at(row, messages, sent_at):
    valid = [
        at
        for message in capture.incoming(row, messages)
        if (at := timestamp(message.get("createdAt"))) is not None
        and sent_at < at <= datetime.now(UTC)
    ]
    return min(valid) if valid else None


def discover(credentials):
    # Existing fixed transport route; never uses POST/send/import endpoints.
    skip = 0
    for _ in range(20):
        path = "/v1/broadcasts" if skip == 0 else f"/v1/broadcasts?limit=100&skip={skip}"
        listing = provider.request(credentials, "GET", path)
        rows = listing.get("broadcasts")
        if not isinstance(rows, list) or len(rows) > 100:
            raise TypeError("cohort_campaigns_invalid")
        matches = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("cohort_campaigns_invalid")
            if row.get("name") != NATIVE_NAME or row.get("accountId") != ACCOUNT:
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{24}", identifier):
                raise ValueError("cohort_campaign_invalid")
            full = provider.request(credentials, "GET", f"/v1/broadcasts/{identifier}").get(
                "broadcast"
            )
            if not isinstance(full, dict):
                raise TypeError("cohort_campaign_invalid")
            if (
                full.get("id") != identifier
                or full.get("accountId") != ACCOUNT
                or full.get("name") != NATIVE_NAME
                or full.get("platform") != "whatsapp"
                or full.get("status") not in {"completed", "cancelled"}
                or not isinstance(full.get("template"), dict)
                or full["template"].get("name") != TEMPLATE
                or full["template"].get("language") != "es"
                or NATIVE_TAG not in (full.get("segmentFilters") or {}).get("tags", [])
                or timestamp(full.get("startedAt")) is None
                or type(full.get("recipientCount")) is not int
                or not 0 <= full["recipientCount"] <= 10000
            ):
                raise ValueError("cohort_campaign_unverified")
            matches.append(full)
        if matches:
            return matches
        pagination = listing.get("pagination")
        if not isinstance(pagination, dict) or type(pagination.get("hasMore")) is not bool:
            raise ValueError("cohort_campaigns_incomplete")
        if pagination["hasMore"] is False:
            return []
        if not rows:
            raise ValueError("cohort_campaigns_incomplete")
        skip += len(rows)
    raise ValueError("cohort_campaigns_incomplete")


def unchanged(credentials):
    if _digest(capture.config.required()) != _digest(credentials):
        raise ValueError("cohort_credentials_changed")


def sync(db, credentials, native):
    key = (credentials["profile_id"], ACCOUNT, native["id"])
    db.execute(
        """INSERT INTO crm.native_template_campaigns
        (profile_id,account_id,broadcast_id,label,template_name,recipient_count)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        (*key, LABEL, TEMPLATE, native["recipientCount"]),
    )
    saved = db.execute(
        """SELECT * FROM crm.native_template_campaigns
        WHERE profile_id=%s AND account_id=%s AND broadcast_id=%s""",
        key,
    ).fetchone()
    db.commit()
    if saved["recipient_count"] != native["recipientCount"]:
        raise ValueError("cohort_audience_changed")
    if saved["complete"]:
        return
    # At most two pages per minute, persisted cursor. A native 913-person base
    # needs five passes; no 500-row CRM import limit and no outgoing operation.
    skip = saved["scan_skip"]
    for _ in range(2):
        response = provider.request(
            credentials, "GET", f"/v1/broadcasts/{native['id']}/recipients?limit=100&skip={skip}"
        )
        rows, meta = response.get("recipients"), response.get("pagination")
        if (
            not isinstance(rows, list)
            or len(rows) > 100
            or not isinstance(meta, dict)
            or meta.get("total") != native["recipientCount"]
            or type(meta.get("hasMore")) is not bool
            or (meta["hasMore"] and len(rows) != 100)
            or (not meta["hasMore"] and skip + len(rows) != meta["total"])
        ):
            raise ValueError("cohort_recipients_incomplete")
        accepted, seen = [], set()
        for row in rows:
            if not isinstance(row, dict) or row.get("status") not in {
                "sent",
                "delivered",
                "read",
                "failed",
                "pending",
            }:
                raise ValueError("cohort_recipient_invalid")
            phone = row.get("platformIdentifier")
            if not isinstance(phone, str) or not re.fullmatch(r"\+?[1-9][0-9]{7,14}", phone):
                raise ValueError("cohort_recipient_invalid")
            phone = ContactInput.normalize_phone("+" + phone.lstrip("+"))
            if phone in seen:
                raise ValueError("cohort_duplicate_recipient")
            seen.add(phone)
            sent = timestamp(row.get("sentAt"))
            if row["status"] in {"sent", "delivered", "read"}:
                if (
                    sent is None
                    or sent < timestamp(native["startedAt"])
                    or sent > datetime.now(UTC)
                ):
                    raise ValueError("cohort_send_unverified")
                accepted.append((phone, sent))
        unchanged(credentials)
        for phone, sent in accepted:
            db.execute(
                """INSERT INTO crm.native_template_recipients
                (profile_id,account_id,broadcast_id,phone,sent_at)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (*key, phone, sent),
            )
        skip += len(rows)
        db.execute(
            """UPDATE crm.native_template_campaigns SET scan_skip=%s,complete=%s
            WHERE profile_id=%s AND account_id=%s AND broadcast_id=%s""",
            (skip, not meta["hasMore"], *key),
        )
        db.commit()
        if not meta["hasMore"]:
            break


def seed(db, profile):
    db.execute(
        """INSERT INTO crm.template_lead_attribution
        (profile_id,account_id,broadcast_id,contact_id,conversation_id,participant_id,
         label,template_name,sent_at)
        SELECT n.profile_id,n.account_id,n.broadcast_id,c.id,t.conversation_id,t.participant_id,
               b.label,b.template_name,n.sent_at
        FROM crm.native_template_recipients n
        JOIN crm.native_template_campaigns b USING(profile_id,account_id,broadcast_id)
        JOIN crm.contacts c ON c.phone=n.phone
        JOIN (
            SELECT profile_id,account_id,conversation_id,participant_id,contact_id
                FROM crm.lead_capture_threads WHERE platform='whatsapp' AND contact_id IS NOT NULL
            UNION
            SELECT profile_id,account_id,conversation_id,participant_id,contact_id
                FROM crm.social_onboarding WHERE platform='whatsapp' AND contact_id IS NOT NULL
        ) t ON t.profile_id=n.profile_id AND t.account_id=n.account_id AND t.contact_id=c.id
        WHERE n.profile_id=%s AND n.account_id=%s
        ON CONFLICT DO NOTHING""",
        (profile, ACCOUNT),
    )
    db.commit()


def tick():
    if not capture.enabled():
        return
    credentials = capture.config.required()
    profile = credentials["profile_id"]
    with connect() as db:
        if not db.execute("SELECT pg_try_advisory_lock(%s) AS held", (LOCK,)).fetchone()["held"]:
            return
        capture.require_connections(db, "zernio", "whatsapp")
        account = capture.inbox_service.account(credentials, ACCOUNT)
        if account.get("platform") != "whatsapp" or account.get("active") is not True:
            raise ValueError("cohort_account_unavailable")
        db.commit()
        for native in discover(credentials):
            sync(db, credentials, native)
        seed(db, profile)
        pending = db.execute(
            """SELECT * FROM crm.template_lead_attribution WHERE profile_id=%s
            AND account_id=%s AND state='pending' AND next_attempt<=now()
            ORDER BY next_attempt,contact_id,conversation_id LIMIT 10""",
            (profile, ACCOUNT),
        ).fetchall()
        db.commit()
        for saved in pending:
            key = (
                profile,
                ACCOUNT,
                saved["broadcast_id"],
                saved["contact_id"],
                saved["conversation_id"],
            )
            try:
                thread = read(
                    credentials,
                    ACCOUNT,
                    "getInboxConversation",
                    path={"conversationId": saved["conversation_id"]},
                ).get("data")
                if (
                    not isinstance(thread, dict)
                    or any(
                        thread.get(remote) != saved[local]
                        for remote, local in (
                            ("id", "conversation_id"),
                            ("accountId", "account_id"),
                            ("participantId", "participant_id"),
                        )
                    )
                    or thread.get("platform") != "whatsapp"
                ):
                    raise ValueError("cohort_thread_changed")
                # Scope and phone identity are revalidated after contact edits.
                current = db.execute(
                    "SELECT phone FROM crm.contacts WHERE id=%s", (saved["contact_id"],)
                ).fetchone()
                if not current or current["phone"] != "+" + saved["participant_id"].lstrip("+"):
                    raise ValueError("cohort_phone_changed")
                db.commit()
                result = read(
                    credentials,
                    ACCOUNT,
                    "getInboxConversationMessages",
                    {"limit": 100, "sortOrder": "desc"},
                    {"conversationId": saved["conversation_id"]},
                )
                rows = result.get("messages")
                if (
                    not isinstance(rows, list)
                    or len(rows) > 100
                    or any(not isinstance(row, dict) for row in rows)
                ):
                    raise ValueError("cohort_history_invalid")
                reply = reply_at(thread, rows, saved["sent_at"])
                unchanged(credentials)
                capture.require_connections(db, "zernio", "whatsapp")
                db.execute(
                    """UPDATE crm.template_lead_attribution a SET state=%s,reply_at=%s,
                    last_error=NULL,next_attempt=now()+interval '5 minutes'
                    WHERE profile_id=%s AND account_id=%s AND broadcast_id=%s
                    AND contact_id=%s AND conversation_id=%s AND EXISTS
                    (SELECT 1 FROM crm.contacts c WHERE c.id=a.contact_id AND c.phone=%s)""",
                    ("matched" if reply else "pending", reply, *key, current["phone"]),
                )
                db.commit()
            except Exception:  # noqa: BLE001 - diagnostic code only, no credentials or PII
                db.rollback()
                db.execute(
                    """UPDATE crm.template_lead_attribution SET last_error='cohort_read_failed',
                    next_attempt=now()+interval '5 minutes' WHERE profile_id=%s AND account_id=%s
                    AND broadcast_id=%s AND contact_id=%s AND conversation_id=%s""",
                    key,
                )
                db.commit()
