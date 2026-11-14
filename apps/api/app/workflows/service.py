"""Human review and immutable run grants; no browser-session impersonation."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from ..control import service as control
from . import models

EXTERNAL = {"whatsapp_template", "social_message", "retell_call"}
LABELS = {
    "whatsapp_template": "Plantilla de WhatsApp",
    "social_message": "Mensaje social",
    "retell_call": "Llamada Retell",
    "wait": "Espera",
    "condition": "Condición CRM",
    "crm_note": "Nota CRM",
    "crm_task": "Tarea CRM",
    "end": "Fin",
}


def now():
    return datetime.now(UTC)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            jsonable_encoder(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def event(db, run_id, kind, message, contact_id=None, node_id=None):
    db.execute(
        "INSERT INTO crm.workflow_events(run_id,kind,message,contact_id,node_id) VALUES (%s,%s,%s,%s,%s)",
        (run_id, kind, message, contact_id, node_id),
    )


def definition(db, record_id, lock=False):
    row = db.execute(
        "SELECT * FROM crm.workflow_definitions WHERE id=%s" + (" FOR UPDATE" if lock else ""),
        (record_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    return row


def definitions(db):
    return {
        "workflows": db.execute(
            "SELECT * FROM crm.workflow_definitions ORDER BY updated_at DESC,id LIMIT 200"
        ).fetchall()
    }


def create(db, data, admin):
    return db.execute(
        "INSERT INTO crm.workflow_definitions(name,description,document) VALUES (%s,%s,%s) RETURNING *",
        (data.name, data.description, Jsonb(data.document.model_dump())),
    ).fetchone()


def update(db, record_id, data, admin):
    row = definition(db, record_id, True)
    if row["version"] != data.version:
        raise HTTPException(409, "record_changed")
    changes = data.model_dump(exclude_unset=True)
    return db.execute(
        "UPDATE crm.workflow_definitions SET name=%s,description=%s,document=%s,version=version+1,updated_at=now() WHERE id=%s RETURNING *",
        (
            changes.get("name", row["name"]),
            changes.get("description", row["description"]),
            Jsonb(changes.get("document", row["document"])),
            record_id,
        ),
    ).fetchone()


def contact(db, contact_id):
    row = db.execute(
        "SELECT c.id,c.name,c.phone,c.source,c.version,d.id AS deal_id,d.stage FROM crm.contacts c LEFT JOIN crm.deals d ON d.contact_id=c.id WHERE c.id=%s FOR SHARE OF c",
        (contact_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "contact_not_found")
    return jsonable_encoder(row)


def render(value, recipient):
    if isinstance(value, dict):
        return {key: render(child, recipient) for key, child in value.items()}
    if isinstance(value, list):
        return [render(child, recipient) for child in value]
    if isinstance(value, str):
        return value.replace("{{nombre}}", recipient["name"]).replace(
            "{{celular}}", recipient["phone"]
        )
    return value


def retell_args(node, recipient):
    from ..retell.models import Execute

    return Execute(
        endpoint="createPhoneCall",
        arguments={
            "requestBody": {
                "from_number": node["settings"]["from_number"],
                "to_number": recipient["phone"],
                "override_agent_id": node["settings"]["agent_id"],
            }
        },
        contacts=[{"contact_id": recipient["id"], "expected_phone": recipient["phone"]}],
    )


def prepare_plan(db, node, recipient, binding, admin, cache=None):
    if node["kind"] in {"social_message", "whatsapp_template"}:
        from ..social import workflow

        return workflow.prepare(db, node, recipient, binding, cache=cache)
    if node["kind"] == "retell_call":
        from ..retell import service as retell

        args = retell_args(node, recipient)
        return {
            "args": args.model_dump(mode="json"),
            "revisions": retell.freeze(db, args, admin),
            "summary": {
                "description": f"Llamada a {recipient['phone']} desde {node['settings']['from_number']} · agente {node['settings']['agent_id']}"
            },
        }
    settings = node["settings"]
    description = node["label"]
    if node["kind"] == "crm_note":
        description = "Nota: " + settings["body"]
    elif node["kind"] == "crm_task":
        description = f"Tarea: {settings['title']} · vencimiento {settings['due_days']} días después del paso."
    elif node["kind"] == "wait":
        description = f"Esperar {settings['hours']} horas."
    elif node["kind"] == "condition":
        description = f"Si {settings['field']} es {settings['value']}: {node['on_true']}; si no: {node['on_false']}."
    return {"summary": {"description": description}}


def connection_revisions(db, nodes):
    keys = set()
    for node in nodes:
        if node["kind"] == "retell_call":
            keys.add("retell")
        elif node["kind"] in {"social_message", "whatsapp_template"}:
            keys.update(["zernio", node["settings"].get("platform", "whatsapp")])
    if not keys:
        return {}
    control.require_connections(db, *sorted(keys))
    rows = db.execute(
        "SELECT key,version FROM crm.control_connections WHERE key=ANY(%s)", (sorted(keys),)
    ).fetchall()
    return {"connection:" + row["key"]: row["version"] for row in rows}


def prepare(db, record_id, data, admin):
    if not data.consent_confirmed:
        raise HTTPException(422, "workflow_consent_required")
    control.lock(db)
    row = definition(db, record_id, True)
    if row["version"] != data.version:
        raise HTTPException(409, "record_changed")
    doc = models.Document.model_validate(row["document"]).model_dump()
    if len(data.contact_ids) * sum(n["kind"] in EXTERNAL for n in doc["nodes"]) > 10:
        raise HTTPException(422, "workflow_provider_review_limit")
    deadline, cache = monotonic() + 60, {}
    revisions = connection_revisions(db, doc["nodes"])
    action_by_kind = {
        "crm_note": "crm.note.create",
        "crm_task": "crm.task.create",
        "retell_call": "retell.execute",
    }
    revisions.update(
        control.revisions(
            db,
            sorted(
                {action_by_kind[n["kind"]] for n in doc["nodes"] if n["kind"] in action_by_kind}
            ),
        )
    )
    bindings = {str(b.contact_id): b.model_dump(mode="json") for b in data.bindings}
    audience, plans = [], {}
    for contact_id in data.contact_ids:
        recipient = contact(db, contact_id)
        audience.append(recipient)
        plans[str(contact_id)] = {}
        for source in doc["nodes"]:
            node = render(source, recipient)
            if monotonic() >= deadline:
                raise HTTPException(503, "workflow_review_budget_exceeded")
            plans[str(contact_id)][node["id"]] = prepare_plan(
                db, node, recipient, bindings.get(str(contact_id)), admin, cache
            )
    frozen = {
        "document": doc,
        "audience": audience,
        "plans": plans,
        "bindings": bindings,
        "revisions": revisions,
        "max_external_actions": len(audience) * sum(n["kind"] in EXTERNAL for n in doc["nodes"]),
    }
    if monotonic() >= deadline:
        raise HTTPException(503, "workflow_review_budget_exceeded")
    expires = now() + timedelta(minutes=10)
    result = db.execute(
        "INSERT INTO crm.workflow_runs(workflow_id,workflow_name,workflow_version,snapshot,fingerprint,prepared_by,review_expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            row["id"],
            row["name"],
            row["version"],
            Jsonb(frozen),
            fingerprint(frozen),
            admin["id"],
            expires,
        ),
    ).fetchone()
    for person in audience:
        db.execute(
            "INSERT INTO crm.workflow_recipients(run_id,contact_id,current_node_id) VALUES (%s,%s,%s)",
            (result["id"], person["id"], doc["entry_id"]),
        )
    event(db, result["id"], "prepared", "Revisión congelada; no se ha enviado ninguna acción.")
    return review(db, result)


def run_row(db, record_id, lock=False):
    row = db.execute(
        "SELECT * FROM crm.workflow_runs WHERE id=%s" + (" FOR UPDATE" if lock else ""),
        (record_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    return row


def run_view(db, row):
    counts = {key: 0 for key in ("total", "completed", "active", "blocked", "unknown", "stopped")}
    for count in db.execute(
        "SELECT status,count(*) AS total FROM crm.workflow_recipients WHERE run_id=%s GROUP BY status",
        (row["id"],),
    ).fetchall():
        counts[count["status"]] = count["total"]
        counts["total"] += count["total"]
    grant = db.execute(
        "SELECT expires_at FROM crm.workflow_grants WHERE run_id=%s", (row["id"],)
    ).fetchone()
    return {
        key: row[key]
        for key in (
            "id",
            "workflow_id",
            "workflow_name",
            "workflow_version",
            "status",
            "version",
            "created_at",
            "started_at",
        )
    } | {"expires_at": grant["expires_at"] if grant else row["review_expires_at"], "counts": counts}


def summary_text(summary):
    labels = {
        "account_id": "Cuenta remitente",
        "platform": "Canal",
        "recipient": "Destinatario del canal",
        "conversation_id": "Conversación",
        "template_name": "Plantilla",
        "language": "Idioma",
        "text": "Mensaje exacto",
        "template_body": "Texto de plantilla",
    }
    parts = [str(summary.get("description", ""))]
    for key, label in labels.items():
        if summary.get(key) is not None:
            parts.append(f"{label}: {summary[key]}")
    if "parameters" in summary:
        parts.append(
            "Parámetros exactos: "
            + "; ".join(f"{i + 1}: {text}" for i, text in enumerate(summary["parameters"]))
        )
    for component in summary.get("template_components", []):
        parts.append(f"{component['type']}: {component['text']}")
    return "\n".join(parts)


def review(db, row):
    frozen = row["snapshot"]
    recipients = []
    for p in frozen["audience"]:
        safe = {"contact_id": p["id"], **{key: p[key] for key in ("name", "phone", "source")}}
        plan = next(
            (plan for plan in frozen["plans"][p["id"]].values() if plan.get("participant_id")), None
        )
        if plan:
            safe["channel_recipient"] = plan["summary"]
        recipients.append(safe)
    steps = []
    for n in frozen["document"]["nodes"]:
        descriptions = []
        for person in frozen["audience"]:
            summary = frozen["plans"][person["id"]][n["id"]]["summary"]
            descriptions.append(
                person["name"] + " · " + person["phone"] + "\n" + summary_text(summary)
            )
        steps.append(
            {
                "node_id": n["id"],
                "kind": n["kind"],
                "label": n["label"],
                "description": "\n\n".join(descriptions),
            }
        )
    return {
        "run": run_view(db, row),
        "fingerprint": row["fingerprint"],
        "expires_at": row["review_expires_at"],
        "recipients": recipients,
        "steps": steps,
        "warnings": [
            f"Horario aprobado: America/Bogota · días {','.join(str(d) for d in frozen['document']['schedule']['days'])} (1=lunes; 7=domingo) · {frozen['document']['schedule']['start_time']}–{frozen['document']['schedule']['end_time']} · máximo {frozen['document']['schedule']['daily_limit']} acciones externas/día y {frozen['max_external_actions']} en total.",
            "Detener al recibir respuesta verificada: "
            + ("sí" if frozen["document"]["stop_on_reply"] else "no"),
            "La aprobación vence en 30 días. Los resultados inciertos se retienen sin reintento automático.",
            "Los horarios usan días 1=lunes a 7=domingo. Envío aceptado no significa entrega, llamada contestada ni venta.",
            "Retell no dispone de ruta colombiana +57 verificada.",
        ],
    }


def check_snapshot(db, row, admin=None, check_all=True):
    frozen = row["snapshot"]
    deadline = monotonic() + 60
    if fingerprint(frozen) != row["fingerprint"]:
        raise HTTPException(409, "workflow_snapshot_changed")
    control.check_revisions(db, frozen["revisions"])
    for person in frozen["audience"]:
        current = contact(db, person["id"])
        if any(current[k] != person[k] for k in ("name", "phone", "source", "version", "deal_id")):
            raise HTTPException(409, "workflow_contact_changed")
        if check_all:
            for node in frozen["document"]["nodes"]:
                if monotonic() >= deadline:
                    raise HTTPException(503, "workflow_review_budget_exceeded")
                check_plan(db, node, frozen["plans"][person["id"]][node["id"]], admin)
    if monotonic() >= deadline:
        raise HTTPException(503, "workflow_review_budget_exceeded")


def check_plan(db, node, plan, admin=None, request_id=None):
    if node["kind"] in {"social_message", "whatsapp_template"}:
        from ..social import workflow

        workflow.check(plan)
    elif node["kind"] == "retell_call":
        from ..retell import models as rm
        from ..retell import service as retell

        control.check_revisions(db, plan["revisions"])
        return retell.prepare(
            db,
            {"id": request_id or uuid4(), "revisions": plan["revisions"]},
            rm.Execute.model_validate(plan["args"]),
            admin,
            True,
        )
    return plan


def activate(db, record_id, data, admin):
    from .worker import available

    if not available():
        raise HTTPException(503, "workflow_worker_unavailable")
    if not data.consent_confirmed:
        raise HTTPException(422, "workflow_consent_required")
    control.lock(db)
    row = run_row(db, record_id, True)
    if row["status"] != "prepared":
        raise HTTPException(409, "workflow_already_activated")
    if row["review_expires_at"] <= now():
        raise HTTPException(410, "workflow_review_expired")
    if row["prepared_by"] != admin["id"] or not hmac.compare_digest(
        data.fingerprint, row["fingerprint"]
    ):
        raise HTTPException(409, "workflow_review_changed")
    # A changed draft does not mutate a snapshot, but invalidates pending review.
    if definition(db, row["workflow_id"])["version"] != row["workflow_version"]:
        raise HTTPException(409, "workflow_definition_changed")
    check_snapshot(db, row, admin)
    if row["review_expires_at"] <= now():
        raise HTTPException(410, "workflow_review_expired")
    current_admin = db.execute(
        "SELECT id FROM crm.users WHERE id=%s AND enabled AND role='admin'", (admin["id"],)
    ).fetchone()
    if not current_admin:
        raise HTTPException(403, "workflow_administrator_disabled")
    db.execute(
        "INSERT INTO crm.workflow_grants(run_id,actor_id,fingerprint,consent_confirmed,expires_at) VALUES (%s,%s,%s,true,now()+interval '30 days')",
        (record_id, admin["id"], row["fingerprint"]),
    )
    row = db.execute(
        "UPDATE crm.workflow_runs SET status='active',started_at=now(),version=version+1 WHERE id=%s RETURNING *",
        (record_id,),
    ).fetchone()
    event(
        db,
        record_id,
        "activated",
        "Administrador aprobó esta audiencia, contenido, conexiones y horario exactos.",
    )
    return run_view(db, row)


def authority(db, row):
    grant = db.execute(
        "SELECT g.*,u.username,u.enabled,u.role FROM crm.workflow_grants g JOIN crm.users u ON u.id=g.actor_id WHERE g.run_id=%s",
        (row["id"],),
    ).fetchone()
    if (
        not grant
        or grant["expires_at"] <= now()
        or not grant["enabled"]
        or grant["role"] != "admin"
        or grant["fingerprint"] != row["fingerprint"]
    ):
        raise HTTPException(409, "workflow_grant_invalid")
    return {"id": grant["actor_id"], "username": grant["username"], "role": grant["role"]}


def transition(db, record_id, action, data, admin):
    control.lock(db)
    row = run_row(db, record_id, True)
    if row["version"] != data.version:
        raise HTTPException(409, "record_changed")
    allowed = {
        "pause": {"active"},
        "resume": {"paused"},
        "stop": {"prepared", "active", "paused", "blocked", "unknown"},
    }
    if row["status"] not in allowed[action]:
        raise HTTPException(409, "workflow_transition_denied")
    if action == "resume":
        from .worker import available

        if not available():
            raise HTTPException(503, "workflow_worker_unavailable")
        actor = authority(db, row)
        check_snapshot(db, row, actor)
    target = {"pause": "paused", "resume": "active", "stop": "stopped"}[action]
    row = db.execute(
        "UPDATE crm.workflow_runs SET status=%s,version=version+1 WHERE id=%s RETURNING *",
        (target, record_id),
    ).fetchone()
    if action == "stop":
        db.execute(
            "UPDATE crm.workflow_recipients SET status='stopped' WHERE run_id=%s AND status='active'",
            (record_id,),
        )
    event(
        db,
        record_id,
        target,
        {
            "pause": "Secuencia pausada.",
            "resume": "Secuencia reanudada; las acciones inciertas no se repiten.",
            "stop": "Secuencia detenida. Una acción ya reservada podría haber salido.",
        }[action],
    )
    return run_view(db, row)


def runs(db):
    return {
        "runs": [
            run_view(db, row)
            for row in db.execute(
                "SELECT * FROM crm.workflow_runs ORDER BY created_at DESC,id LIMIT 100"
            ).fetchall()
        ]
    }


def detail(db, record_id):
    row = run_row(db, record_id)
    people = {p["id"]: p for p in row["snapshot"]["audience"]}
    recipients = []
    labels = {n["id"]: n["label"] for n in row["snapshot"]["document"]["nodes"]}
    for p in db.execute(
        "SELECT * FROM crm.workflow_recipients WHERE run_id=%s ORDER BY contact_id", (record_id,)
    ).fetchall():
        person = people[str(p["contact_id"])]
        recipients.append(
            {key: p[key] for key in ("contact_id", "status", "current_node_id", "due_at", "error")}
            | {key: person[key] for key in ("name", "phone")}
            | {"current_node_label": labels.get(p["current_node_id"])}
        )
    events = db.execute(
        "SELECT id,contact_id,node_id,kind,message,created_at FROM crm.workflow_events WHERE run_id=%s ORDER BY created_at DESC,id LIMIT 300",
        (record_id,),
    ).fetchall()
    return {"run": run_view(db, row), "recipients": recipients, "events": events}


def options(db, data, admin):
    if data.provider == "zernio":
        from ..social import workflow

        return workflow.options(db, data.account_id)
    from ..retell import inventory
    from ..retell import models as rm
    from ..retell import service as retell

    state = retell.require_state()
    agents = inventory.read(
        rm.AutomaticRead(endpoint="listAgents", revision=state["revision"], arguments={}), admin
    )["data"]
    numbers = inventory.read(
        rm.AutomaticRead(endpoint="listPhoneNumbers", revision=state["revision"], arguments={}),
        admin,
    )["data"]
    if not isinstance(agents, list) or not isinstance(numbers, list):
        raise HTTPException(503, "retell_options_unavailable")
    return {
        "available": True,
        "agents": [
            {"id": x["agent_id"], "name": x.get("agent_name", x["agent_id"])}
            for x in agents
            if isinstance(x, dict) and isinstance(x.get("agent_id"), str)
        ],
        "numbers": [
            {"number": x["phone_number"], "label": x.get("nickname", x["phone_number"])}
            for x in numbers
            if isinstance(x, dict) and isinstance(x.get("phone_number"), str)
        ],
    }


def catalog(db):
    from .worker import available, enabled

    prefs = {
        r["key"]: r["enabled"]
        for r in db.execute("SELECT key,enabled FROM crm.control_connections").fetchall()
    }
    from ..retell.service import state

    provider = state() if prefs.get("retell") else {}
    retell_ok = bool(
        prefs.get("retell")
        and provider.get("configured")
        and provider.get("verified")
        and provider.get("available")
    )
    from ..social import config

    try:
        config.required()
        social_ok = bool(prefs.get("zernio"))
    except HTTPException:
        social_ok = False
    nodes = []
    for kind, label in LABELS.items():
        okay = (
            retell_ok
            if kind == "retell_call"
            else social_ok
            if kind in {"social_message", "whatsapp_template"}
            else True
        )
        nodes.append(
            {
                "kind": kind,
                "label": label,
                "available": okay,
                **(
                    {"reason": "La conexión no está disponible; no se simulará un envío."}
                    if not okay
                    else {}
                ),
            }
        )
    return {
        "worker": {"enabled": enabled(), "available": available()},
        "nodes": nodes,
        "connections": [
            {"key": "zernio", "name": "Zernio", "available": social_ok},
            {"key": "retell", "name": "Retell AI", "available": retell_ok},
        ],
    }
