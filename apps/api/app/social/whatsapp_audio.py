"""One requested spoken answer; server-owned TTS, never customer model tools."""

import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException

from ..control import service as control
from ..crm.database import connect
from ..sara import profile
from ..voice import models
from ..voice import service as voice
from . import audio_media, config, workflow


def requested(text):
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    if value.startswith("/aprender ") or re.search(r"\bno\b.{0,45}\b(audio|voz)\b", value):
        return False
    return bool(
        value.startswith("/audio ")
        or re.search(
            r"\b(respondeme|responde|respondas|responder)\b[^.!?\n]{0,40}"
            r"\b(en|por|con)\s+(audio|voz|una nota de voz)\b",
            value,
        )
        or re.search(
            r"\b(enviame|enviarme|mandame|mandarme|manda|quiero)\s+"
            r"(?:por favor\s+)?(?:un|una)?\s*(audio|nota de voz)\b",
            value,
        )
    )


def public_messages(history, text, instructions, knowledge):
    """Keep the original message intact within the unchanged public bridge limits."""
    original = [*history, {"role": "user", "content": text}]
    if not requested(text) or len(original) >= 8:
        return original
    hint = {
        "role": "user",
        "content": "Requested output: natural spoken answer. "
        "The application synthesizes the answer separately; do not claim audio was sent.",
    }
    candidate = [*history, hint, original[-1]]
    body = {"messages": candidate, "instructions": instructions, "knowledge": knowledge}
    if len(json.dumps(body, ensure_ascii=False).encode()) > 24 * 1024:
        return original
    return candidate


def _source(db, job, row, expected_state):
    from . import consent
    from . import whatsapp_agent as agent

    if consent.suppressed(db, {**job, "platform": "whatsapp"}):
        raise HTTPException(409, "recipient_opted_out")

    control.require_connections(db, "hermes", "zernio", "whatsapp", "elevenlabs")
    control.require_capability(db, "voice.execute")
    fresh = agent.current(db)
    actual = db.execute(
        "SELECT * FROM crm.whatsapp_agent_jobs WHERE id=%s FOR UPDATE", (job["id"],)
    ).fetchone()
    owner = db.execute(
        "SELECT id FROM crm.users WHERE id=%s AND enabled AND role='admin'", (row["owner_id"],)
    ).fetchone()
    if (
        not fresh
        or not actual
        or not owner
        or not fresh["enabled"]
        or fresh["version"] != row["version"]
        or fresh["owner_id"] != row["owner_id"]
        or actual["state"] != expected_state
        or not requested(actual["content"])
        or actual["shared_profile_version"] != profile.get(db)["version"]
        or fresh["document"]["account_id"] != actual["account_id"]
        or any(
            actual[k] != job[k]
            for k in (
                "agent_version",
                "account_id",
                "profile_id",
                "conversation_id",
                "participant_id",
                "message_id",
                "content",
            )
        )
    ):
        raise HTTPException(409, "audio_source_changed")
    credentials = config.required()
    if (
        workflow._digest(credentials) != row["credential_revision"]
        or fresh["credential_revision"] != row["credential_revision"]
        or credentials["profile_id"] != actual["profile_id"]
        or not agent.source_verified(actual, credentials)
    ):
        raise HTTPException(409, "audio_source_changed")


def _provider(db):
    value = voice.require_state()
    pref = db.execute(
        "SELECT enabled,version FROM crm.control_connections WHERE key='elevenlabs'"
    ).fetchone()
    if not pref or not pref["enabled"]:
        raise HTTPException(409, "connection_disabled")
    cached = db.execute(
        "SELECT catalog FROM crm.voice_catalog WHERE id=true AND revision=%s", (value["revision"],)
    ).fetchone()
    defaults = value["defaults"]
    if not cached or any(
        defaults[field] not in {v["id"] for v in cached["catalog"][group]}
        for field, group in (("voice_id", "voices"), ("model_id", "models"))
    ):
        raise HTTPException(409, "voice_catalog_required")
    return {
        "revision": value["revision"],
        "connection_version": pref["version"],
        "voice_id": defaults["voice_id"],
        "model_id": defaults["model_id"],
    }


def respond(job, row, reply):
    """Reuse the inbound worker's once-only state; no second queue or fake proposal."""
    from . import whatsapp_agent as agent

    reserved = False
    with connect() as guard:
        guard.execute("SELECT pg_advisory_lock(9142040)")
        guard.execute("SELECT pg_advisory_lock(2026111105)")
        guard.commit()
        try:
            _source(guard, job, row, "generating")
            provider = _provider(guard)
            arguments = models.TTS(
                text=reply, voice_id=provider["voice_id"], model_id=provider["model_id"]
            ).model_dump()
            preparation = audio_media.prepare_reply(job)
            if preparation["credential_revision"] != row["credential_revision"]:
                raise HTTPException(409, "audio_source_changed")
            quota = guard.execute(
                """SELECT count(*) AS n,
                count(*) FILTER(WHERE created_at>now()-interval '24 hours') AS day,
                COALESCE(sum(octet_length(data)),0) AS bytes
                FROM crm.whatsapp_agent_audio WHERE owner_id=%s""",
                (row["owner_id"],),
            ).fetchone()
            if (
                quota["n"] >= 100
                or quota["day"] >= 20
                or quota["bytes"] + audio_media.MAX_AUDIO > 25 * 1024 * 1024
            ):
                raise HTTPException(409, "audio_budget_exceeded")
            # Durable reservation covers paid generation AND sending, including crashes.
            guard.execute(
                """INSERT INTO crm.whatsapp_agent_audio(job_id,owner_id,voice_id,
                model_id,provider_revision,connection_version,state)
                VALUES(%s,%s,%s,%s,%s,%s,'synthesizing')""",
                (
                    job["id"],
                    row["owner_id"],
                    provider["voice_id"],
                    provider["model_id"],
                    provider["revision"],
                    provider["connection_version"],
                ),
            )
            guard.execute(
                "UPDATE crm.whatsapp_agent_jobs SET state='reserved',reply=%s WHERE id=%s",
                (reply, job["id"]),
            )
            guard.commit()
            reserved = True
            result = voice.bridge.request(
                "/execute",
                {
                    "id": str(job["id"]),
                    "revision": provider["revision"],
                    "operation": "tts",
                    "arguments": arguments,
                },
                timeout=45,
            )
            data = voice.tts_audio(result)
            _source(guard, job, row, "reserved")
            if _provider(guard) != provider:
                raise HTTPException(409, "voice_provider_changed")
            guard.execute(
                """UPDATE crm.whatsapp_agent_audio SET data=%s,content_hash=%s
                WHERE job_id=%s AND state='synthesizing'""",
                (data, hashlib.sha256(data).hexdigest(), job["id"]),
            )
            guard.commit()
            plan = audio_media.prepare(job, data)
            if plan["reply"]["credential_revision"] != row["credential_revision"]:
                raise HTTPException(409, "audio_source_changed")
            _source(guard, job, row, "reserved")
            if _provider(guard) != provider:
                raise HTTPException(409, "voice_provider_changed")
            guard.execute(
                "UPDATE crm.whatsapp_agent_audio SET state='reserved' WHERE job_id=%s", (job["id"],)
            )
            guard.commit()
            delivery = audio_media.submit(plan, data, "sara-audio-" + str(job["id"]))
            guard.execute(
                "UPDATE crm.whatsapp_agent_audio SET state=%s WHERE job_id=%s",
                (delivery["state"], job["id"]),
            )
            guard.commit()
            agent.finish(
                job["id"], delivery["state"], delivery.get("error"), reply, delivery.get("receipt")
            )
        except Exception:  # noqa: BLE001 - Never leak provider data or retry an uncertain paid call.
            guard.rollback()
            if reserved:
                guard.execute(
                    "UPDATE crm.whatsapp_agent_audio SET state='unknown' WHERE job_id=%s",
                    (job["id"],),
                )
                guard.commit()
            agent.finish(job["id"], "unknown" if reserved else "blocked", "audio_not_confirmed")
        finally:
            guard.rollback()
            guard.execute("SELECT pg_advisory_unlock(2026111105)")
            guard.execute("SELECT pg_advisory_unlock(9142040)")
            guard.commit()
