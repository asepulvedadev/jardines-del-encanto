"""Owner-authorized internal WhatsApp outbox, independent of public Sara replies."""

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..campaigns import reviews
from ..control import service as control
from ..crm.database import connect
from . import config, lead_capture_worker, whatsapp_agent, workflow

ZONE = ZoneInfo("America/Bogota")
LOCK = 9142072
LEAD_TEMPLATE = "jardines_equipo_nuevo_lead_v1"
REPORT_TEMPLATE = "jardines_equipo_reporte_leads_v1"
LEAD_BODY = (
    "Nuevo lead registrado en Jardines del Encanto.\nNombre: {{1}}.\n"
    "Celular: {{2}}.\nOrigen: {{3}}.\nAviso interno para el equipo comercial."
)
REPORT_BODY = (
    "Reporte interno de Jardines del Encanto: {{1}}.\nTotal acumulado: {{2}}.\n"
    "Desglose acumulado: {{3}}.\nRegistros del día: {{4}}.\n"
    "Desglose del día: {{5}}.\nÚltima hora: {{6}}.\nHora de Colombia."
)


def now():
    return datetime.now(UTC)


def identity(document):
    return workflow._digest({k: document[k] for k in ("account_id", "phone", "developers")})


def verify_account(credentials, document):
    account = workflow._account(credentials, document["account_id"])
    phone = re.sub(r"[^0-9]", "", str(account.get("metadata", {}).get("displayPhoneNumber", "")))
    if account["platform"] != "whatsapp" or phone != document["phone"].lstrip("+"):
        raise HTTPException(409, "notice_account_unverified")


def resolve_recipients(credentials, document):
    # Only these two owner-configured developer numbers are eligible destinations.
    recipients = document["developers"]
    names = {
        unicodedata.normalize("NFKD", r["name"]).encode("ascii", "ignore").decode().casefold()
        for r in recipients
    }
    if len(recipients) != 2 or names != {"johan", "andres"}:
        raise HTTPException(409, "notice_recipients_unverified")
    matches = _matching_threads(
        credentials, document["account_id"], [r["phone"] for r in recipients]
    )
    return [{**r, "conversation_id": next(iter(matches[r["phone"]]), None)} for r in recipients]


def _matching_threads(credentials, account_id, phones):
    matches = {phone: set() for phone in phones}
    for status in ("active", "archived"):
        cursor = None
        for _ in range(20):
            query = {"platform": "whatsapp", "status": status, "limit": 100}
            if cursor:
                query["cursor"] = cursor
            value = lead_capture_worker.read(
                credentials, account_id, "listInboxConversations", query
            )
            rows, following = lead_capture_worker.page(value, "data", cursor)
            for row in rows:
                if row.get("accountId") != account_id or row.get("platform") != "whatsapp":
                    raise HTTPException(409, "notice_recipient_scope")
                participant = row.get("participantId")
                if isinstance(participant, str) and re.fullmatch(
                    r"\+?[1-9][0-9]{7,14}", participant
                ):
                    phone = "+" + participant.lstrip("+")
                    if phone in matches:
                        workflow._control(row)
                        matches[phone].add(workflow._identifier(row.get("id")))
            cursor = following
            if cursor is None:
                break
        else:
            raise HTTPException(409, "notice_recipient_scan_incomplete")
    if any(len(ids) > 1 for ids in matches.values()):
        raise HTTPException(409, "notice_recipient_ambiguous")
    return matches


def configure(db, owner_id):
    credentials = config.required()
    agent = whatsapp_agent.current(db)
    if not agent or not agent["enabled"]:
        raise HTTPException(409, "notice_agent_disabled")
    document = whatsapp_agent.Document.model_validate(agent["document"]).model_dump()
    verify_account(credentials, document)
    recipients = resolve_recipients(credentials, document)
    whatsapp_agent.lock(db)
    control.lock(db)
    current = whatsapp_agent.current(db)
    if not current or not current["enabled"] or identity(current["document"]) != identity(document):
        raise HTTPException(409, "notice_configuration_changed")
    if not db.execute(
        "SELECT 1 FROM crm.users WHERE id=%s AND enabled AND role='admin'", (owner_id,)
    ).fetchone():
        raise HTTPException(409, "notice_owner_unavailable")
    control.require_connections(db, "zernio", "whatsapp")
    value = now()
    hour = value.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    daily = value.astimezone(ZONE).replace(hour=22, minute=0, second=0, microsecond=0)
    if daily <= value:
        daily += timedelta(days=1)
    # Explicit activation never replays existing contacts or rewinds sent periods.
    if db.execute("SELECT 1 FROM crm.lead_notice_config WHERE singleton AND enabled").fetchone():
        raise HTTPException(409, "notice_already_enabled")
    db.execute(
        """INSERT INTO crm.lead_notice_config(singleton,owner_id,profile_id,account_id,
       credential_revision,document_revision,recipients,activated_at,next_hour,next_daily,enabled)
       VALUES(true,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
       ON CONFLICT(singleton) DO UPDATE SET epoch=gen_random_uuid(),owner_id=EXCLUDED.owner_id,
       profile_id=EXCLUDED.profile_id,account_id=EXCLUDED.account_id,
       credential_revision=EXCLUDED.credential_revision,document_revision=EXCLUDED.document_revision,
       recipients=EXCLUDED.recipients,activated_at=EXCLUDED.activated_at,
       next_hour=EXCLUDED.next_hour,next_daily=EXCLUDED.next_daily,enabled=true""",
        (
            owner_id,
            credentials["profile_id"],
            document["account_id"],
            workflow._digest(credentials),
            identity(document),
            Jsonb(recipients),
            value,
            hour,
            daily,
        ),
    )
    control.audit(
        db,
        {"id": owner_id},
        "lead.notifications.enable",
        {"timezone": "America/Bogota", "daily_hour": 22, "recipients": 2},
    )


def origin(db, contact_id, source):
    if source == "whatsapp":
        return "WhatsApp"
    if (
        source == "social_campaign"
        and db.execute(
            """SELECT 1 WHERE
       EXISTS(SELECT 1 FROM crm.social_onboarding WHERE contact_id=%s AND platform='facebook') OR
       EXISTS(SELECT 1 FROM crm.lead_capture_threads WHERE contact_id=%s AND platform='facebook' AND status='registered')""",
            (contact_id, contact_id),
        ).fetchone()
    ):
        return "Facebook"
    return "Otros / sin confirmar"


def counts(db, cutoff):
    day = cutoff.astimezone(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    row = db.execute(
        """WITH categorized AS (
       SELECT c.created_at,CASE WHEN c.source='whatsapp' THEN 'whatsapp'
       WHEN c.source='social_campaign' AND (
        EXISTS(SELECT 1 FROM crm.social_onboarding s WHERE s.contact_id=c.id AND s.platform='facebook') OR
        EXISTS(SELECT 1 FROM crm.lead_capture_threads s WHERE s.contact_id=c.id AND s.platform='facebook' AND s.status='registered'))
       THEN 'facebook' ELSE 'other' END AS channel FROM crm.contacts c WHERE c.created_at<%s)
       SELECT count(*) AS total,
       count(*) FILTER(WHERE channel='whatsapp') AS whatsapp,
       count(*) FILTER(WHERE channel='facebook') AS facebook,
       count(*) FILTER(WHERE channel='other') AS other,
       count(*) FILTER(WHERE created_at>=%s) AS today,
       count(*) FILTER(WHERE created_at>=%s AND channel='whatsapp') AS today_whatsapp,
       count(*) FILTER(WHERE created_at>=%s AND channel='facebook') AS today_facebook,
       count(*) FILTER(WHERE created_at>=%s AND channel='other') AS today_other,
       count(*) FILTER(WHERE created_at>=%s) AS hour FROM categorized""",
        (cutoff, day, day, day, day, cutoff - timedelta(hours=1)),
    ).fetchone()
    return dict(row)


def schedule(db, value):
    cfg = db.execute(
        "SELECT * FROM crm.lead_notice_config WHERE singleton AND enabled FOR UPDATE"
    ).fetchone()
    if not cfg:
        return
    due = []
    daily_cutoff = None
    if value >= cfg["next_daily"]:
        daily_cutoff = value.astimezone(ZONE).replace(hour=22, minute=0, second=0, microsecond=0)
        if daily_cutoff > value:
            daily_cutoff -= timedelta(days=1)
        due.append(("daily", daily_cutoff))
        db.execute(
            "UPDATE crm.lead_notice_config SET next_daily=%s WHERE singleton",
            (daily_cutoff + timedelta(days=1),),
        )
    if value >= cfg["next_hour"]:
        cutoff = value.replace(minute=0, second=0, microsecond=0)
        if cutoff != daily_cutoff:
            due.append(("hourly", cutoff))
        db.execute(
            "UPDATE crm.lead_notice_config SET next_hour=%s WHERE singleton",
            (cutoff + timedelta(hours=1),),
        )
    for kind, cutoff in due:
        key = f"{cfg['epoch']}:{kind}:{cutoff.isoformat()}"
        saved = db.execute(
            """INSERT INTO crm.lead_notice_events(id,epoch,kind,cutoff,payload)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
            (key, cfg["epoch"], kind, cutoff, Jsonb(counts(db, cutoff))),
        ).fetchone()
        if saved:
            for recipient in cfg["recipients"]:
                db.execute(
                    """INSERT INTO crm.lead_notice_deliveries(event_id,recipient_phone,conversation_id)
                   VALUES(%s,%s,%s)""",
                    (key, recipient["phone"], recipient["conversation_id"]),
                )


def content(event):
    p = event["payload"]
    if event["kind"] == "lead":
        params = [p["name"], p["phone"], p["origin"]]
        body = LEAD_BODY
    else:
        label = (
            ("Cierre del día" if event["kind"] == "daily" else "Reporte por hora")
            + " "
            + event["cutoff"].astimezone(ZONE).strftime("%d/%m/%Y %H:%M")
        )
        total = f"WhatsApp: {p['whatsapp']}, Facebook: {p['facebook']}, otros/sin confirmar: {p['other']}"
        daily = f"WhatsApp: {p['today_whatsapp']}, Facebook: {p['today_facebook']}, otros/sin confirmar: {p['today_other']}"
        params, body = (
            [label, str(p["total"]), total, str(p["today"]), daily, str(p["hour"])],
            REPORT_BODY,
        )
    for index, value in enumerate(params, 1):
        value = " ".join(str(value).split())[:1024]
        params[index - 1] = value
        body = body.replace("{{" + str(index) + "}}", value)
    return body, params


def read_thread(credentials, row):
    if not row["conversation_id"]:
        matches = _matching_threads(credentials, row["account_id"], [row["recipient_phone"]])
        conversation = next(iter(matches[row["recipient_phone"]]), None)
        if conversation is None:
            return None
        row = {**row, "conversation_id": conversation}
    value = lead_capture_worker.read(
        credentials,
        row["account_id"],
        "getInboxConversation",
        path={"conversationId": row["conversation_id"]},
    )
    thread = value.get("data")
    if (
        not isinstance(thread, dict)
        or any(
            thread.get(k) != v
            for k, v in {
                "id": row["conversation_id"],
                "accountId": row["account_id"],
                "platform": "whatsapp",
            }.items()
        )
        or str(thread.get("participantId")).lstrip("+") != row["recipient_phone"].lstrip("+")
    ):
        raise HTTPException(409, "notice_recipient_scope")
    workflow._control(thread)
    return thread


def prepare(credentials, row, event):
    body, params = content(event)
    thread = read_thread(credentials, row)
    if thread:
        try:
            workflow._window(credentials, thread)
            return "reply", {"accountId": row["account_id"], "message": body}, thread["id"]
        except HTTPException as error:
            if error.detail != "zernio_window_unconfirmed":
                raise
    name = LEAD_TEMPLATE if event["kind"] == "lead" else REPORT_TEMPLATE
    expected = LEAD_BODY if event["kind"] == "lead" else REPORT_BODY
    templates = [
        t
        for t in workflow._templates(credentials, row["account_id"])
        if t.get("name") == name and t.get("language") == "es_CO"
    ]
    if len(templates) != 1:
        raise HTTPException(409, "notice_template_pending")
    info = workflow._template_info(templates[0])
    components = templates[0].get("components")
    if (
        info["body"] != expected
        or info["parameter_count"] != len(params)
        or not isinstance(components, list)
        or len(components) != 1
        or str(components[0].get("type", "")).upper() != "BODY"
    ):
        raise HTTPException(409, "notice_template_changed")
    return (
        "open",
        {
            "accountId": row["account_id"],
            "participantId": row["recipient_phone"].lstrip("+"),
            "templateName": name,
            "templateLanguage": "es_CO",
            "templateParams": params,
        },
        None,
    )


def send(credentials, operation, payload, thread, key):
    return workflow._request(
        credentials,
        operation,
        account_id=payload["accountId"],
        conversation_id=thread,
        payload=payload,
        request_id=key,
    )


def guard(db, cfg):
    fresh = db.execute("SELECT * FROM crm.lead_notice_config WHERE singleton").fetchone()
    agent = whatsapp_agent.current(db)
    if (
        not fresh
        or not fresh["enabled"]
        or fresh["epoch"] != cfg["epoch"]
        or not agent
        or not agent["enabled"]
        or identity(agent["document"]) != cfg["document_revision"]
    ):
        raise HTTPException(409, "notice_authorization_revoked")
    if not db.execute(
        "SELECT 1 FROM crm.users WHERE id=%s AND enabled AND role='admin'", (cfg["owner_id"],)
    ).fetchone():
        raise HTTPException(409, "notice_authorization_revoked")
    control.require_connections(db, "zernio", "whatsapp")
    credentials = config.required()
    if (
        credentials["profile_id"] != cfg["profile_id"]
        or workflow._digest(credentials) != cfg["credential_revision"]
    ):
        raise HTTPException(409, "notice_authorization_revoked")
    verify_account(credentials, agent["document"])
    return credentials


def tick():
    with connect() as db:
        if not db.execute("SELECT pg_try_advisory_lock(%s) AS held", (LOCK,)).fetchone()["held"]:
            return
        db.commit()
        # A previous dispatch reservation is ambiguous after a crash. Never replay it.
        db.execute(
            "UPDATE crm.lead_notice_deliveries SET state='unknown',error='notice_interrupted' WHERE state='reserved'"
        )
        schedule(db, now())
        cfg = db.execute("SELECT * FROM crm.lead_notice_config WHERE singleton").fetchone()
        rows = db.execute(
            "SELECT * FROM crm.lead_notice_deliveries WHERE state='pending' AND next_attempt<=now() ORDER BY next_attempt,id LIMIT 10"
        ).fetchall()
        db.commit()
        for row in rows:
            # Same ordering as the public worker and all owner revocations.
            db.execute("SELECT pg_advisory_lock(9142040)")
            db.execute("SELECT pg_advisory_lock(2026111105)")
            db.commit()
            reserved = False
            try:
                with config.locked():
                    credentials = guard(db, cfg)
                    if row["recipient_phone"] not in {r["phone"] for r in cfg["recipients"]}:
                        raise HTTPException(409, "notice_authorization_revoked")
                    event = db.execute(
                        "SELECT * FROM crm.lead_notice_events WHERE id=%s", (row["event_id"],)
                    ).fetchone()
                    if event["epoch"] != cfg["epoch"]:
                        raise HTTPException(409, "notice_authorization_revoked")
                    if event["kind"] == "lead" and "origin" not in event["payload"]:
                        event["payload"]["origin"] = origin(
                            db, event["contact_id"], event["payload"]["source"]
                        )
                        db.execute(
                            "UPDATE crm.lead_notice_events SET payload=%s WHERE id=%s",
                            (Jsonb(event["payload"]), event["id"]),
                        )
                    operation, payload, thread = prepare(
                        credentials, {**row, "account_id": cfg["account_id"]}, event
                    )
                    reservation = db.execute(
                        "UPDATE crm.lead_notice_deliveries SET state='reserved',reserved_at=now(),error=NULL WHERE id=%s AND state='pending' RETURNING id",
                        (row["id"],),
                    ).fetchone()
                    if not reservation:
                        raise HTTPException(409, "notice_authorization_revoked")
                    db.commit()
                    reserved = True
                    result = send(
                        credentials, operation, payload, thread, "lead-notice-" + str(row["id"])
                    )
                    data = result.get("data")
                    if (
                        result.get("success") is False
                        or result.get("status") in {"failed", "error"}
                        or not isinstance(data, dict)
                    ):
                        raise ValueError("unconfirmed")
                    workflow._identifier(data.get("id") or data.get("messageId"))
                    if thread and data.get("conversationId") != thread:
                        raise ValueError("scope")
                    if ("accountId" in data and data["accountId"] != cfg["account_id"]) or (
                        "participantId" in data
                        and str(data["participantId"]).lstrip("+")
                        != row["recipient_phone"].lstrip("+")
                    ):
                        raise ValueError("scope")
                    receipt = {
                        k: data[k] for k in ("id", "messageId", "conversationId") if k in data
                    }
                    db.execute(
                        "UPDATE crm.lead_notice_deliveries SET state='accepted',receipt=%s,finished_at=now() WHERE id=%s",
                        (Jsonb(receipt), row["id"]),
                    )
                    db.commit()
            except Exception as error:  # noqa: BLE001 - finite diagnostics; never log payloads
                db.rollback()
                reason = error.detail if isinstance(error, HTTPException) else "notice_unavailable"
                revoked = reason == "notice_authorization_revoked"
                state = "unknown" if reserved else "cancelled" if revoked else "pending"
                safe = (
                    reason
                    if reason
                    in {
                        "notice_authorization_revoked",
                        "notice_template_pending",
                        "notice_template_changed",
                        "notice_recipient_scope",
                        "notice_account_unverified",
                        "connection_disabled",
                    }
                    else "notice_unavailable"
                )
                db.execute(
                    "UPDATE crm.lead_notice_deliveries SET state=%s,error=%s,next_attempt=now()+interval '60 seconds' WHERE id=%s",
                    (state, safe, row["id"]),
                )
                db.commit()
            finally:
                db.execute("SELECT pg_advisory_unlock(2026111105)")
                db.execute("SELECT pg_advisory_unlock(9142040)")
                db.commit()
        db.execute(
            "UPDATE crm.lead_notice_config SET worker_last_tick=clock_timestamp() WHERE singleton"
        )
        db.commit()


def submit_templates():
    """Explicit owner maintenance only. A durable reservation forbids blind POST retries."""
    credentials = config.required()
    with connect() as db:
        cfg = db.execute(
            "SELECT * FROM crm.lead_notice_config WHERE singleton AND enabled"
        ).fetchone()
        if not cfg:
            raise HTTPException(409, "notice_not_configured")
    for name, body, examples in [
        (LEAD_TEMPLATE, LEAD_BODY, ["Ana Prueba", "+573001234567", "WhatsApp"]),
        (
            REPORT_TEMPLATE,
            REPORT_BODY,
            [
                "Cierre del día 16/11/2026 22:00",
                "20",
                "WhatsApp: 7, Facebook: 8, otros/sin confirmar: 5",
                "4",
                "WhatsApp: 2, Facebook: 1, otros/sin confirmar: 1",
                "3",
            ],
        ),
    ]:
        with connect() as db:
            db.execute("SELECT pg_advisory_lock(9142040)")
            db.execute("SELECT pg_advisory_lock(2026111105)")
            db.commit()
            try:
                with config.locked():
                    credentials = guard(db, cfg)
                    created = db.execute(
                        "INSERT INTO crm.lead_notice_templates(name,status) VALUES(%s,'SUBMITTING') ON CONFLICT DO NOTHING RETURNING name",
                        (name,),
                    ).fetchone()
                    db.commit()
                    if not created:
                        continue
                    status, provider_id = "UNKNOWN", None
                    try:
                        result = reviews.request(
                            credentials,
                            "POST",
                            "/v1/whatsapp/templates",
                            {
                                "accountId": cfg["account_id"],
                                "name": name,
                                "language": "es_CO",
                                "category": "UTILITY",
                                "components": [
                                    {
                                        "type": "body",
                                        "text": body,
                                        "example": {"body_text": [examples]},
                                    }
                                ],
                            },
                        )
                        template = reviews.validated_template(result.get("template"), name)
                        status, provider_id = template["status"], template["id"]
                    except HTTPException:
                        pass
                    db.execute(
                        "UPDATE crm.lead_notice_templates SET status=%s,provider_id=%s WHERE name=%s",
                        (status, provider_id, name),
                    )
                    db.commit()
            finally:
                db.rollback()
                db.execute("SELECT pg_advisory_unlock(2026111105)")
                db.execute("SELECT pg_advisory_unlock(9142040)")
                db.commit()


def status():
    with connect() as db:
        cfg = db.execute(
            "SELECT enabled,activated_at,next_hour,next_daily,worker_last_tick FROM crm.lead_notice_config WHERE singleton"
        ).fetchone()
        rows = db.execute(
            "SELECT state,error,count(*) AS count FROM crm.lead_notice_deliveries GROUP BY state,error"
        ).fetchall()
        templates = db.execute("SELECT name,status FROM crm.lead_notice_templates").fetchall()
    return {
        "configuration": cfg,
        "deliveries": rows,
        "templates": templates,
        "timezone": "America/Bogota",
        "worker_alive": bool(
            cfg
            and cfg["worker_last_tick"]
            and now() - cfg["worker_last_tick"] < timedelta(seconds=120)
        ),
    }
