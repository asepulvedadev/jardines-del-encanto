"""Durable, channel-scoped refusal. Public text never grants opt-in or tools."""

from contextlib import contextmanager

from fastapi import HTTPException
from psycopg.errors import LockNotAvailable

from ..crm.database import connect
from . import config, workflow


def key(row):
    return tuple(row[k] for k in ("profile_id", "account_id", "platform", "participant_id"))


def suppressed(db, row):
    current = bool(
        db.execute(
            "SELECT 1 FROM crm.social_opt_outs WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s)",
            key(row),
        ).fetchone()
    )
    return current or bool(
        db.execute(
            "SELECT 1 FROM crm.social_onboarding WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s) AND suppressed LIMIT 1",
            key(row),
        ).fetchone()
    )


def remember(db, event):
    # Intake must commit even while a vendor send holds enrollment/row locks.
    # The append-only refusal ledger is authoritative; never wait on a busy welcome row.
    credentials = config.required()
    if credentials["profile_id"] != event["profile_id"]:
        raise HTTPException(409, "opt_out_scope_changed")
    db.execute(
        """INSERT INTO crm.social_opt_outs(profile_id,account_id,platform,participant_id,
        conversation_id,event_id,credential_revision) VALUES(%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING""",
        (*key(event), event["conversation_id"], event["event_id"], workflow._digest(credentials)),
    )

    # Keep the legacy flag as a best-effort projection, never as a prerequisite.
    # A savepoint retains the refusal INSERT if a welcome currently owns the row.
    try:
        with db.transaction():
            rows = db.execute(
                "SELECT id FROM crm.social_onboarding WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s) FOR UPDATE NOWAIT",
                key(event),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE crm.social_onboarding SET suppressed=true WHERE id=%s", (row["id"],)
                )
    except LockNotAvailable:
        pass


@contextmanager
def sending(row):
    """Serialize submissions and recheck durable refusal immediately before dispatch."""
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(9142041)")
        if suppressed(db, row):
            raise HTTPException(409, "recipient_opted_out")
        yield


def sync():
    """Bounded, idempotent unsubscribe synchronization; local refusal wins immediately."""
    from ..control.service import require_connections
    from .consent_transport import unsubscribe

    with connect() as db, config.locked():
        row = db.execute(
            "SELECT * FROM crm.social_opt_outs WHERE remote_state='pending' AND next_attempt<=now() ORDER BY next_attempt FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not row:
            return
        target = "pending"
        try:
            require_connections(db, "zernio")
            credentials = config.required()
            if (
                credentials["profile_id"] != row["profile_id"]
                or workflow._digest(credentials) != row["credential_revision"]
            ):
                raise ValueError("opt_out_credentials_changed")
            unsubscribe(credentials, row)
            target = "synced"
        except ValueError:
            target = (
                "blocked"  # No guessed identities, cross-brand writes or credential substitution.
            )
        except Exception:  # noqa: BLE001 - retries are safe: the only write is isSubscribed=false.
            if row["attempts"] >= 4:
                target = "blocked"
        db.execute(
            "UPDATE crm.social_opt_outs SET remote_state=%s,attempts=attempts+1,next_attempt=now()+interval '5 minutes' WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s)",
            (target, *key(row)),
        )
