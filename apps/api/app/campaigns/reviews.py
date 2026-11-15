"""Explicit Meta review only; no delivery, scheduling, automatic retry or remote edit."""

import hashlib
import http.client
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..crm.database import connect
from ..social import config, workflow
from ..social.transport import https_connection
from . import models, service

STATUSES = frozenset(
    {"PENDING", "APPROVED", "REJECTED", "IN_APPEAL", "PAUSED", "DISABLED", "PENDING_DELETION"}
)
COLUMNS = "id, slug, version, account_id, account_label, name, snapshot, status, provider_id, category, created_at, checked_at"


def accounts(credentials):
    # Reuse the existing profile-scoped, bounded account discovery, not the sender.
    return [
        {
            "id": row["_id"],
            "label": str(row.get("displayName") or row.get("username") or row["_id"])[:160],
        }
        for row in workflow._accounts(credentials)
        if row.get("platform") == "whatsapp"
        and row.get("isActive") is True
        and row.get("needsReconnection") is not True
    ]


def selected_account(credentials, account_id):
    matches = [item for item in accounts(credentials) if item["id"] == account_id]
    if len(matches) != 1:
        raise HTTPException(422, "review_account_unavailable")
    return matches[0]


def request(credentials, method, path, payload=None):
    # Internal callers construct exactly the template collection endpoint only.
    if method not in {"GET", "POST"} or path.split("?")[0] != "/v1/whatsapp/templates":
        raise ValueError("Unsupported review operation")
    connection = None
    try:
        connection = https_connection("zernio.com", timeout=6)
        headers = {
            "Authorization": "Bearer " + credentials["api_key"],
            "Accept": "application/json",
        }
        body = None
        if method == "POST":
            body = json.dumps(payload, ensure_ascii=False).encode()
            if len(body) > 32768:
                raise ValueError
            headers["Content-Type"] = "application/json"
        connection.request(method, "/api" + path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if not 200 <= response.status < 300 or len(raw) > 1024 * 1024:
            raise ValueError
        if response.getheader("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("success") is not True:
            raise ValueError
        return result
    except (OSError, ValueError, TypeError, http.client.HTTPException, UnicodeError):
        raise HTTPException(502, "review_provider_unavailable") from None
    finally:
        if connection:
            connection.close()


def public_origin():
    origin = os.getenv("CAMPAIGN_MEDIA_ORIGIN", os.getenv("CRM_ORIGIN", "")).rstrip("/")
    if (
        not models.https_link(origin)
        or urlsplit(origin).path
        or urlsplit(origin).query
        or urlsplit(origin).fragment
    ):
        raise HTTPException(422, "review_public_media_origin_required")
    return origin


def payload(document, account_id, name, image_url=None):
    components = []
    if document.image_id:
        if not image_url:
            raise HTTPException(422, "review_public_media_origin_required")
        components.append(
            {"type": "header", "format": "image", "example": {"header_handle": [image_url]}}
        )
    body = {"type": "body", "text": document.body}
    keys = list(dict.fromkeys(models.TOKEN.findall(document.body)))
    variables = {item.key: item for item in document.variables}
    if keys:
        body["example"] = {
            "body_text_named_params": [
                {"param_name": key, "example": variables[key].example} for key in keys
            ]
        }
    components.append(body)
    kinds = [button.kind for button in document.buttons]
    if kinds.count("url") > 2 or sum(a != b for a, b in pairwise(kinds)) > 1:
        raise HTTPException(422, "review_button_groups_required")
    buttons = []
    for button in document.buttons:
        if button.kind == "reply":
            buttons.append({"type": "quick_reply", "text": button.label})
        else:
            match = models.TOKEN.fullmatch(button.value)
            if match:
                example = variables[match[1]].example
                parts = urlsplit(example)
                base = f"https://{parts.netloc}/"
                suffix = parts.path.removeprefix("/")
                if parts.query:
                    suffix += "?" + parts.query
                if parts.fragment:
                    suffix += "#" + parts.fragment
                # A root URL has an empty suffix; '?' is an equivalent nonempty URL sample.
                suffix = suffix or "?"
                buttons.append(
                    {
                        "type": "url",
                        "text": button.label,
                        "url": base + "{{1}}",
                        "example": [suffix],
                    }
                )
            else:
                buttons.append({"type": "url", "text": button.label, "url": button.value})
    if buttons:
        components.append({"type": "buttons", "buttons": buttons})
    return {
        "accountId": account_id,
        "name": name,
        "category": "MARKETING",
        "language": "es_CO",
        "parameter_format": "NAMED",
        "components": components,
    }


def snapshot(db, slug, version):
    row = db.execute(
        "SELECT document, version FROM crm.campaign_drafts WHERE slug=%s FOR SHARE", (slug,)
    ).fetchone()
    if not row or row["version"] != version:
        raise HTTPException(409, "review_save_current_version")
    return models.Document.model_validate(row["document"])


def template_name(credentials, slug, version, account_id):
    identity = json.dumps([credentials["profile_id"], slug, version, account_id])
    return f"jardines_{hashlib.sha256(identity.encode()).hexdigest()[:32]}_v{version}"


def preview(slug, data):
    credentials = config.required()
    account = selected_account(credentials, data.account_id)
    with connect() as db:
        document = snapshot(db, slug, data.version)
    name = template_name(credentials, slug, data.version, data.account_id)
    image_url = (
        public_origin() + "/api/crm/campaigns/review-media/sample" if document.image_id else None
    )
    content = payload(document, data.account_id, name, image_url)
    return {
        "name": name,
        "version": data.version,
        "account": account,
        "category": "MARKETING",
        "language": "es_CO",
        "components": content["components"],
    }


def history(slug):
    with connect() as db:
        rows = db.execute(
            f"SELECT {COLUMNS} FROM crm.campaign_reviews WHERE slug=%s ORDER BY created_at DESC,id DESC LIMIT 20",
            (slug,),
        ).fetchall()
    return {"items": rows}


def submit(slug, data, admin):
    credentials = config.required()
    account = selected_account(credentials, data.account_id)
    name = template_name(credentials, slug, data.version, data.account_id)
    identifier = uuid4()
    token = secrets.token_urlsafe(32)
    with connect() as db:
        document = snapshot(db, slug, data.version)
        origin = public_origin() if document.image_id else None
        image_url = (
            f"{origin}/api/crm/campaigns/review-media/{identifier}/{token}" if origin else None
        )
        content = payload(document, data.account_id, name, image_url)
        image_hash = (
            hashlib.sha256(
                (service.ROOT / "assets" / f"{document.image_id}.png").read_bytes()
            ).hexdigest()
            if document.image_id
            else None
        )
        row = db.execute(
            "INSERT INTO crm.campaign_reviews (id,slug,version,profile_id,account_id,account_label,name,snapshot,image_sha256,media_token_hash,media_expires_at,status,created_by) "
            f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'SUBMITTING',%s) ON CONFLICT DO NOTHING RETURNING {COLUMNS}",
            (
                identifier,
                slug,
                data.version,
                credentials["profile_id"],
                data.account_id,
                account["label"],
                name,
                Jsonb(document.model_dump(mode="json")),
                image_hash,
                hashlib.sha256(token.encode()).hexdigest() if origin else None,
                datetime.now(UTC) + timedelta(minutes=15) if origin else None,
                admin["id"],
            ),
        ).fetchone()
        if not row:
            raise HTTPException(409, "review_already_requested")
    # Reservation is committed BEFORE the single external mutation. Never retry it.
    status, provider_id, category = "UNKNOWN", None, None
    try:
        result = request(credentials, "POST", "/v1/whatsapp/templates", content)
        template = validated_template(result.get("template"), name)
        status, provider_id, category = template["status"], template["id"], template["category"]
    except HTTPException:
        pass
    with connect() as db:
        updated = db.execute(
            f"UPDATE crm.campaign_reviews SET status=%s,provider_id=%s,category=%s,checked_at=now() WHERE id=%s AND status='SUBMITTING' RETURNING {COLUMNS}",
            (status, provider_id, category, identifier),
        ).fetchone()
        return (
            updated
            or db.execute(
                f"SELECT {COLUMNS} FROM crm.campaign_reviews WHERE id=%s", (identifier,)
            ).fetchone()
        )


def validated_template(template, name, provider_id=None):
    if (
        not isinstance(template, dict)
        or template.get("name") != name
        or template.get("language") != "es_CO"
        or template.get("status") not in STATUSES
        or template.get("category") not in {"MARKETING", "UTILITY", "AUTHENTICATION"}
        or not isinstance(template.get("id"), str)
        or not 1 <= len(template["id"]) <= 160
        or (provider_id and template["id"] != provider_id)
    ):
        raise HTTPException(502, "review_provider_unavailable")
    return template


def refresh(slug, identifier):
    credentials = config.required()
    with connect() as db:
        row = db.execute(
            f"SELECT {COLUMNS},profile_id FROM crm.campaign_reviews WHERE slug=%s AND id=%s",
            (slug, identifier),
        ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    if row["profile_id"] != credentials["profile_id"]:
        raise HTTPException(409, "review_profile_changed")
    selected_account(credentials, row["account_id"])
    result = request(
        credentials,
        "GET",
        "/v1/whatsapp/templates?"
        + urlencode({"accountId": row["account_id"], "name": row["name"], "language": "es_CO"}),
    )
    templates = result.get("templates")
    if not isinstance(templates, list) or len(templates) > 100:
        raise HTTPException(502, "review_provider_unavailable")
    matches = [
        item
        for item in templates
        if isinstance(item, dict)
        and item.get("name") == row["name"]
        and item.get("language") == "es_CO"
    ]
    if len(matches) != 1:
        raise HTTPException(409, "review_not_found_at_provider")
    template = validated_template(matches[0], row["name"], row["provider_id"])
    with connect() as db:
        updated = db.execute(
            f"UPDATE crm.campaign_reviews SET status=%s,provider_id=%s,category=%s,checked_at=now() WHERE id=%s AND checked_at IS NOT DISTINCT FROM %s RETURNING {COLUMNS}",
            (
                template["status"],
                template["id"],
                template["category"],
                identifier,
                row["checked_at"],
            ),
        ).fetchone()
        return (
            updated
            or db.execute(
                f"SELECT {COLUMNS} FROM crm.campaign_reviews WHERE id=%s", (identifier,)
            ).fetchone()
        )


def media(identifier, token):
    if len(token) != 43 or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for char in token
    ):
        raise HTTPException(404, "not_found")
    with connect() as db:
        row = db.execute(
            "SELECT snapshot,image_sha256,media_token_hash FROM crm.campaign_reviews WHERE id=%s AND media_expires_at>now()",
            (identifier,),
        ).fetchone()
    if (
        not row
        or not row["media_token_hash"]
        or not secrets.compare_digest(
            row["media_token_hash"], hashlib.sha256(token.encode()).hexdigest()
        )
    ):
        raise HTTPException(404, "not_found")
    image_id = row["snapshot"].get("image_id")
    if image_id not in models.ASSETS:
        raise HTTPException(404, "not_found")
    raw = (service.ROOT / "assets" / f"{image_id}.png").read_bytes()
    if not secrets.compare_digest(hashlib.sha256(raw).hexdigest(), row["image_sha256"]):
        raise HTTPException(404, "not_found")
    return raw
