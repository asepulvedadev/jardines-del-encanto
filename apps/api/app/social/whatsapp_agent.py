"""Dedicated public Sara subagent: verified inbound identity, reviewed learning, no admin tools."""

import copy
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..control import service as control
from ..control.service import require_connections
from ..crm import security
from ..crm.database import connect
from ..hermes import bridge
from ..sara import profile as shared_profile
from ..sara.profile_models import ProfileUpdate
from . import config, workflow

router = APIRouter(prefix="/crm/social/whatsapp-agent")
Admin = Annotated[dict, Depends(security.session)]
DAILY_REPLY_LIMIT = 1000
DEVELOPER_DAILY_REPLY_LIMIT = 500
_stop = threading.Event()
_thread = None
_heartbeat = 0.0


def now():
    return datetime.now(UTC)


class Developer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    developers: list[Developer] = Field(max_length=2)
    instructions: str = Field(max_length=2000)
    knowledge: str = Field(max_length=4000)

    @field_validator("instructions", "knowledge")
    @classmethod
    def inert_text(cls, value):
        if any(ord(c) < 32 and c not in "\r\n\t" for c in value):
            raise ValueError("Invalid text")
        return value

    @model_validator(mode="after")
    def distinct_developers(self):
        phones = [d.phone for d in self.developers]
        if len(set(phones)) != len(phones) or self.phone in phones:
            raise ValueError("Developer numbers must be distinct from the business number")
        return self


class Update(Document):
    version: int = Field(ge=0)
    enabled: bool
    consent_confirmed: bool = False
    shared_profile_version: int | None = Field(default=None, ge=1)


class Resolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


def worker_enabled():
    return os.getenv("CRM_WHATSAPP_AGENT_WORKER_ENABLED") == "1"


def lock(db):
    db.execute("SELECT pg_advisory_xact_lock(9142040)")


def current(db):
    return db.execute("SELECT * FROM crm.whatsapp_agent WHERE singleton").fetchone()


def developer(document, participant):
    if not isinstance(participant, str) or not re.fullmatch(r"[1-9][0-9]{7,14}", participant):
        return None
    return next(
        (d["name"] for d in document["developers"] if d["phone"] == "+" + participant), None
    )


def learning_command(text, author):
    if author and isinstance(text, str) and text.startswith("/aprender "):
        value = text[len("/aprender ") :].strip()
        if 1 <= len(value) <= 1000:
            return value
    return None


def readiness(db, document, verify=False):
    try:
        c = config.required()
        if not c.get("webhook_registered"):
            return {"ready": False, "reason": "webhook_not_registered"}
        require_connections(db, "hermes", "zernio", "whatsapp")
        if (
            not worker_enabled()
            or not _thread
            or not _thread.is_alive()
            or monotonic() - _heartbeat > 70
        ):
            return {"ready": False, "reason": "worker_disabled"}
        state = bridge.request("/health", timeout=2)
        if state.get("available") is not True or state.get("public_reply_available") is not True:
            return {"ready": False, "reason": "hermes_unavailable"}
        if verify:
            account = workflow._account(c, document["account_id"])
            phone = account.get("metadata", {}).get("displayPhoneNumber")
            if not isinstance(phone, str) or not re.fullmatch(r"[+0-9 ()-]{8,32}", phone):
                raise HTTPException(409, "account_unverified")
            if re.sub(r"[^0-9]", "", phone) != document["phone"].lstrip("+"):
                raise HTTPException(409, "account_unverified")
            if account["platform"] != "whatsapp":
                raise HTTPException(409, "account_unverified")
        return {"ready": True, "reason": None}
    except (HTTPException, AttributeError) as error:
        reason = getattr(error, "detail", "account_unverified")
        allowed = {"zernio_not_configured", "hermes_unavailable", "connection_disabled"}
        return {"ready": False, "reason": reason if reason in allowed else "account_unverified"}


def view(db):
    row = current(db)
    data = (
        row["document"]
        if row
        else {
            "account_id": "",
            "phone": "",
            "developers": [],
            "instructions": "",
            "knowledge": "",
        }
    )
    published = shared_profile.get(db)
    return {
        **data,
        "instructions": published["instructions"],
        "knowledge": published["knowledge"],
        "shared_profile_version": published["version"],
        "version": row["version"] if row else 0,
        "enabled": row["enabled"] if row else False,
        "status": readiness(db, data, verify=True)
        if row
        else {"ready": False, "reason": "agent_not_configured"},
        "lessons": db.execute(
            "SELECT id,content,author,state,created_at FROM crm.whatsapp_agent_lessons ORDER BY created_at DESC LIMIT 30"
        ).fetchall(),
        "activity": db.execute(
            "SELECT state,created_at,error FROM crm.whatsapp_agent_jobs ORDER BY created_at DESC LIMIT 20"
        ).fetchall(),
    }


def save(db, data, author, owner_id=None):
    lock(db)
    control.lock(db)
    old = current(db)
    if data.version != (old["version"] if old else 0):
        raise HTTPException(409, "record_changed")
    document = data.model_dump(
        exclude={"version", "enabled", "consent_confirmed", "shared_profile_version"}
    )
    published = shared_profile.get(db)
    changed = any(document[key] != published[key] for key in ("instructions", "knowledge"))
    if (
        data.shared_profile_version is not None
        and data.shared_profile_version != published["version"]
    ):
        raise HTTPException(409, "record_changed")
    if changed:
        initial = old is None and owner_id is not None and published["version"] == 1
        if data.shared_profile_version is None and not initial:
            raise HTTPException(409, "shared_configuration_version_required")
        if owner_id is None:
            raise HTTPException(409, "developer_owner_required")
        shared_profile.update(
            db,
            ProfileUpdate(
                version=published["version"],
                instructions=document["instructions"],
                knowledge=document["knowledge"],
            ),
            {"id": owner_id, "username": author},
        )
    revision = None
    if data.enabled:
        if not data.consent_confirmed:
            raise HTTPException(409, "consent_required")
        status = readiness(db, document, verify=True)
        if not status["ready"]:
            raise HTTPException(409, status["reason"])
        revision = workflow._digest(config.required())
    version = data.version + 1
    # Every changed policy revokes queued work; only new incoming events can enroll.
    db.execute(
        "UPDATE crm.whatsapp_agent_jobs SET state='blocked',error='agent_changed',finished_at=now() WHERE state IN ('pending','generating')"
    )
    db.execute(
        """INSERT INTO crm.whatsapp_agent(singleton,version,enabled,enabled_at,document,credential_revision,owner_id)
        VALUES(true,%s,%s,%s,%s,%s,%s) ON CONFLICT(singleton) DO UPDATE SET
        version=excluded.version,enabled=excluded.enabled,enabled_at=excluded.enabled_at,
        document=excluded.document,credential_revision=excluded.credential_revision,
        owner_id=coalesce(excluded.owner_id,crm.whatsapp_agent.owner_id),updated_at=now()""",
        (
            version,
            data.enabled,
            now() if data.enabled else None,
            Jsonb(document),
            revision,
            owner_id,
        ),
    )
    db.execute(
        "INSERT INTO crm.whatsapp_agent_revisions(version,document,author) VALUES(%s,%s,%s)",
        (version, Jsonb(document), author),
    )
    return view(db)


@router.get("")
def get_settings(admin: Admin):
    with connect() as db:
        return view(db)


@router.patch("")
def update_settings(data: Update, admin: Admin):
    with connect() as db:
        return save(db, data, admin["username"], admin["id"])


@router.post("/lessons/{lesson_id}/{decision}")
def resolve_lesson(lesson_id: UUID, decision: str, data: Resolve, admin: Admin):
    if decision not in {"approve", "reject"}:
        raise HTTPException(404, "not_found")
    with connect() as db:
        lock(db)
        row = current(db)
        if not row or row["version"] != data.version:
            raise HTTPException(409, "record_changed")
        lesson = db.execute(
            "SELECT * FROM crm.whatsapp_agent_lessons WHERE id=%s FOR UPDATE", (lesson_id,)
        ).fetchone()
        if not lesson or lesson["state"] != "pending":
            raise HTTPException(409, "record_changed")
        if decision == "approve":
            document = copy.deepcopy(row["document"])
            published = shared_profile.get(db)
            document["instructions"] = published["instructions"]
            document["knowledge"] = (published["knowledge"] + "\n" + lesson["content"]).strip()
            if len(document["knowledge"]) > 4000:
                raise HTTPException(409, "knowledge_limit")
            # Publishing knowledge pauses the agent; renewed explicit activation follows review.
            save(
                db,
                Update(
                    **document,
                    version=row["version"],
                    enabled=False,
                    shared_profile_version=published["version"],
                ),
                admin["username"],
                admin["id"],
            )
        db.execute(
            "UPDATE crm.whatsapp_agent_lessons SET state=%s,resolved_at=now() WHERE id=%s",
            ("approved" if decision == "approve" else "rejected", lesson_id),
        )
        return view(db)


def normalize(payload, profile):
    """Caller has already authenticated raw HMAC and first-seen provider event."""
    if not isinstance(payload, dict) or not isinstance(payload.get("account"), dict):
        return None
    account = payload["account"]
    profiles = payload.get("profiles", [])
    if not isinstance(profiles, list):
        return None
    if account.get("profileId") not in (None, profile):
        return None
    if account.get("profileId") != profile and not any(
        isinstance(p, dict) and p.get("id") == profile for p in profiles
    ):
        return None
    cloned = {**payload, "account": {**account, "profileId": profile}}
    event = workflow.normalize_event(cloned)
    if not event or event["platform"] != "whatsapp":
        return None
    message = payload["message"]
    phone = message.get("sender", {}).get("phoneNumber")
    if phone is not None and phone.lstrip("+") != event["participant_id"]:
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return None
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        return None
    if not re.fullmatch(r"[1-9][0-9]{7,14}", event["participant_id"]):
        return None
    try:
        # REST list/reply routes use Zernio's signed opaque conversation ID,
        # not the platform alias (the platform message ID remains canonical).
        conversation_id = workflow._identifier(payload["conversation"].get("id"))
    except HTTPException:
        return None
    return {**event, "conversation_id": conversation_id, "text": text}


def enqueue(db, payload, profile):
    event = normalize(payload, profile)
    if not event:
        return
    from . import consent

    if consent.suppressed(db, event):
        return
    lock(db)
    row = current(db)
    if not row or not row["enabled"]:
        return
    doc = row["document"]
    control.lock(db)
    published = shared_profile.get(db)
    sent_at = workflow._time(event["sent_at"])
    if (
        event["account_id"] != doc["account_id"]
        or event["participant_id"] == doc["phone"].lstrip("+")
        or sent_at < row["enabled_at"]
        or not now() - timedelta(minutes=15) < sent_at <= now()
    ):
        return
    db.execute(
        """INSERT INTO crm.whatsapp_agent_jobs(event_id,account_id,profile_id,conversation_id,
        participant_id,message_id,agent_version,sent_at,content,shared_profile_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING""",
        (
            event["event_id"],
            event["account_id"],
            profile,
            event["conversation_id"],
            event["participant_id"],
            event["message_id"],
            row["version"],
            sent_at,
            event["text"],
            published["version"],
        ),
    )


def finish(job_id, state, error=None, reply=None, receipt=None):
    with connect() as db:
        db.execute(
            """UPDATE crm.whatsapp_agent_jobs SET state=%s,error=%s,reply=coalesce(%s,reply),
            receipt=%s,finished_at=now() WHERE id=%s AND state IN ('generating','reserved')""",
            (state, error, reply, Jsonb(receipt or {}), job_id),
        )


def claim():
    with connect() as db:
        lock(db)
        db.execute("""UPDATE crm.whatsapp_agent_jobs SET state='unknown',error='interrupted',finished_at=now()
            WHERE state IN ('generating','reserved') AND claimed_at<now()-interval '3 minutes'""")
        row = current(db)
        if not row or not row["enabled"]:
            return None
        # Global serialization limits both spend and conversational ordering across API processes.
        if db.execute(
            "SELECT 1 FROM crm.whatsapp_agent_jobs WHERE state IN ('generating','reserved') LIMIT 1"
        ).fetchone():
            return None
        budget = db.execute("""SELECT count(*) FILTER(WHERE claimed_at>now()-interval '1 minute') AS minute,
            count(*) FILTER(WHERE claimed_at>now()-interval '24 hours') AS day
            FROM crm.whatsapp_agent_jobs WHERE claimed_at>now()-interval '24 hours'""").fetchone()
        if budget["minute"] >= 6 or budget["day"] >= DAILY_REPLY_LIMIT:
            return None
        job = db.execute(
            "SELECT * FROM crm.whatsapp_agent_jobs WHERE state='pending' ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not job:
            return None
        from . import consent

        if consent.suppressed(db, {**job, "platform": "whatsapp"}):
            db.execute(
                "UPDATE crm.whatsapp_agent_jobs SET state='blocked',error='recipient_opted_out',finished_at=now() WHERE id=%s",
                (job["id"],),
            )
            return None
        if (
            job["agent_version"] != row["version"]
            or job["sent_at"] < now() - timedelta(minutes=15)
            or job["shared_profile_version"] != shared_profile.get(db)["version"]
        ):
            db.execute(
                "UPDATE crm.whatsapp_agent_jobs SET state='blocked',error='agent_changed_or_expired',finished_at=now() WHERE id=%s",
                (job["id"],),
            )
            return None
        if developer(row["document"], job["participant_id"]) is not None:
            count = db.execute(
                """SELECT count(*) AS n FROM crm.whatsapp_agent_jobs
                WHERE account_id=%s AND profile_id=%s AND participant_id=%s
                AND claimed_at>now()-interval '24 hours'""",
                (job["account_id"], job["profile_id"], job["participant_id"]),
            ).fetchone()["n"]
            limit, reason = DEVELOPER_DAILY_REPLY_LIMIT, "developer_budget"
        else:
            count = db.execute(
                "SELECT count(*) AS n FROM crm.whatsapp_agent_jobs WHERE account_id=%s AND conversation_id=%s AND claimed_at>now()-interval '24 hours'",
                (job["account_id"], job["conversation_id"]),
            ).fetchone()["n"]
            limit, reason = 30, "conversation_budget"
        if count >= limit:
            db.execute(
                "UPDATE crm.whatsapp_agent_jobs SET state='blocked',error=%s,finished_at=now() WHERE id=%s",
                (reason, job["id"]),
            )
            return None
        db.execute(
            "UPDATE crm.whatsapp_agent_jobs SET state='generating',claimed_at=now() WHERE id=%s",
            (job["id"],),
        )
        return job, row


def source_verified(job, credentials):
    from . import onboarding

    data = workflow._request(
        credentials,
        "messages",
        account_id=job["account_id"],
        conversation_id=job["conversation_id"],
    )
    matched = False
    for message in workflow._list(data, "messages"):
        # Inbox REST uses `message`; webhook deliveries use `text`. Retain the
        # legacy REST spelling only when it cannot contradict canonical content.
        content = message.get("message", message.get("text"))
        if not isinstance(content, str) or ("text" in message and message["text"] != content):
            continue
        if (
            message.get("conversationId") == job["conversation_id"]
            and message.get("accountId") == job["account_id"]
            and message.get("platform") == "whatsapp"
            and message.get("direction") == "incoming"
            and message.get("senderId") == job["participant_id"]
            and message.get("isDeleted") is not True
            and onboarding.opted_out(content)
        ):
            from . import consent

            with connect() as db:
                consent.remember(
                    db,
                    {
                        **job,
                        "platform": "whatsapp",
                        "event_id": "history:" + str(message.get("id")),
                    },
                )
            return False
        if (
            message.get("id") == job["message_id"]
            and message.get("conversationId") == job["conversation_id"]
            and message.get("accountId") == job["account_id"]
            and message.get("platform") == "whatsapp"
            and message.get("direction") == "incoming"
            and message.get("senderId") == job["participant_id"]
            and content == job["content"]
            and message.get("isDeleted") is not True
            and isinstance(message.get("metadata", {}), dict)
            and not message.get("metadata", {}).get("standby")
        ):
            matched = True
    return matched


def generate(job, row):
    document = row["document"]
    with connect() as db:
        published = shared_profile.get(db)
        if published["version"] != job["shared_profile_version"]:
            raise HTTPException(409, "shared_configuration_changed")
    author = developer(document, job["participant_id"])
    lesson = learning_command(job["content"], author)
    if lesson:
        with connect() as db:
            lock(db)
            fresh = current(db)
            if not fresh or not fresh["enabled"] or fresh["version"] != row["version"]:
                raise HTTPException(409, "agent_changed")
            db.execute(
                "INSERT INTO crm.whatsapp_agent_lessons(job_id,content,author) VALUES(%s,%s,%s) ON CONFLICT(job_id) DO NOTHING",
                (job["id"], lesson, author),
            )
        return f"{author}, guardé tu propuesta de conocimiento. Está pendiente de aprobación en la web; aún no cambia mis respuestas."
    if author and job["content"].strip() == "/estado":
        return f"Hola, {author}. Soy el subagente de Sara para WhatsApp. Versión {row['version']}. Usa /aprender seguido del dato para proponer conocimiento; se aprueba en la web."
    with connect() as db:
        history = db.execute(
            """SELECT content,reply FROM crm.whatsapp_agent_jobs WHERE account_id=%s
            AND conversation_id=%s AND participant_id=%s AND agent_version=%s AND state='completed'
            AND shared_profile_version=%s AND created_at>now()-interval '24 hours' ORDER BY created_at DESC LIMIT 3""",
            (
                job["account_id"],
                job["conversation_id"],
                job["participant_id"],
                row["version"],
                published["version"],
            ),
        ).fetchall()
    messages = []
    for previous in reversed(history):
        messages.append({"role": "user", "content": previous["content"]})
        if previous["reply"]:
            messages.append({"role": "assistant", "content": previous["reply"]})
    if author:
        from ..hermes import developer as trusted_developer

        return trusted_developer.generate(job, row, messages)
    from .whatsapp_audio import public_messages

    instructions = shared_profile.instructions(published)
    instructions += (
        "\nPuedes recibir respuestas a la campaña jardines_db36df695b5e19dabfbe7ca17b628228_v4. "
        "Conocer opciones expresa interés; No recibir información, SALIR o un rechazo explícito "
        "solicitan detener el contacto. La aplicación gestiona las bajas y el flujo inicial: "
        "audio de bienvenida, solicitud o confirmación de nombre completo y celular, registro "
        "sin duplicados y después página oficial y grupo del proyecto. No repitas la bienvenida "
        "ni afirmes que registraste datos, enviaste audio o diste de baja a alguien sin resultado "
        "confirmado de la aplicación. No inventes enlaces ni condiciones comerciales."
    )
    messages = public_messages(messages, job["content"], instructions, published["knowledge"])
    result = bridge.request(
        "/public-reply",
        {
            "messages": messages,
            "instructions": instructions,
            "knowledge": published["knowledge"],
        },
        timeout=48,
    )
    if result.get("ok") is not True or result.get("tools") != 0:
        raise HTTPException(503, "hermes_unavailable")
    return workflow._text(result.get("response"), 1500)


def tick():
    global _heartbeat
    # A live worker marks availability before claiming durable work after restart.
    if _thread and _thread.is_alive():
        _heartbeat = monotonic()
    claimed = claim()
    if not claimed:
        return
    job, row = claimed
    reserved = False
    try:
        with connect() as db:
            status = readiness(db, row["document"], verify=True)
        if not status["ready"]:
            raise HTTPException(409, status["reason"])
        c = config.required()
        if (
            workflow._digest(c) != row["credential_revision"]
            or c["profile_id"] != job["profile_id"]
        ):
            raise HTTPException(409, "connection_changed")
        if not source_verified(job, c):
            raise HTTPException(409, "source_unverified")
        reply = generate(job, row)
        from . import whatsapp_audio

        if whatsapp_audio.requested(job["content"]):
            whatsapp_audio.respond(job, row, reply)
            return
        with connect() as db:
            plan = workflow.prepare_literal_reply(db, job, reply)
        if plan["credential_revision"] != row["credential_revision"]:
            raise HTTPException(409, "connection_changed")
        # Serialize revocation with the actual send. A reservation is committed BEFORE I/O.
        with connect() as guard:
            guard.execute("SELECT pg_advisory_lock(9142040)")
            guard.execute("SELECT pg_advisory_lock(2026111105)")
            guard.commit()
            try:
                with connect() as db:
                    from . import consent

                    if consent.suppressed(db, {**job, "platform": "whatsapp"}):
                        raise HTTPException(409, "recipient_opted_out")
                    require_connections(db, "hermes", "zernio", "whatsapp")
                    fresh = current(db)
                    state = db.execute(
                        "SELECT state,shared_profile_version FROM crm.whatsapp_agent_jobs WHERE id=%s",
                        (job["id"],),
                    ).fetchone()
                    if (
                        not fresh
                        or not fresh["enabled"]
                        or fresh["version"] != row["version"]
                        or state["state"] != "generating"
                        or state["shared_profile_version"] != shared_profile.get(db)["version"]
                    ):
                        raise HTTPException(409, "agent_changed")
                    db.execute(
                        "UPDATE crm.whatsapp_agent_jobs SET state='reserved',reply=%s WHERE id=%s",
                        (reply, job["id"]),
                    )
                reserved = True
                result = workflow.dispatch(plan, "sara-whatsapp-" + str(job["id"]))
                finish(
                    job["id"],
                    "completed" if result["state"] == "completed" else "unknown",
                    result.get("error"),
                    reply,
                    result.get("receipt"),
                )
            finally:
                guard.execute("SELECT pg_advisory_unlock(2026111105)")
                guard.execute("SELECT pg_advisory_unlock(9142040)")
                guard.commit()
    except Exception:  # noqa: BLE001 - provider data never enters logs
        finish(job["id"], "unknown" if reserved else "blocked", "reply_not_confirmed")


def _loop():
    global _heartbeat
    while not _stop.is_set():
        try:
            from . import consent, onboarding

            onboarding.tick()
            tick()
            consent.sync()
            _heartbeat = monotonic()
        except Exception:  # noqa: BLE001 - recover without logging private data
            _heartbeat = 0.0
        _stop.wait(2)


def start():
    global _thread
    if worker_enabled() and (_thread is None or not _thread.is_alive()):
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="sara-whatsapp", daemon=True)
        _thread.start()


def stop():
    global _heartbeat
    _heartbeat = 0.0
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
