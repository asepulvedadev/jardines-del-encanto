"""Minimal social connection settings; publishing, messaging and AI actions stay disabled."""

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..crm import security
from ..crm.database import connect
from . import config, provider

router = APIRouter(prefix="/crm/social")
webhook_router = APIRouter(prefix="/integrations/zernio")
Admin = Annotated[dict, Depends(security.session)]
MAX_BODY = 256 * 1024
WEBHOOK_PATH = "/api/integrations/zernio/webhook"


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(min_length=8, max_length=2048)
    profile_id: str = Field(pattern=r"^[a-fA-F0-9]{24}$")
    replace: bool = False

    @field_validator("api_key")
    @classmethod
    def printable_key(cls, value):
        if not all(33 <= ord(char) <= 126 for char in value.get_secret_value()):
            raise ValueError("Invalid credential")
        return value


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: UUID


def settings(credentials=None):
    if credentials is None:
        try:
            credentials = config.load()
        except HTTPException as error:
            if error.detail != "zernio_not_configured":
                raise
    result = {
        "configured": bool(credentials),
        "profile": None,
        "last_sync": None,
        "connections": [],
        "events": [],
        "limitations": {
            "telegram": "Canales y grupos; no incluye mensajes privados al bot.",
            "tiktok": "Los mensajes directos dependen de elegibilidad y solo permiten respuestas.",
        },
        "webhook": {"configured": False, "path": WEBHOOK_PATH},
        "hermes": {"connected": False, "mode": "manual"},
        "sync_warning": None,
    }
    if not credentials:
        return result
    profile_id = credentials["profile_id"]
    result["profile"] = {"id": profile_id, "name": credentials["profile_name"]}
    # A local secret prepares receipt validation; it does not register a vendor subscription.
    result["webhook"]["configured"] = bool(credentials.get("webhook_registered", False))
    with connect() as db:
        state = db.execute(
            "SELECT last_sync, sync_warning FROM crm.social_state WHERE profile_id=%s",
            (profile_id,),
        ).fetchone()
        if state:
            result.update(state)
        result["connections"] = db.execute(
            """SELECT account_id AS id, platform, username, display_name, status, connected_at
               FROM crm.social_connections WHERE profile_id=%s
               ORDER BY observed_at DESC, account_id LIMIT 100""",
            (profile_id,),
        ).fetchall()
        result["events"] = db.execute(
            """SELECT event_id AS id, event, platform, received_at, status
               FROM crm.social_webhook_events WHERE profile_id=%s OR event='webhook.test'
               ORDER BY received_at DESC, event_id LIMIT 20""",
            (profile_id,),
        ).fetchall()
    return result


@router.get("/settings")
def get_settings(admin: Admin):
    return settings()


@router.post("/settings")
def update_settings(data: SettingsInput, admin: Admin):
    with config.locked():
        previous = config.load()
        if previous and not data.replace:
            raise HTTPException(409, "zernio_replacement_confirmation_required")
        profile_id = data.profile_id.lower()
        candidate = {"api_key": data.api_key.get_secret_value(), "profile_id": profile_id}
        response = provider.request(candidate, "GET", "/v1/profiles/" + profile_id)
        profile = response.get("profile")
        if not isinstance(profile, dict) or provider.identifier(profile) != profile_id:
            raise HTTPException(502, "zernio_profile_mismatch")
        name = provider.text(profile.get("name"))
        if not name:
            raise HTTPException(502, "zernio_invalid_profile")
        candidate.update(
            {
                "profile_name": name,
                "generation": config.new_secret(),
                "webhook_secret": previous["webhook_secret"] if previous else config.new_secret(),
                "webhook_registered": bool(
                    previous
                    and previous.get("webhook_registered", False)
                    and previous["profile_id"] == profile_id
                ),
            }
        )
        config.store(candidate)
    return settings(candidate)


def sync(credentials, db=None):
    """One bounded cursor page. Never infer disconnection from an incomplete page."""
    profile_id = credentials["profile_id"]
    query = urlencode({"profileId": profile_id, "limit": 100})
    response = provider.request(credentials, "GET", "/v1/accounts?" + query)
    rows = response.get("accounts")
    if not isinstance(rows, list):
        raise HTTPException(502, "zernio_invalid_accounts")
    pagination = response.get("pagination") or {}
    if not isinstance(pagination, dict):
        raise HTTPException(502, "zernio_invalid_accounts")
    truncated = (
        len(rows) > 100 or bool(pagination.get("nextCursor")) or bool(response.get("warning"))
    )
    warning = "account_list_truncated" if truncated else None
    selected = []
    for account in rows[:100]:
        if not isinstance(account, dict):
            raise HTTPException(502, "zernio_invalid_accounts")
        if provider.identifier(account.get("profileId")) != profile_id:
            warning = warning or "profile_mismatch_filtered"
            continue
        account_id = account.get("_id")
        platform = account.get("platform")
        if platform not in provider.PLATFORMS:
            continue
        if not isinstance(account_id, str) or not 1 <= len(account_id) <= 160:
            raise HTTPException(502, "zernio_invalid_accounts")
        connected = account.get("isActive") is True and account.get("needsReconnection") is not True
        selected.append(
            {
                "id": account_id,
                "platform": platform,
                "username": provider.text(account.get("username")),
                "display_name": provider.text(account.get("displayName")),
                "status": "connected" if connected else "disconnected",
            }
        )
    if db is None:
        with connect() as connection:
            persist_sync(connection, profile_id, selected, truncated or bool(warning), warning)
    else:
        persist_sync(db, profile_id, selected, truncated or bool(warning), warning)
    return selected


def persist_sync(db, profile_id, selected, truncated, warning):
    if not truncated:
        db.execute(
            "UPDATE crm.social_connections SET status='disconnected' WHERE profile_id=%s",
            (profile_id,),
        )
    for account in selected:
        db.execute(
            """INSERT INTO crm.social_connections
               (profile_id,account_id,platform,username,display_name,status)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT(profile_id,account_id) DO UPDATE SET
                 platform=EXCLUDED.platform, username=EXCLUDED.username,
                 display_name=EXCLUDED.display_name, status=EXCLUDED.status, observed_at=now()""",
            (
                profile_id,
                account["id"],
                account["platform"],
                account["username"],
                account["display_name"],
                account["status"],
            ),
        )
    db.execute(
        """INSERT INTO crm.social_state(profile_id,last_sync,sync_warning) VALUES (%s,now(),%s)
           ON CONFLICT(profile_id) DO UPDATE SET last_sync=now(), sync_warning=EXCLUDED.sync_warning""",
        (profile_id, warning),
    )


@router.post("/sync")
def sync_settings(data: EmptyInput, admin: Admin):
    with config.locked():
        credentials = config.required()
        sync(credentials)
    return settings(credentials)


def intent_binding(admin, credentials):
    return security.digest(admin["token_hash"] + ":" + credentials.get("generation", "legacy"))


@router.post("/connect/{platform}")
def start_connection(platform: str, data: EmptyInput, admin: Admin):
    if platform not in provider.PLATFORMS:
        raise HTTPException(404, "unsupported_platform")
    with config.locked():
        credentials = config.required()
        # Snapshot vendor state, not a potentially stale cache, before beginning consent.
        before = sync(credentials)
        intent_id = uuid4()
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        query = {"profileId": credentials["profile_id"]}
        if platform != "telegram":
            query["redirect_url"] = security.origin() + "/crm?social_intent=" + str(intent_id)
        response = provider.request(
            credentials, "GET", "/v1/connect/" + platform + "?" + urlencode(query)
        )
        auth_url, code, instructions = None, None, None
        if platform == "telegram":
            code = response.get("code")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9-]{4,160}", code):
                raise HTTPException(502, "zernio_invalid_connection")
            raw_instructions = response.get("instructions")
            if not isinstance(raw_instructions, list) or not all(
                isinstance(i, str) for i in raw_instructions
            ):
                raise HTTPException(502, "zernio_invalid_connection")
            instructions = "\n".join(raw_instructions[:10])[:4000]
            try:
                vendor_expiry = datetime.fromisoformat(response["expiresAt"])
                if vendor_expiry.tzinfo is None or vendor_expiry <= datetime.now(UTC):
                    raise ValueError
                expires_at = min(expires_at, vendor_expiry)
            except (KeyError, ValueError, TypeError, AttributeError):
                raise HTTPException(502, "zernio_invalid_connection") from None
        else:
            auth_url = provider.auth_url(response.get("authUrl"))
        with connect() as db:
            db.execute(
                """INSERT INTO crm.social_connection_intents
                   (id,actor_id,session_hash,profile_id,platform,before_ids,code,expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    intent_id,
                    admin["id"],
                    intent_binding(admin, credentials),
                    credentials["profile_id"],
                    platform,
                    Jsonb([a["id"] for a in before if a["platform"] == platform]),
                    code,
                    expires_at,
                ),
            )
        return {
            "intent_id": intent_id,
            "auth_url": auth_url,
            "code": code,
            "expires_at": expires_at,
            "instructions": instructions,
        }


@router.post("/complete")
def complete_connection(data: CompletionInput, admin: Admin):
    with config.locked():
        credentials = config.required()
        status = "pending"
        with connect() as db:
            intent = db.execute(
                """SELECT * FROM crm.social_connection_intents
                   WHERE id=%s AND actor_id=%s AND session_hash=%s AND profile_id=%s FOR UPDATE""",
                (
                    data.intent_id,
                    admin["id"],
                    intent_binding(admin, credentials),
                    credentials["profile_id"],
                ),
            ).fetchone()
            if not intent:
                raise HTTPException(404, "zernio_intent_not_found")
            if intent["state"] == "completed":
                status = "connected"
            elif intent["expires_at"] <= datetime.now(UTC):
                raise HTTPException(410, "zernio_intent_expired")
            else:
                telegram_id = None
                if intent["platform"] == "telegram":
                    response = provider.request(
                        credentials,
                        "PATCH",
                        "/v1/connect/telegram?" + urlencode({"code": intent["code"]}),
                    )
                    if response.get("status") == "expired":
                        raise HTTPException(410, "zernio_intent_expired")
                    if response.get("status") == "connected":
                        telegram_account = response.get("account")
                        if (
                            not isinstance(telegram_account, dict)
                            or telegram_account.get("platform") != "telegram"
                        ):
                            raise HTTPException(502, "zernio_invalid_connection")
                        telegram_id = provider.identifier(telegram_account)
                    elif response.get("status") != "pending":
                        raise HTTPException(502, "zernio_invalid_connection")
                accounts = sync(credentials, db)
                verified = any(
                    a["platform"] == intent["platform"]
                    and a["status"] == "connected"
                    and a["id"] not in intent["before_ids"]
                    and (intent["platform"] != "telegram" or a["id"] == telegram_id)
                    for a in accounts
                )
                if verified:
                    db.execute(
                        "UPDATE crm.social_connection_intents SET state='completed', completed_at=now() WHERE id=%s",
                        (intent["id"],),
                    )
                    status = "connected"
    return {"status": status, "settings": settings(credentials)}


def event_mapping(payload, credentials, event):
    if event == "webhook.test":
        return None, None
    account = payload.get("account")
    if not isinstance(account, dict):
        raise HTTPException(403, "zernio_event_scope_mismatch")
    profile = provider.identifier(account.get("profileId"))
    profiles = payload.get("profiles")
    if profile is None and isinstance(profiles, list):
        ids = [provider.identifier(p) for p in profiles if isinstance(p, dict)]
        if credentials["profile_id"] in ids:
            profile = credentials["profile_id"]
    platform = account.get("platform")
    if profile != credentials["profile_id"] or platform not in provider.PLATFORMS:
        raise HTTPException(403, "zernio_event_scope_mismatch")
    return profile, platform


@webhook_router.post("/webhook")
async def webhook(request: Request):
    credentials = config.required()
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > MAX_BODY:
            raise HTTPException(413, "zernio_event_too_large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    signature = request.headers.get("x-zernio-signature", "")
    expected = hmac.new(credentials["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest()
    if not re.fullmatch(r"[a-fA-F0-9]{64}", signature) or not hmac.compare_digest(
        expected, signature.lower()
    ):
        raise HTTPException(401, "zernio_invalid_signature")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "zernio_invalid_event") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "zernio_invalid_event")
    event_id, event = payload.get("id"), payload.get("event")
    if (
        not isinstance(event_id, str)
        or not 1 <= len(event_id) <= 200
        or not isinstance(event, str)
        or not 1 <= len(event) <= 120
        or request.headers.get("x-zernio-event-id") != event_id
        or request.headers.get("x-zernio-event") != event
    ):
        raise HTTPException(400, "zernio_event_header_mismatch")
    profile, platform = event_mapping(payload, credentials, event)
    body_hash = hashlib.sha256(raw).hexdigest()
    with connect() as db:
        record = db.execute(
            """INSERT INTO crm.social_webhook_events(event_id,event,profile_id,platform,body,body_hash)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING RETURNING event_id""",
            (event_id, event, profile, platform, Jsonb(payload), body_hash),
        ).fetchone()
        if not record:
            previous = db.execute(
                "SELECT body_hash FROM crm.social_webhook_events WHERE event_id=%s", (event_id,)
            ).fetchone()
            if not previous or not hmac.compare_digest(previous["body_hash"], body_hash):
                raise HTTPException(409, "zernio_event_conflict")
    return {"status": "received"}
