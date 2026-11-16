"""Owner-approved, deterministic social intake. Public models never receive CRM tools."""

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control import service as control
from ..crm.database import connect
from ..crm.models import ContactInput
from ..crm.services import capture_contact
from . import config, media, whatsapp_agent, whatsapp_audio, workflow

SCRIPT = (
    "Hola, soy Sara, asistente comercial del proyecto Jardines del Encanto, ubicado en "
    "Acacías, Meta. Es un gusto poder registrarte. A continuación te enviaré un enlace a "
    "nuestra página web y a nuestro grupo de WhatsApp para que puedas tener más información "
    "del proyecto y de la Gran Feria Inmobiliaria Jardines del Encanto, que se realizará el "
    "domingo veintidós de noviembre en la Cámara de Comercio de Bogotá en Soacha."
)
WEBSITE = "https://jardinesdelencanto.site/"
DAILY_WELCOME_LIMIT = 1000
WELCOME_UNTIL = datetime(2026, 11, 23, 5, tzinfo=UTC)  # End of fair date, Bogotá.
FIELDS = re.compile(
    r"(?P<label>full name|nombre completo|phone number|n[uú]mero de (?:tel[eé]fono|celular)|"
    r"celular|tel[eé]fono|city|ciudad|email|¿[^:\n]{1,120}\?)\s*:\s*",
    re.IGNORECASE,
)


def folded(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def opted_out(text):
    return bool(
        re.search(
            r"(?:^\s*(?:salir|stop|baja)\s*[.!]?\s*$|\bno (?:recibir mas|me contacten|"
            r"quiero (?:mas mensajes|informacion|que me contacten)|"
            r"deseo recibir (?:mas )?mensajes|me (?:escriban|escribas|vuelvas a escribir)|mas mensajes)\b)",
            folded(text),
        )
    )


def valid_name(value):
    value = " ".join(str(value or "").split())
    if not 3 <= len(value) <= 120 or not all(c.isalpha() or c in " .'-" for c in value):
        return None
    if len(value.split()) < 2 or folded(value) in {
        "quiero informacion",
        "buenos dias",
        "buenas tardes",
    }:
        return None
    return value


def phone(value):
    try:
        return ContactInput.normalize_phone(value)
    except (ValueError, TypeError):
        return None


def details(text, sender, previous):
    """Named ad fields take precedence; opaque IDs and unlabelled chat are not names."""
    found = {}
    matches = list(FIELDS.finditer(text))
    for index, match in enumerate(matches):
        label = folded(match["label"])
        key = (
            "name"
            if label in {"full name", "nombre completo"}
            else "phone"
            if label
            in {
                "phone number",
                "numero de telefono",
                "numero de celular",
                "celular",
                "telefono",
            }
            else None
        )
        if not key:
            continue
        raw = text[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
        ]
        raw = raw.strip(" \r\n,;|")
        value = valid_name(raw) if key == "name" else phone(raw)
        if not value or (key in found and found[key] != value):
            raise ValueError("ambiguous_contact_fields")
        found[key] = value
    result = {**previous, **found}
    if "name" not in result:
        name = valid_name(sender.get("name"))
        if name:
            result["name"] = name
    if "phone" not in result:
        number = phone(sender.get("phoneNumber"))
        if number:
            result["phone"] = number
        elif not matches and phone(text.strip()):
            result["phone"] = phone(text.strip())
    return result


def settings(db):
    return db.execute("SELECT * FROM crm.social_onboarding_config WHERE singleton").fetchone()


def configure(db, *, owner_id, profile_id, accounts, group_url, facebook_takeover=False):
    """Owner-operated configuration; no model-writable/public authorization surface."""
    if (
        not isinstance(accounts, dict)
        or not accounts
        or set(accounts.values()) - {"whatsapp", "facebook"}
        or any(workflow._identifier(k, 160) != k for k in accounts)
        or not re.fullmatch(
            r"https://chat\.whatsapp\.com/[A-Za-z0-9]+(?:\?[A-Za-z0-9=&]+)?", group_url
        )
        or ("facebook" in accounts.values() and facebook_takeover is not True)
        or not db.execute(
            "SELECT 1 FROM crm.users WHERE id=%s AND enabled AND role='admin'", (owner_id,)
        ).fetchone()
    ):
        raise ValueError("invalid_onboarding_configuration")
    workflow._identifier(profile_id, 160)
    credentials = config.required()
    if credentials["profile_id"] != profile_id:
        raise ValueError("onboarding_profile_mismatch")
    control.lock(db)
    db.execute(
        """INSERT INTO crm.social_onboarding_config(singleton,owner_id,profile_id,accounts,
        group_url,facebook_takeover,credential_revision,voice) VALUES(true,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(singleton) DO UPDATE SET owner_id=EXCLUDED.owner_id,
        profile_id=EXCLUDED.profile_id,accounts=EXCLUDED.accounts,group_url=EXCLUDED.group_url,
        facebook_takeover=EXCLUDED.facebook_takeover,credential_revision=EXCLUDED.credential_revision,
        version=crm.social_onboarding_config.version+1,
        enabled=true,enabled_at=now(),voice=EXCLUDED.voice""",
        (
            owner_id,
            profile_id,
            Jsonb(accounts),
            group_url,
            facebook_takeover,
            workflow._digest(credentials),
            Jsonb(whatsapp_audio._provider(db)),
        ),
    )


def normalize(payload, profile_id):
    account = payload.get("account") or {}
    conversation = payload.get("conversation")
    message = payload.get("message")
    if not all(isinstance(v, dict) for v in (account, conversation, message)):
        return None
    sender = message.get("sender")
    if not isinstance(sender, dict):
        return None
    sender = dict(sender)
    if sender.get("phoneNumber") is not None and not phone(sender["phoneNumber"]):
        sender.pop("phoneNumber")
    # This pipeline uses the signed REST ID exclusively. A Meta platform alias is
    # neither needed nor substituted for a customer's contact phone.
    event = workflow.normalize_event(
        {
            **payload,
            "account": {**account, "profileId": profile_id},
            "conversation": {**conversation, "platformConversationId": conversation.get("id")},
            "message": {**message, "sender": sender},
        }
    )
    if not event or event["platform"] not in {"whatsapp", "facebook"}:
        return None
    message = payload["message"]
    text = message.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        return None
    event.update(conversation_id=workflow._identifier(payload["conversation"]["id"]), text=text)
    return event


def enqueue(db, payload, profile_id):
    """Return True only when this public thread is owned by deterministic intake."""
    return _enqueue(db, payload, profile_id, earliest=datetime.now(UTC) - timedelta(minutes=15))


def recover_unanswered(db, event_id, *, actor_id):
    """Operator-only recovery of a signed, still-unanswered event; never sends inline."""
    from . import onboarding_transport

    with db.transaction():
        cfg = settings(db)
        if (
            not cfg
            or not cfg["enabled"]
            or cfg["owner_id"] != actor_id
            or not db.execute(
                "SELECT 1 FROM crm.users WHERE id=%s AND enabled AND role='admin'", (actor_id,)
            ).fetchone()
        ):
            raise ValueError("recovery_not_authorized")
        receipt = db.execute(
            "SELECT body,profile_id FROM crm.social_webhook_events WHERE event_id=%s AND event='message.received' AND profile_id=%s",
            (event_id, cfg["profile_id"]),
        ).fetchone()
        if not receipt:
            raise ValueError("recovery_signed_receipt_required")
        event = normalize(receipt["body"], receipt["profile_id"])
        if not event or cfg["accounts"].get(event["account_id"]) != event["platform"]:
            raise ValueError("recovery_scope_changed")
        earliest = datetime.now(UTC) - timedelta(hours=24)
        if (
            not max(cfg["enabled_at"], earliest)
            < workflow._time(event["sent_at"])
            <= datetime.now(UTC)
        ):
            raise ValueError("recovery_source_expired")
        if opted_out(event["text"]):
            raise ValueError("recovery_opted_out")
        scope = (receipt["profile_id"], event["account_id"], event["participant_id"])

        def recoverable_history():
            prior = db.execute(
                "SELECT * FROM crm.social_onboarding WHERE profile_id=%s AND account_id=%s AND participant_id=%s",
                scope,
            ).fetchall()
            if db.execute(
                "SELECT 1 FROM crm.whatsapp_agent_jobs WHERE profile_id=%s AND account_id=%s AND participant_id=%s LIMIT 1",
                scope,
            ).fetchone():
                raise ValueError("recovery_existing_history")
            if not prior:
                return None
            if (
                len(prior) != 1
                or prior[0]["state"] != "blocked"
                or prior[0]["suppressed"]
                or prior[0]["asked"]
                or not prior[0]["welcome_required"]
                or prior[0]["config_version"] != cfg["version"]
                or any(
                    prior[0][key]
                    for key in (
                        "audio_receipt",
                        "website_receipt",
                        "group_receipt",
                        "links_receipt",
                    )
                )
                or not db.execute(
                    "SELECT 1 FROM crm.social_welcome_claims WHERE onboarding_id=%s",
                    (prior[0]["id"],),
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM crm.social_onboarding_inputs WHERE onboarding_id=%s AND NOT processed AND message_id<>%s LIMIT 1",
                    (prior[0]["id"], event["message_id"]),
                ).fetchone()
            ):
                raise ValueError("recovery_existing_history")
            return prior[0]

        prior = recoverable_history()
        candidate = {
            **event,
            "id": None,
            "profile_id": receipt["profile_id"],
            "config_version": cfg["version"],
            "source": event,
            "recovery_event_id": event_id,
            "audio_receipt": {},
            "website_receipt": {},
            "group_receipt": {},
        }
        # Upstream reads must never hold the shared enrollment lock: fresh public
        # webhooks continue enrolling while the operator checks this candidate.
        onboarding_transport.recovery_source(db, candidate)
        db.execute("SELECT pg_advisory_xact_lock(9142041)")
        fresh_prior = recoverable_history()
        if (prior["id"] if prior else None) != (fresh_prior["id"] if fresh_prior else None):
            raise ValueError("recovery_existing_history")
        guard_scope(db, candidate)  # Configuration/owner may also have changed.
        _enqueue(db, receipt["body"], receipt["profile_id"], earliest=earliest)
        row = db.execute(
            "UPDATE crm.social_onboarding SET recovery_event_id=%s,source=%s,state='pending',error=NULL WHERE profile_id=%s AND account_id=%s AND conversation_id=%s RETURNING *",
            (
                event_id,
                Jsonb(event),
                receipt["profile_id"],
                event["account_id"],
                event["conversation_id"],
            ),
        ).fetchone()
        if not row:
            raise ValueError("recovery_not_admitted")
        guard(db, row)
        # The normal worker rechecks live unanswered proof before every send.
        return {"state": "queued", "id": str(row["id"]), "platform": row["platform"]}


def _enqueue(db, payload, profile_id, *, earliest):
    cfg = settings(db)
    if (
        not cfg
        or not cfg["enabled"]
        or cfg["profile_id"] != profile_id
        or datetime.now(UTC) >= WELCOME_UNTIL
    ):
        return False
    event = normalize(payload, profile_id)
    if not event or cfg["accounts"].get(event["account_id"]) != event["platform"]:
        return False
    current = whatsapp_agent.current(db)
    if (
        event["platform"] == "whatsapp"
        and current
        and (
            whatsapp_agent.developer(current["document"], event["participant_id"])
            or event["participant_id"] == current["document"]["phone"].lstrip("+")
        )
    ):
        return False
    sent = workflow._time(event["sent_at"])
    if not max(cfg["enabled_at"], earliest) < sent <= datetime.now(UTC):
        return True
    key = (profile_id, event["account_id"], event["conversation_id"])
    # Serialize participant claims across distinct conversations, including STOP.
    db.execute("SELECT pg_advisory_xact_lock(9142041)")
    old = db.execute(
        "SELECT * FROM crm.social_onboarding WHERE profile_id=%s AND account_id=%s AND conversation_id=%s FOR UPDATE",
        key,
    ).fetchone()
    if old and (
        old["participant_id"] != event["participant_id"] or old["platform"] != event["platform"]
    ):
        return True
    participant = (profile_id, event["account_id"], event["platform"], event["participant_id"])
    claim = db.execute(
        "SELECT onboarding_id FROM crm.social_welcome_claims WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s)",
        participant,
    ).fetchone()
    suppressed = opted_out(event["text"]) or participant_suppressed(db, participant)
    if suppressed:
        db.execute(
            "UPDATE crm.social_onboarding SET suppressed=true WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s)",
            participant,
        )
    if old:
        if suppressed or old["suppressed"]:
            return True
        if old["state"] == "completed" and old["contact_id"]:
            return event["platform"] == "facebook"
    elif (
        db.execute(
            "SELECT count(*) AS n FROM crm.social_onboarding WHERE created_at>now()-interval '24 hours'"
        ).fetchone()["n"]
        >= DAILY_WELCOME_LIMIT
    ):
        return True
    if not old:
        old = db.execute(
            """INSERT INTO crm.social_onboarding(profile_id,account_id,conversation_id,participant_id,
            platform,config_version,source,suppressed,welcome_required)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                *key,
                event["participant_id"],
                event["platform"],
                cfg["version"],
                Jsonb(event),
                suppressed,
                not bool(claim),
            ),
        ).fetchone()
        if not claim:
            db.execute(
                "INSERT INTO crm.social_welcome_claims(profile_id,account_id,platform,participant_id,onboarding_id) VALUES(%s,%s,%s,%s,%s)",
                (*participant, old["id"]),
            )
    if (
        not old["suppressed"]
        and db.execute(
            "SELECT count(*) AS n FROM crm.social_onboarding_inputs WHERE onboarding_id=%s AND created_at>now()-interval '24 hours'",
            (old["id"],),
        ).fetchone()["n"]
        < 30
    ):
        db.execute(
            "INSERT INTO crm.social_onboarding_inputs(onboarding_id,message_id,source) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (old["id"], event["message_id"], Jsonb(event)),
        )
    return True


def participant_suppressed(db, participant):
    return bool(
        db.execute(
            "SELECT 1 FROM crm.social_onboarding WHERE (profile_id,account_id,platform,participant_id)=(%s,%s,%s,%s) AND suppressed LIMIT 1",
            participant,
        ).fetchone()
    )


def guard_scope(db, row):
    cfg = settings(db)
    if (
        not cfg
        or not cfg["enabled"]
        or participant_suppressed(
            db, (row["profile_id"], row["account_id"], row["platform"], row["participant_id"])
        )
        or row["config_version"] != cfg["version"]
        or datetime.now(UTC) >= WELCOME_UNTIL
        or cfg["profile_id"] != row["profile_id"]
        or cfg["accounts"].get(row["account_id"]) != row["platform"]
        or not db.execute(
            "SELECT 1 FROM crm.users WHERE id=%s AND enabled AND role='admin'", (cfg["owner_id"],)
        ).fetchone()
    ):
        raise HTTPException(409, "onboarding_scope_changed")
    control.require_connections(db, "hermes", "zernio", row["platform"])
    credentials = config.required()
    if (
        credentials["profile_id"] != cfg["profile_id"]
        or workflow._digest(credentials) != cfg["credential_revision"]
    ):
        raise HTTPException(409, "onboarding_profile_changed")
    return cfg, credentials


def guard(db, row):
    cfg, credentials = guard_scope(db, row)
    actual = db.execute("SELECT * FROM crm.social_onboarding WHERE id=%s", (row["id"],)).fetchone()
    if (
        not actual
        or actual["suppressed"]
        or actual["config_version"] != cfg["version"]
        or actual["source"] != row["source"]
    ):
        raise HTTPException(409, "onboarding_scope_changed")
    return cfg, credentials


def check(row):
    return media._isolated({"operation": "welcome_check", "id": str(row["id"])})


def cached_audio(db):
    from ..voice import service as voice

    control.require_connections(db, "elevenlabs")
    control.require_capability(db, "voice.execute")
    provider = whatsapp_audio._provider(db)
    if settings(db)["voice"] != provider:
        raise HTTPException(409, "welcome_voice_changed")
    key = workflow._digest({"script": SCRIPT, **provider})
    audio = db.execute("SELECT * FROM crm.social_welcome_audio WHERE hash=%s", (key,)).fetchone()
    if audio:
        if audio["state"] != "ready":
            raise HTTPException(409, "welcome_audio_unconfirmed")
        return bytes(audio["data"])
    if db.execute("SELECT count(*) AS n FROM crm.social_welcome_audio").fetchone()["n"] >= 10:
        raise HTTPException(409, "welcome_audio_budget")
    request_id = uuid4()
    db.execute(
        "INSERT INTO crm.social_welcome_audio(hash,id,state) VALUES(%s,%s,'synthesizing')",
        (key, request_id),
    )
    db.commit()  # A crash/timeout never spends again for this immutable script and voice.
    result = voice.bridge.request(
        "/execute",
        {
            "id": str(request_id),
            "revision": provider["revision"],
            "operation": "tts",
            "arguments": {
                "text": SCRIPT,
                "voice_id": provider["voice_id"],
                "model_id": provider["model_id"],
            },
        },
        timeout=45,
    )
    data = voice.tts_audio(result)
    if whatsapp_audio._provider(db) != provider:
        raise HTTPException(409, "voice_provider_changed")
    db.execute(
        "UPDATE crm.social_welcome_audio SET state='ready',data=%s WHERE hash=%s", (data, key)
    )
    db.commit()
    return data


def tick():
    """One ordered transition at a time, serialized with existing Sara sends/revocations."""
    with connect() as db:
        if not db.execute("SELECT pg_try_advisory_lock(9142040) AS locked").fetchone()["locked"]:
            return
        db.execute("SELECT pg_advisory_lock(2026111105)")
        db.commit()
        row = None
        incoming = None
        reserved = False
        try:
            # These durable reservations can only remain after an interrupted process.
            db.execute(
                "UPDATE crm.social_onboarding SET state='unknown',error='interrupted' WHERE state IN ('audio_reserved','links_reserved','question_reserved','website_reserved','group_reserved')"
            )
            row = db.execute(
                """SELECT o.* FROM crm.social_onboarding o WHERE NOT suppressed AND (
                state IN ('pending','captured','audio_accepted','website_accepted') OR
                (state='waiting' AND NOT asked) OR EXISTS(
                SELECT 1 FROM crm.social_onboarding_inputs i WHERE i.onboarding_id=o.id AND NOT i.processed))
                ORDER BY created_at,id LIMIT 1"""
            ).fetchone()
            db.commit()
            if not row:
                return
            incoming = db.execute(
                "SELECT * FROM crm.social_onboarding_inputs WHERE onboarding_id=%s AND NOT processed ORDER BY created_at,id LIMIT 1",
                (row["id"],),
            ).fetchone()
            if incoming:
                db.execute(
                    "UPDATE crm.social_onboarding SET source=%s WHERE id=%s",
                    (Jsonb(incoming["source"]), row["id"]),
                )
                row["source"] = incoming["source"]
                db.commit()
            guard(db, row)
            source = check(row)
            if not row["contact_id"]:
                try:
                    value = details(row["source"]["text"], source["sender"], row["details"])
                except ValueError:
                    value = None  # Ask for corrected identity after the welcome; never guess.
                if value is not None:
                    # Plain name is accepted only in response to our explicit missing-name question.
                    if row["asked"] and "name" not in value and valid_name(row["source"]["text"]):
                        value["name"] = valid_name(row["source"]["text"])
                    db.execute(
                        "UPDATE crm.social_onboarding SET details=%s WHERE id=%s",
                        (Jsonb(value), row["id"]),
                    )
                    if set(value) == {"name", "phone"}:
                        record, deal = capture_contact(
                            db,
                            ContactInput(
                                **value,
                                source="whatsapp"
                                if row["platform"] == "whatsapp"
                                else "social_campaign",
                            ),
                        )
                        db.execute(
                            "UPDATE crm.social_onboarding SET contact_id=%s,deal_id=%s WHERE id=%s",
                            (record["id"], deal["id"], row["id"]),
                        )
                        row.update(contact_id=record["id"], deal_id=deal["id"])
            if incoming:
                db.execute(
                    "UPDATE crm.social_onboarding_inputs SET processed=true WHERE id=%s",
                    (incoming["id"],),
                )
            db.commit()  # Real identity capture never waits for a media delivery.
            if row["state"] in {"unknown", "blocked"}:
                return
            if row["welcome_required"] and row["state"] in {"pending", "captured"}:
                phase = "audio"
            elif row["welcome_required"] and row["state"] == "audio_accepted":
                phase = "website"
            elif row["welcome_required"] and row["state"] == "website_accepted":
                phase = "group"
            else:
                if row["contact_id"] or row["asked"]:
                    db.execute(
                        "UPDATE crm.social_onboarding SET state=%s WHERE id=%s",
                        ("completed" if row["contact_id"] else "waiting", row["id"]),
                    )
                    db.commit()
                    return
                phase = "question"
            if phase == "audio":
                data = cached_audio(db)
                db.execute(
                    "UPDATE crm.social_onboarding SET audio=%s WHERE id=%s", (data, row["id"])
                )
            guard(db, row)
            db.execute(
                "UPDATE crm.social_onboarding SET state=%s,updated_at=now() WHERE id=%s",
                (phase + "_reserved", row["id"]),
            )
            db.commit()
            reserved = True
            result = media._isolated({"operation": "welcome_" + phase, "id": str(row["id"])})
            if result.get("state") != "completed":
                raise ValueError("welcome_delivery_unconfirmed")
            target = {
                "audio": "audio_accepted",
                "website": "website_accepted",
                "group": "completed" if row["contact_id"] else "waiting",
                "question": "waiting",
            }[phase]
            db.execute(
                """UPDATE crm.social_onboarding SET state=%s,asked=asked OR %s,
                audio_receipt=CASE WHEN %s THEN %s ELSE audio_receipt END,
                website_receipt=CASE WHEN %s THEN %s ELSE website_receipt END,
                group_receipt=CASE WHEN %s THEN %s ELSE group_receipt END,
                audio=NULL,updated_at=now() WHERE id=%s""",
                (
                    target,
                    phase == "question",
                    phase == "audio",
                    Jsonb(result.get("receipt", {})),
                    phase == "website",
                    Jsonb(result.get("receipt", {})),
                    phase == "group",
                    Jsonb(result.get("receipt", {})),
                    row["id"],
                ),
            )
            db.commit()
        except Exception:  # noqa: BLE001 - no provider errors, PII or credentials in logs
            db.rollback()
            if row:
                if incoming:
                    db.execute(
                        "UPDATE crm.social_onboarding_inputs SET processed=true WHERE id=%s",
                        (incoming["id"],),
                    )
                db.execute(
                    "UPDATE crm.social_onboarding SET state=%s,error='welcome_not_confirmed',audio=NULL WHERE id=%s",
                    ("unknown" if reserved or row["state"] == "unknown" else "blocked", row["id"]),
                )
                db.commit()
        finally:
            db.execute("SELECT pg_advisory_unlock(2026111105)")
            db.execute("SELECT pg_advisory_unlock(9142040)")
            db.commit()
