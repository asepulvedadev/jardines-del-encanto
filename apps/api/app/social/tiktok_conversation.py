"""Public, text-only Sara generation inside the existing TikTok delivery owner.

Generation has no CRM/admin tools. Identity and delivery remain application-owned.
Never generate inside the isolated sender or fall back to canned replies.
"""

import json
import re

from psycopg.types.json import Jsonb

from ..hermes import bridge
from ..sara import profile
from . import workflow


class GenerationUnavailable(Exception):
    """No send was reserved; wait for another incoming turn, without canned fallback."""


def draft(db, row, phase):
    saved = db.execute(
        "SELECT tiktok_replies FROM crm.social_onboarding_inputs WHERE onboarding_id=%s AND message_id=%s",
        (row["id"], row["source"]["message_id"]),
    ).fetchone()
    value = (saved["tiktok_replies"] or {}).get(phase) if saved else None
    if (
        not isinstance(value, dict)
        or value.get("message_id") != row["source"]["message_id"]
        or value.get("phase") != phase
        or value.get("profile_version") != profile.get(db)["version"]
    ):
        raise ValueError("tiktok_sara_draft_changed")
    return workflow._text(value.get("text"), 1500)


def generate(db, row, phase):
    from . import onboarding

    published = profile.get(db)
    input_row = db.execute(
        "SELECT * FROM crm.social_onboarding_inputs WHERE onboarding_id=%s AND message_id=%s",
        (row["id"], row["source"]["message_id"]),
    ).fetchone()
    if not input_row:
        raise ValueError("tiktok_sara_input_missing")
    if phase in input_row["tiktok_replies"]:
        return draft(db, row, phase)
    cfg = onboarding.settings(db, "tiktok")
    # Server facts are bounded, explicit context, never model-authorized writes.
    facts = {
        "phase": phase,
        "registered": bool(row["contact_id"]),
        "identity_confirmed": row["identity_confirmed"],
        "identity": row["details"],
        "website_sent": row["website_receipt"].get("status") == "accepted",
        "group_sent": row["group_receipt"].get("status") == "accepted",
    }
    policy = (
        "Canal TikTok; solo texto, sin notas de voz ni herramientas. Responde como Sara, "
        "asistente virtual comercial, usando el conocimiento publicado. Contesta primero la "
        "pregunta del cliente; no repitas saludos, formularios ni preguntas ya resueltas. "
        "Máximo una pregunta breve. Estado verificado por la aplicación: "
        + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
        + ". Si falta identidad pide solo el dato pendiente de forma natural. Si hay nombre y "
        "celular sin confirmar pide confirmación; no afirmes haber registrado hasta registered=true. "
        "No confundas una pregunta o interés con un nombre. Tras registrarse conversa sin volver "
        "a pedir datos. En confirmation confirma el registro real; en website y group introduce "
        "brevemente el enlace correspondiente, que adjuntará la aplicación. En confirmation, "
        "website y group no repitas la respuesta anterior ni hagas preguntas; solo continúa "
        "ese paso. No escribas URLs, "
        "no anuncies audios ni envíos pendientes como hechos. No inventes información. "
    )
    instructions = (policy + profile.instructions(published))[:2000]
    prior = db.execute(
        """SELECT i.source,i.tiktok_replies FROM crm.social_onboarding_inputs i
        WHERE i.onboarding_id=%s AND (i.created_at,i.id)<(%s,%s)
        ORDER BY i.created_at DESC,i.id DESC LIMIT 3""",
        (row["id"], input_row["created_at"], input_row["id"]),
    ).fetchall()
    accepted = [
        (entry["source_message_id"], entry["phase"])
        for entry in db.execute(
            "SELECT source_message_id,phase FROM crm.tiktok_reply_reservations WHERE onboarding_id=%s AND message_id IS NOT NULL ORDER BY reserved_at,id",
            (row["id"],),
        ).fetchall()
    ]
    messages = []
    for previous in reversed(prior):
        source = previous["source"]
        messages.append({"role": "user", "content": source["text"][:2000]})
        for message_id, step in accepted:
            if message_id == source["message_id"] and step in previous["tiktok_replies"]:
                messages.append(
                    {
                        "role": "assistant",
                        "content": previous["tiktok_replies"][step]["text"][:2000],
                    }
                )
    # Include earlier accepted phases from the same turn, without duplicating the current user.
    for message_id, step in accepted:
        if message_id == row["source"]["message_id"] and step in input_row["tiktok_replies"]:
            messages.append(
                {"role": "assistant", "content": input_row["tiktok_replies"][step]["text"][:2000]}
            )
    messages = [*messages[-7:], {"role": "user", "content": row["source"]["text"][:2000]}]
    payload = bounded_payload(messages, instructions, published["knowledge"])
    db.commit()  # Do not hold row/control locks across model latency.
    try:
        result = bridge.request("/public-reply", payload, timeout=48)
        if (
            result.get("ok") is not True
            or type(result.get("tools")) is not int
            or result["tools"] != 0
        ):
            raise ValueError("tiktok_sara_public_only")
        text = workflow._text(result.get("response"), 1000)
        if re.search(
            r"https?://|www\.|chat\.whatsapp\.com|jardinesdelencanto\.site", text, re.IGNORECASE
        ):
            raise ValueError("tiktok_sara_unapproved_link")
    except Exception as error:
        raise GenerationUnavailable from error
    if phase in {"website", "group"}:
        text += "\n" + (onboarding.WEBSITE if phase == "website" else cfg["group_url"])
    workflow._text(text, 1500)
    # Recheck after latency. Final isolated send repeats config, consent, source,
    # quota and published-profile checks; no public model can bypass any guard.
    onboarding.guard(db, row)
    if profile.get(db)["version"] != published["version"]:
        raise ValueError("tiktok_sara_profile_changed")
    generated = {
        "phase": phase,
        "message_id": row["source"]["message_id"],
        "profile_version": published["version"],
        "text": text,
    }
    db.execute(
        """UPDATE crm.social_onboarding_inputs SET tiktok_replies=
        tiktok_replies || jsonb_build_object(%s::text,%s::jsonb)
        WHERE onboarding_id=%s AND message_id=%s""",
        (phase, Jsonb(generated), row["id"], row["source"]["message_id"]),
    )
    db.commit()
    return text


def bounded_payload(messages, instructions, knowledge):
    """Measure the exact escaped JSON serializer used by hermes.bridge.request."""
    payload = {"messages": list(messages), "instructions": instructions, "knowledge": knowledge}
    while len(json.dumps(payload).encode()) > 24000 and len(payload["messages"]) > 1:
        payload["messages"].pop(0)
    if len(json.dumps(payload).encode()) > 24000:
        # Fixed per-field wire budgets leave room for JSON structure even with
        # surrogate-pair emoji escaping. Keep the trusted policy's leading facts.
        def trim(value, budget):
            while len(json.dumps(value).encode()) > budget:
                value = value[: max(1, len(value) * 3 // 4)]
            return value

        payload["messages"] = [{"role": "user", "content": trim(messages[-1]["content"], 5000)}]
        payload["instructions"] = trim(instructions, 9000)
        payload["knowledge"] = trim(knowledge, 7000)
    return payload
