"""Versioned shared Sara identity and knowledge with immutable runtime boundaries."""

import json

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control import service as control
from .profile_models import Profile, ProfileUpdate

DEFAULT = Profile(
    instructions="Atiende en español colombiano de forma clara, breve y amable. Usa el conocimiento aprobado del proyecto; confirma con un asesor la disponibilidad y las condiciones vigentes. No inventes datos ni afirmes haber realizado acciones sin un resultado confirmado.",
    knowledge="Jardines del Encanto es un proyecto de venta de lotes en Acacías, Meta. Información del propietario: lotes desde 13 millones COP, opción de 7 × 14 metros (98 m²) y financiación hasta 24 meses. El propietario informa: portería de lujo, oficina de administración, salón comunal, tres parques infantiles, cancha de fútbol 5 en grama especial, cancha multifuncional, cancha de voleibol, zona BBQ, piscina, sendero, zona de lectura, amplias jardinerías y kiosco social; vías de ocho metros embalastradas y vibrocompactadas con sardineles en concreto, servicios de agua y luz. Esta lista no certifica el estado actual de construcción ni las condiciones de entrega: se confirman con un asesor. Contacto comercial proporcionado por el propietario: +57 300 8348478.",
).model_dump()


def get(db):
    db.execute(
        "INSERT INTO crm.sara_profile(singleton,version,document) VALUES(true,1,%s) ON CONFLICT DO NOTHING",
        (Jsonb(DEFAULT),),
    )
    row = db.execute("SELECT * FROM crm.sara_profile WHERE singleton").fetchone()
    return {"version": row["version"], **row["document"], "updated_at": row["updated_at"]}


def update(db, args, admin):
    control.lock(db)
    old = get(db)
    if args.version != old["version"]:
        raise HTTPException(409, "record_changed")
    patch = args.model_dump(exclude_unset=True, exclude={"version"})
    if not patch or any(value is None for value in patch.values()):
        raise HTTPException(422, "invalid_input")
    try:
        document = Profile.model_validate(
            {**{k: v for k, v in old.items() if k in Profile.model_fields}, **patch}
        ).model_dump()
    except ValueError:
        raise HTTPException(422, "invalid_input") from None
    version = old["version"] + 1
    row = db.execute(
        "UPDATE crm.sara_profile SET version=%s,document=%s,updated_at=now() WHERE singleton AND version=%s RETURNING version",
        (version, Jsonb(document), old["version"]),
    ).fetchone()
    if not row:
        raise HTTPException(409, "record_changed")
    # The old bytes remain available for inspection or an explicit versioned restoration.
    db.execute(
        "INSERT INTO crm.sara_profile_versions(version,document,actor_id,source,author) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(version) DO NOTHING",
        (
            old["version"],
            Jsonb({k: old[k] for k in Profile.model_fields}),
            admin["id"],
            admin.get("channel", "web"),
            admin["username"],
        ),
    )
    db.execute(
        "INSERT INTO crm.sara_profile_versions(version,document,actor_id,source,author) VALUES(%s,%s,%s,%s,%s)",
        (version, Jsonb(document), admin["id"], admin.get("channel", "web"), admin["username"]),
    )
    current_job = (
        admin.get("developer_job_id") if admin.get("channel") == "whatsapp_developer" else None
    )
    # Final WhatsApp dispatch holds agent then control; never acquire agent after control here.
    db.execute(
        """UPDATE crm.whatsapp_agent_jobs SET state='blocked',error='shared_configuration_changed',finished_at=now()
        WHERE state IN ('pending','generating') AND (%s::uuid IS NULL OR id<>%s::uuid)""",
        (current_job, current_job),
    )
    if current_job:
        db.execute(
            "UPDATE crm.whatsapp_agent_jobs SET shared_profile_version=%s WHERE id=%s AND state='generating'",
            (version, current_job),
        )
    control.audit(db, admin, "sara.config.update", {"version": version, "fields": sorted(patch)})
    return get(db)


def learn(db, args, admin):
    control.lock(db)
    current = get(db)
    content = args.content.strip()
    if not content or args.version != current["version"]:
        raise HTTPException(409, "record_changed")
    knowledge = (current["knowledge"] + "\n" + content).strip()
    if len(knowledge) > 4000:
        raise HTTPException(409, "knowledge_limit")
    return update(db, ProfileUpdate(version=args.version, knowledge=knowledge), admin)


def instructions(document):
    style = {
        "brief": "Responde de forma breve.",
        "balanced": "Responde con detalle moderado.",
        "detailed": "Explica los detalles pertinentes sin inventar información.",
    }[document["response_style"]]
    return f"Nombre: {document['name']}. {document['instructions']} {style} Saludo: {document['greeting']}"[
        :2000
    ]


def context(db):
    data = get(db)
    return {
        "name": "Configuración publicada de Sara",
        "content": json.dumps(
            {k: data[k] for k in ("version", *Profile.model_fields)}, ensure_ascii=False
        ),
    }
