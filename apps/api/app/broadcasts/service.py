"""Atomic CRM import, immutable review and one-shot native Zernio broadcasts."""

import csv
import hashlib
import io
import ipaddress
import json
import re
from urllib.parse import urlparse

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..control.service import require_connections
from ..crm.database import connect
from ..crm.models import ContactInput
from ..crm.services import activity, capture_contact
from ..inbox.service import account, accounts
from ..social import config
from . import provider


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def credentials():
    with connect() as db:
        require_connections(db, "zernio", "whatsapp")
    return config.required()


def parse_csv(data):
    text = data.csv_text.lstrip("\ufeff")
    if len(text.encode()) > 512_000:
        raise HTTPException(413, "broadcast_csv_too_large")
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
        fields = reader.fieldnames or []
        if (
            len(fields) > 50
            or len(set(fields)) != len(fields)
            or data.name_column == data.phone_column
            or not {data.name_column, data.phone_column} <= set(fields)
        ):
            raise HTTPException(422, "broadcast_columns_invalid")
        recipients, invalid, seen, duplicates = [], [], set(), 0
        for row_no, row in enumerate(reader, 2):
            if row_no > 501:
                raise HTTPException(422, "broadcast_csv_limit")
            try:
                if None in row:
                    raise ValueError
                contact = ContactInput(
                    name=row[data.name_column], phone=row[data.phone_column], source="whatsapp"
                )
                if any(ord(c) < 32 for c in contact.name):
                    raise ValueError
            except (ValueError, TypeError):
                invalid.append({"row": row_no, "reason": "invalid_contact"})
                continue
            if contact.phone in seen:
                duplicates += 1
                continue
            seen.add(contact.phone)
            recipients.append({"name": contact.name, "phone": contact.phone})
    except (csv.Error, KeyError):
        raise HTTPException(422, "broadcast_csv_invalid") from None
    if not recipients:
        raise HTTPException(422, "broadcast_csv_empty")
    return {
        "recipients": recipients,
        "duplicates": duplicates,
        "invalid": invalid,
        "headers": fields,
    }


def template_schema(template):
    if template.get("status") != "APPROVED":
        raise HTTPException(409, "broadcast_template_unavailable")
    schema, text = [], ""
    for component in template.get("components", []):
        kind = str(component.get("type", "")).upper()
        if kind in {"BODY", "HEADER"}:
            content = component.get("text", "")
            if "{{" in content and re.sub(r"\{\{[1-9][0-9]*\}\}", "", content).find("{{") >= 0:
                raise HTTPException(422, "broadcast_template_unsupported")
            if kind == "BODY":
                text = content
            if kind == "HEADER" and component.get("format", "TEXT").upper() in {
                "IMAGE",
                "VIDEO",
                "DOCUMENT",
            }:
                schema.append(
                    {
                        "key": "header:media",
                        "label": "Archivo del encabezado (URL HTTPS)",
                        "kind": component["format"].lower(),
                    }
                )
            elif kind == "HEADER" and component.get("format", "TEXT").upper() != "TEXT":
                raise HTTPException(422, "broadcast_template_unsupported")
            positions = sorted({int(p) for p in re.findall(r"\{\{([1-9][0-9]*)\}\}", content)})
            if positions and positions != list(range(1, max(positions) + 1)):
                raise HTTPException(422, "broadcast_template_unsupported")
            for position in positions:
                schema.append(
                    {
                        "key": f"{kind.lower()}:{position}",
                        "label": f"{'Texto' if kind == 'BODY' else 'Encabezado'} {position}",
                        "kind": "text",
                    }
                )
        elif kind == "BUTTONS":
            for i, button in enumerate(component.get("buttons", [])):
                if button.get("type") == "URL" and "{{" in button.get("url", ""):
                    if button["url"].count("{{1}}") != 1 or "{{" in button["url"].replace(
                        "{{1}}", ""
                    ):
                        raise HTTPException(422, "broadcast_template_unsupported")
                    schema.append(
                        {
                            "key": f"button:{i}",
                            "label": f"Botón: {button.get('text', 'Enlace')}",
                            "kind": "text",
                        }
                    )
                elif button.get("type") not in {"URL", "PHONE_NUMBER", "QUICK_REPLY"}:
                    raise HTTPException(422, "broadcast_template_unsupported")
        elif kind != "FOOTER":
            raise HTTPException(422, "broadcast_template_unsupported")
    if len(schema) > 40:
        raise HTTPException(422, "broadcast_template_unsupported")
    return schema, text


def compile_template(template, values):
    schema, text = template_schema(template)
    if set(values) != {p["key"] for p in schema}:
        raise HTTPException(422, "broadcast_variables_invalid")
    for entry in schema:
        value = values[entry["key"]]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 1024
            or "{{" in value
            or any(ord(c) < 32 for c in value)
        ):
            raise HTTPException(422, "broadcast_variables_invalid")
        if entry["kind"] != "text":
            try:
                url = urlparse(value)
                host = (url.hostname or "").lower()
                invalid = (
                    url.scheme != "https"
                    or not host
                    or url.username
                    or url.password
                    or url.port not in (443, None)
                    or host == "localhost"
                    or host.endswith((".localhost", ".local", ".internal"))
                )
                try:
                    invalid = invalid or not ipaddress.ip_address(host).is_global
                except ValueError:
                    pass
                if invalid:
                    raise ValueError
            except ValueError:
                raise HTTPException(422, "broadcast_variables_invalid") from None
    components, mapping = [], {}
    for component in template.get("components", []):
        kind = str(component.get("type", "")).lower()
        entries = [e for e in schema if e["key"].startswith(kind + ":")]
        if kind == "body" and entries:
            for entry in entries:
                position = entry["key"].split(":")[1]
                mapping[position] = {"field": "custom", "customValue": values[entry["key"]]}
                text = text.replace("{{" + position + "}}", values[entry["key"]])
            components.append(
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "{{" + e["key"].split(":")[1] + "}}"}
                        for e in entries
                    ],
                }
            )
        elif kind == "header" and entries:
            params = []
            for entry in entries:
                typ = entry["kind"]
                value = values[entry["key"]]
                params.append(
                    {"type": "text", "text": value}
                    if typ == "text"
                    else {"type": typ, typ: {"link": value}}
                )
            components.append({"type": "header", "parameters": params})
        elif kind == "buttons":
            for entry in [e for e in schema if e["key"].startswith("button:")]:
                components.append(
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": entry["key"].split(":")[1],
                        "parameters": [{"type": "text", "text": values[entry["key"]]}],
                    }
                )
    payload = {"name": template["name"], "language": template["language"]}
    if components:
        payload["components"] = components
    if mapping:
        payload["variableMapping"] = mapping
    # The human confirmation includes visible header, footer and buttons, not body only.
    review = []
    for component in template.get("components", []):
        kind = str(component.get("type", "")).upper()
        if kind == "HEADER":
            if component.get("format", "TEXT").upper() == "TEXT":
                header = component.get("text", "")
                for e in schema:
                    if e["key"].startswith("header:"):
                        header = header.replace(
                            "{{" + e["key"].split(":")[1] + "}}", values[e["key"]]
                        )
                if header:
                    review.append(header)
            else:
                review.append(component.get("format", "") + ": " + values.get("header:media", ""))
        elif kind == "BODY":
            review.append(text)
        elif kind == "FOOTER" and component.get("text"):
            review.append(component["text"])
        elif kind == "BUTTONS":
            for i, button in enumerate(component.get("buttons", [])):
                target = button.get("url", button.get("phone_number", ""))
                target = target.replace("{{1}}", values.get(f"button:{i}", ""))
                review.append(button.get("text", "") + (": " + target if target else ""))
    return schema, payload, "\n\n".join(review)


def templates(creds, identifier):
    selected = account(creds, identifier)
    if selected["platform"] != "whatsapp":
        raise HTTPException(409, "broadcast_account_invalid")
    data = provider.request(
        creds, "GET", f"/v1/whatsapp/templates?accountId={identifier}&status=APPROVED"
    )
    rows = data.get("templates")
    if (
        not isinstance(rows, list)
        or len(rows) > 500
        or (data.get("pagination") or {}).get("hasMore")
    ):
        raise HTTPException(502, "broadcast_templates_incomplete")
    return [t for t in rows if isinstance(t, dict) and t.get("status") == "APPROVED"]


def catalog(identifier=None):
    creds = credentials()
    if identifier:
        items = []
        for t in templates(creds, identifier):
            try:
                fields, body = template_schema(t)
                issue = None
            except HTTPException:
                fields, body, issue = [], "", "broadcast_template_unsupported"
            items.append(
                {
                    "name": t.get("name"),
                    "language": t.get("language"),
                    "category": t.get("category"),
                    "body": body,
                    "fields": fields,
                    "issue": issue,
                }
            )
        return {"items": items}
    return {"accounts": [a for a in accounts(creds) if a["platform"] == "whatsapp" and a["active"]]}


PUBLIC_COLUMNS = "id,name,account_id,template_name,template_language,preview,state,provider_id,provider_status,last_error,stats,version,created_at,updated_at"


def listing(db):
    rows = db.execute(
        f"SELECT {PUBLIC_COLUMNS}, (SELECT count(*) FROM crm.whatsapp_broadcast_recipients r WHERE r.campaign_id=b.id) AS recipient_count FROM crm.whatsapp_broadcasts b ORDER BY created_at DESC,id LIMIT 100"
    ).fetchall()
    return {"items": rows}


def detail(db, identifier):
    row = db.execute(
        f"SELECT {PUBLIC_COLUMNS} FROM crm.whatsapp_broadcasts WHERE id=%s", (identifier,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    row["recipients"] = db.execute(
        "SELECT r.contact_id,r.name,r.phone,r.status, c.contact_id IS NOT NULL AS cold FROM crm.whatsapp_broadcast_recipients r LEFT JOIN crm.whatsapp_cold_leads c ON c.contact_id=r.contact_id WHERE r.campaign_id=%s ORDER BY r.name,r.contact_id",
        (identifier,),
    ).fetchall()
    row["recipient_count"] = len(row["recipients"])
    return row


def create(data, admin):
    parsed = parse_csv(data)
    # Never silently omit bad rows before a paid communication.
    if parsed["invalid"]:
        raise HTTPException(422, "broadcast_fix_invalid_rows")
    fingerprint = digest(data.model_dump())
    with connect() as db:
        existing = db.execute(
            "SELECT fingerprint,actor_id FROM crm.whatsapp_broadcasts WHERE id=%s", (data.id,)
        ).fetchone()
        if existing:
            if existing["fingerprint"] != fingerprint or str(existing["actor_id"]) != str(
                admin["id"]
            ):
                raise HTTPException(409, "broadcast_changed")
            return detail(db, data.id)
    creds = credentials()
    chosen = [
        t
        for t in templates(creds, data.account_id)
        if t.get("name") == data.template_name and t.get("language") == data.template_language
    ]
    if len(chosen) != 1:
        raise HTTPException(409, "broadcast_template_unavailable")
    _, payload, text = compile_template(chosen[0], data.values)
    with connect() as db:
        # The UUID is a caller-held idempotency key, serialized before any CRM write.
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,31))", (str(data.id),))
        existing = db.execute(
            "SELECT fingerprint,actor_id FROM crm.whatsapp_broadcasts WHERE id=%s", (data.id,)
        ).fetchone()
        if existing:
            if existing["fingerprint"] != fingerprint or str(existing["actor_id"]) != str(
                admin["id"]
            ):
                raise HTTPException(409, "broadcast_changed")
            return detail(db, data.id)
        db.execute(
            "INSERT INTO crm.whatsapp_broadcasts(id,actor_id,fingerprint,name,account_id,credential_revision,template_name,template_language,template_revision,template_payload,preview,consent_note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                data.id,
                admin["id"],
                fingerprint,
                data.name,
                data.account_id,
                digest([creds["profile_id"], creds["api_key"]]),
                data.template_name,
                data.template_language,
                digest(chosen[0]),
                Jsonb(payload),
                text,
                data.consent_note,
            ),
        )
        # Keep phone-lock acquisition consistent across overlapping imports.
        for entry in sorted(parsed["recipients"], key=lambda entry: entry["phone"]):
            # INSERT result, not a prior existence check, decides cold provenance under concurrency.
            new = db.execute(
                "INSERT INTO crm.contacts(name,phone,source) VALUES(%s,%s,'whatsapp') ON CONFLICT(phone) DO NOTHING RETURNING id",
                (entry["name"], entry["phone"]),
            ).fetchone()
            contact, deal = capture_contact(db, ContactInput(**entry, source="whatsapp"))
            if new:
                db.execute(
                    "INSERT INTO crm.whatsapp_cold_leads(contact_id,campaign_id) VALUES(%s,%s)",
                    (contact["id"], data.id),
                )
            db.execute(
                "INSERT INTO crm.whatsapp_broadcast_recipients(campaign_id,contact_id,name,phone) VALUES(%s,%s,%s,%s)",
                (data.id, contact["id"], entry["name"], entry["phone"]),
            )
            activity(
                db,
                deal["id"],
                admin["id"],
                "note",
                f"Incluido en campaña WhatsApp masivo: {data.name}. Importación CSV; aún no enviado.",
            )
        return detail(db, data.id)


def scoped_remote(creds, row):
    remote = provider.request(creds, "GET", f"/v1/broadcasts/{row['provider_id']}").get("broadcast")
    if (
        not isinstance(remote, dict)
        or remote.get("accountId") != row["account_id"]
        or remote.get("platform") != "whatsapp"
        or remote.get("profileId", creds["profile_id"]) != creds["profile_id"]
    ):
        raise HTTPException(502, "broadcast_scope_mismatch")
    return remote


def recipient_snapshot(creds, row, expected):
    result, seen = [], set()
    for skip in range(0, 500, 100):
        data = provider.request(
            creds, "GET", f"/v1/broadcasts/{row['provider_id']}/recipients?limit=100&skip={skip}"
        )
        rows = data.get("recipients")
        pagination = data.get("pagination")
        if not isinstance(rows, list) or len(rows) > 100 or not isinstance(pagination, dict):
            raise HTTPException(502, "broadcast_audience_invalid")
        for recipient in rows:
            try:
                phone = ContactInput.normalize_phone(recipient.get("platformIdentifier", ""))
            except (ValueError, TypeError, AttributeError):
                raise HTTPException(502, "broadcast_audience_invalid") from None
            if (
                recipient.get("isSubscribed") is False
                or recipient.get("isBlocked") is True
                or phone not in expected
                or phone in seen
                or recipient.get("status") not in {"pending", "sent", "delivered", "read", "failed"}
            ):
                raise HTTPException(502, "broadcast_audience_invalid")
            seen.add(phone)
            result.append({"phone": phone, "status": recipient["status"]})
        if pagination.get("hasMore") is False:
            if pagination.get("total") != len(result):
                raise HTTPException(502, "broadcast_audience_invalid")
            return result
        if pagination.get("hasMore") is not True or len(rows) != 100:
            break
    raise HTTPException(502, "broadcast_audience_invalid")


def send(identifier, data, admin):
    creds = credentials()
    with connect() as db:
        # Session-level lock survives explicit checkpoints and is released on connection close.
        if not db.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,32)) AS locked", (str(identifier),)
        ).fetchone()["locked"]:
            raise HTTPException(409, "broadcast_busy")
        row = db.execute(
            "SELECT * FROM crm.whatsapp_broadcasts WHERE id=%s FOR UPDATE", (identifier,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if row["state"] != "draft" or row["version"] != data.version:
            raise HTTPException(409, "broadcast_already_attempted")
        recipients = db.execute(
            "SELECT name,phone FROM crm.whatsapp_broadcast_recipients WHERE campaign_id=%s ORDER BY contact_id",
            (identifier,),
        ).fetchall()
        if len(recipients) != data.count:
            raise HTTPException(409, "broadcast_changed")
        if row["credential_revision"] != digest([creds["profile_id"], creds["api_key"]]):
            raise HTTPException(409, "broadcast_changed")
        chosen = [
            t
            for t in templates(creds, row["account_id"])
            if t.get("name") == row["template_name"]
            and t.get("language") == row["template_language"]
        ]
        if len(chosen) != 1 or digest(chosen[0]) != row["template_revision"]:
            raise HTTPException(409, "broadcast_changed")
        db.execute(
            "UPDATE crm.whatsapp_broadcasts SET state='preparing',attempted_at=now(),version=version+1,updated_at=now() WHERE id=%s",
            (identifier,),
        )
        db.commit()
        try:
            # Import never opts an existing Zernio contact back in. Unique campaign segment
            # plus isSubscribed excludes remote opt-outs rather than bypassing them by phone.
            tag = "crm-broadcast:" + str(identifier)
            imported = provider.request(
                creds,
                "POST",
                "/v1/contacts/bulk",
                {
                    "profileId": creds["profile_id"],
                    "accountId": row["account_id"],
                    "contacts": [
                        {"name": r["name"], "platformIdentifier": r["phone"], "tags": [tag]}
                        for r in recipients
                    ],
                },
            )
            if imported.get("errors") or imported.get("total") != len(recipients):
                raise HTTPException(409, "broadcast_import_incomplete")
            created = provider.request(
                creds,
                "POST",
                "/v1/broadcasts",
                {
                    "profileId": creds["profile_id"],
                    "accountId": row["account_id"],
                    "platform": "whatsapp",
                    "name": row["name"],
                    "template": row["template_payload"],
                    "segmentFilters": {"tags": [tag], "isSubscribed": True},
                },
            )
            remote = created.get("broadcast") or {}
            remote_id = remote.get("id")
            if not isinstance(remote_id, str) or not re.fullmatch(r"[a-f0-9]{24}", remote_id):
                raise HTTPException(502, "broadcast_unknown")
            db.execute(
                "UPDATE crm.whatsapp_broadcasts SET provider_id=%s WHERE id=%s",
                (remote_id, identifier),
            )
            db.commit()
            row["provider_id"] = remote_id
            scoped_remote(creds, row)
            added = provider.request(
                creds, "POST", f"/v1/broadcasts/{remote_id}/recipients", {"useSegment": True}
            )
            n = added.get("added")
            if type(n) is not int or n < 1 or n > len(recipients):
                raise HTTPException(409, "broadcast_audience_invalid")
            remote = scoped_remote(creds, row)
            if remote.get("status") != "draft" or remote.get("recipientCount") != n:
                raise HTTPException(409, "broadcast_audience_invalid")
            frozen = recipient_snapshot(creds, row, {r["phone"] for r in recipients})
            if len(frozen) != n or any(r["status"] != "pending" for r in frozen):
                raise HTTPException(409, "broadcast_audience_invalid")
            db.execute(
                "UPDATE crm.whatsapp_broadcasts SET state='sending',stats=%s,updated_at=now() WHERE id=%s",
                (Jsonb({"eligible": n, "excluded": len(recipients) - n}), identifier),
            )
            db.commit()
            provider.request(creds, "POST", f"/v1/broadcasts/{remote_id}/send", {})
            db.execute(
                "UPDATE crm.whatsapp_broadcasts SET state='submitted',provider_status='sending',updated_at=now() WHERE id=%s",
                (identifier,),
            )
            db.commit()
        except Exception as error:  # noqa: BLE001 - preserve unknown paid outcomes on any failure
            # Unknown outcomes never become a reusable draft, including process restarts.
            db.rollback()
            code = (
                error.detail
                if isinstance(error, HTTPException) and isinstance(error.detail, str)
                else "broadcast_unknown"
            )
            db.execute(
                "UPDATE crm.whatsapp_broadcasts SET state='unknown',last_error=%s,updated_at=now() WHERE id=%s",
                (code, identifier),
            )
            db.commit()
        return detail(db, identifier)


def refresh(identifier):
    creds = credentials()
    with connect() as db:
        if not db.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,32)) AS locked", (str(identifier),)
        ).fetchone()["locked"]:
            raise HTTPException(409, "broadcast_busy")
        row = db.execute(
            "SELECT * FROM crm.whatsapp_broadcasts WHERE id=%s", (identifier,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if row["state"] == "draft" or not row["provider_id"]:
            return detail(db, identifier)
        if row["credential_revision"] != digest([creds["profile_id"], creds["api_key"]]):
            raise HTTPException(409, "broadcast_changed")
        account(creds, row["account_id"])
        remote = scoped_remote(creds, row)
        snapshots = recipient_snapshot(
            creds, row, {r["phone"] for r in detail(db, identifier)["recipients"]}
        )
        for recipient in snapshots:
            db.execute(
                "UPDATE crm.whatsapp_broadcast_recipients SET status=%s WHERE campaign_id=%s AND phone=%s",
                (recipient["status"], identifier, recipient["phone"]),
            )
        stats = {
            k: remote.get(k)
            for k in ("recipientCount", "sentCount", "deliveredCount", "readCount", "failedCount")
            if type(remote.get(k)) is int and remote[k] >= 0
        }
        status = remote.get("status")
        state = {
            "sending": "submitted",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(status, row["state"])
        db.execute(
            "UPDATE crm.whatsapp_broadcasts SET provider_status=%s,stats=%s,state=%s,updated_at=now() WHERE id=%s",
            (
                status
                if status in {"draft", "sending", "scheduled", "completed", "failed", "cancelled"}
                else None,
                Jsonb(stats),
                state,
                identifier,
            ),
        )
        return detail(db, identifier)
