"""Reviewed Zernio inbox actions. Preparation never sends; engine owns reservations.

No OAuth substitution, arbitrary provider routes, raw vendor errors or automatic retries.
Only the private workflow engine may persist plans and call dispatch after reservation.
"""

import hashlib
import hmac
import http.client
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

from fastapi import HTTPException

from ..control.service import require_connections
from ..crm.database import connect
from . import config
from .transport import https_connection

MAX_RESPONSE = 1024 * 1024
MAX_REQUEST = 32 * 1024
PLATFORMS = frozenset({"facebook", "instagram", "whatsapp"})
KNOWN_PLATFORMS = PLATFORMS | {"telegram", "tiktok"}
META = PLATFORMS


def _fail(reason="zernio_workflow_unavailable"):
    raise HTTPException(409, reason)


def _identifier(value, maximum=512):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        _fail("zernio_invalid_identity")
    if value in {".", ".."} or any(ord(char) < 33 or ord(char) > 126 for char in value):
        _fail("zernio_invalid_identity")
    return value


def _text(value, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail("zernio_invalid_content")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        _fail("zernio_invalid_content")
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _cached(cache, credentials, key, fetch):
    """Optional one-prepare-request cache. Never passed by check or dispatch."""
    if cache is None:
        return fetch()
    key = (_digest(credentials), *key)
    if key not in cache:
        cache[key] = fetch()
    return cache[key]


def _phone(value):
    if not isinstance(value, str) or not re.fullmatch(r"\+?[1-9][0-9]{7,14}", value):
        _fail("zernio_recipient_phone_required")
    return value.lstrip("+")


def _time(value):
    if not isinstance(value, str) or len(value) > 48:
        _fail("zernio_window_unconfirmed")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except ValueError:
        _fail("zernio_window_unconfirmed")


def _route(operation, account_id=None, profile_id=None, conversation_id=None):
    """Construct only reviewed routes, encoding opaque IDs as one path segment."""
    if operation == "accounts":
        return "/v1/accounts?" + urlencode({"profileId": _identifier(profile_id), "limit": 100})
    account_id = _identifier(account_id, 160)
    if operation == "templates":
        return "/v1/whatsapp/templates?" + urlencode(
            {"accountId": account_id, "status": "APPROVED"}
        )
    if operation == "conversations":
        return "/v1/inbox/conversations?" + urlencode(
            {"profileId": _identifier(profile_id), "accountId": account_id, "limit": 100}
        )
    if operation == "open":
        return "/v1/inbox/conversations"
    if operation in {"messages", "reply"}:
        segment = quote(_identifier(conversation_id), safe="")
        path = "/v1/inbox/conversations/" + segment + "/messages"
        if operation == "messages":
            path += "?" + urlencode({"accountId": account_id, "sortOrder": "desc", "limit": 100})
        return path
    _fail()


def _request(
    credentials, operation, *, account_id=None, conversation_id=None, payload=None, request_id=None
):
    path = _route(operation, account_id, credentials["profile_id"], conversation_id)
    sending = operation in {"open", "reply"}
    if sending:
        expected = (
            {"accountId", "participantId", "templateName", "templateLanguage", "templateParams"}
            if operation == "open"
            else {"accountId", "message"}
        )
        if not isinstance(payload, dict) or set(payload) != expected:
            _fail()
        if payload["accountId"] != account_id:
            _fail()
        if operation == "reply":
            _text(payload["message"])
        else:
            _phone(payload["participantId"])
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,511}", payload["templateName"]):
                _fail("zernio_invalid_template")
            if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", payload["templateLanguage"]):
                _fail("zernio_invalid_template")
            params = payload["templateParams"]
            if not isinstance(params, list) or len(params) > 32:
                _fail("zernio_invalid_template")
            for value in params:
                _text(value, 1024)
    elif payload is not None or request_id is not None:
        _fail()
    body = _json(payload).encode() if sending else None
    if body and len(body) > MAX_REQUEST:
        _fail("zernio_invalid_content")
    connection = None
    try:
        connection = https_connection("zernio.com", timeout=4)
        headers = {
            "Authorization": "Bearer " + credentials["api_key"],
            "Accept": "application/json",
        }
        if sending:
            headers["Content-Type"] = "application/json"
            # Zernio documents this header for replies. It never authorizes retries.
            if operation == "reply":
                headers["Idempotency-Key"] = _identifier(request_id, 200)
        connection.request("POST" if sending else "GET", "/api" + path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if not 200 <= response.status < 300 or len(raw) > MAX_RESPONSE:
            raise ValueError
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise TypeError
        return result
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException, UnicodeError):
        # No status, redirect target, body, exception string or vendor error escapes.
        raise HTTPException(
            502, "zernio_submission_unknown" if sending else "zernio_workflow_unavailable"
        ) from None
    finally:
        if connection:
            connection.close()


def _list(data, key, limit=100):
    rows = data.get(key)
    if (
        not isinstance(rows, list)
        or len(rows) > limit
        or any(not isinstance(r, dict) for r in rows)
    ):
        _fail()
    return rows


def _accounts(credentials, cache=None):
    rows = _list(
        _cached(cache, credentials, ("accounts",), lambda: _request(credentials, "accounts")),
        "accounts",
    )
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row.get("platform"), str) or row["platform"] not in KNOWN_PLATFORMS:
            continue
        profile = row.get("profileId")
        profile = profile.get("_id", profile.get("id")) if isinstance(profile, dict) else profile
        if profile != credentials["profile_id"]:
            continue
        account_id = _identifier(row.get("_id"), 160)
        if account_id in seen:
            _fail("zernio_ambiguous_account")
        seen.add(account_id)
        result.append(row)
    return result


def _account(credentials, account_id, cache=None):
    rows = [row for row in _accounts(credentials, cache) if row.get("_id") == account_id]
    if len(rows) != 1:
        _fail("zernio_account_unavailable")
    account = rows[0]
    if account.get("isActive") is not True or account.get("needsReconnection") is True:
        _fail("zernio_account_unavailable")
    if account.get("platform") not in PLATFORMS:
        _fail(
            "zernio_tiktok_eligibility_unverified"
            if account.get("platform") == "tiktok"
            else "zernio_personal_channel_unsupported"
        )
    return account


def _takeover_consent(platform, settings):
    # A fresh ownership read cannot exclude a race. Meta automation must explicitly
    # disclose Zernio's documented automatic take+resend, never use HUMAN_AGENT.
    if (
        platform in {"facebook", "instagram"}
        and settings.get("allow_provider_takeover") is not True
    ):
        _fail("zernio_provider_takeover_consent_required")


def _conversations(credentials, account_id, complete=False, cache=None):
    data = _cached(
        cache,
        credentials,
        ("conversations", account_id),
        lambda: _request(credentials, "conversations", account_id=account_id),
    )
    meta = data.get("meta", {})
    if not isinstance(meta, dict) or meta.get("accountsFailed") or meta.get("failedAccounts"):
        _fail("zernio_conversations_unavailable")
    if meta.get("accountsSkipped"):
        _fail("zernio_conversations_unavailable")
    pagination = data.get("pagination")
    if not isinstance(pagination, dict):
        _fail("zernio_conversations_unavailable")
    if complete and (pagination.get("hasMore") is not False or pagination.get("nextCursor")):
        _fail("zernio_conversations_incomplete")
    rows = _list(data, "data")
    seen = set()
    for row in rows:
        if row.get("accountId") != account_id:
            _fail("zernio_conversation_account_mismatch")
        if not isinstance(row.get("platform"), str) or row["platform"] not in KNOWN_PLATFORMS:
            _fail("zernio_conversations_unavailable")
        value = _identifier(row.get("id"))
        _identifier(row.get("participantId"))
        if value in seen:
            _fail("zernio_ambiguous_conversation")
        seen.add(value)
    return rows


def _control(conversation):
    metadata = conversation.get("metadata")
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, dict) or metadata.get("standby"):
        _fail("zernio_thread_control_unconfirmed")
    if conversation.get("platform") in META and conversation.get("threadControl") != "app":
        _fail("zernio_thread_control_unconfirmed")


def _conversation_revision(conversation):
    return _digest(
        {
            key: conversation.get(key)
            for key in (
                "id",
                "accountId",
                "platform",
                "participantId",
                "businessScopedUserId",
                "threadControl",
            )
        }
    )


def _window(credentials, conversation):
    """Never mistake an outgoing message/updatedTime for the customer-service window."""
    data = _request(
        credentials,
        "messages",
        account_id=conversation["accountId"],
        conversation_id=conversation["id"],
    )
    now = datetime.now(UTC)
    allowed_senders = {conversation["participantId"]}
    if conversation.get("businessScopedUserId"):
        allowed_senders.add(_identifier(conversation["businessScopedUserId"]))
    for message in _list(data, "messages"):
        if (
            message.get("conversationId") == conversation["id"]
            and message.get("accountId") == conversation["accountId"]
            and message.get("platform") == conversation["platform"]
            and message.get("direction") == "incoming"
            and message.get("senderId") in allowed_senders
            and message.get("isDeleted") is not True
        ):
            metadata = message.get("metadata")
            metadata = {} if metadata is None else metadata
            if not isinstance(metadata, dict) or metadata.get("standby"):
                continue
            sent_at = _time(message.get("createdAt"))
            if now - timedelta(hours=24) < sent_at <= now:
                return
    _fail("zernio_window_unconfirmed")


def _template_info(template):
    if template.get("status") != "APPROVED":
        _fail("zernio_template_not_approved")
    _identifier(template.get("id"), 160)
    name, language = template.get("name"), template.get("language")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,511}", name):
        _fail("zernio_invalid_template")
    if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", language):
        _fail("zernio_invalid_template")
    components = _list(template, "components", 10)
    count, body, seen = 0, "", set()
    parameter_format = template.get("parameter_format", "POSITIONAL")
    if not isinstance(parameter_format, str) or parameter_format.upper() != "POSITIONAL":
        _fail("zernio_template_shape_unsupported")
    for component in components:
        kind = component.get("type")
        kind = kind.upper() if isinstance(kind, str) else ""
        if kind not in {"HEADER", "BODY", "FOOTER"} or kind in seen:
            _fail("zernio_template_shape_unsupported")
        seen.add(kind)
        header_format = component.get("format", "TEXT")
        if kind == "HEADER" and (
            not isinstance(header_format, str) or header_format.upper() != "TEXT"
        ):
            _fail("zernio_template_shape_unsupported")
        text = _text(component.get("text"), 10000)
        placeholders = re.findall(r"\{\{([^{}]+)\}\}", text)
        numbers = sorted(set(placeholders), key=lambda v: int(v) if v.isdigit() else -1)
        if numbers != [str(i + 1) for i in range(len(numbers))]:
            _fail("zernio_template_shape_unsupported")
        if "{{" in re.sub(r"\{\{[0-9]+\}\}", "", text) or (kind == "FOOTER" and numbers):
            _fail("zernio_template_shape_unsupported")
        count += len(numbers)
        if kind == "BODY":
            body = text
    if "BODY" not in seen or count > 32:
        _fail("zernio_template_shape_unsupported")
    return {
        "name": name,
        "language": language,
        "status": "APPROVED",
        "parameter_count": count,
        "body": body,
    }


def _templates(credentials, account_id, cache=None):
    data = _cached(
        cache,
        credentials,
        ("templates", account_id),
        lambda: _request(credentials, "templates", account_id=account_id),
    )
    if data.get("success") is not True:
        _fail("zernio_templates_unavailable")
    return _list(data, "templates")


def _render(value, contact, maximum=4000):
    value = _text(value, maximum)
    value = value.replace("{{nombre}}", _text(contact.get("name"), 160))
    value = value.replace("{{celular}}", _text(contact.get("phone"), 32))
    if "{{" in value or "}}" in value:
        _fail("zernio_invalid_placeholder")
    return _text(value, maximum)


def _seal(plan, credentials):
    return hmac.new(
        credentials["api_key"].encode(), _json(plan).encode(), hashlib.sha256
    ).hexdigest()


def prepare(db, node, contact, binding=None, cache=None):
    """Freeze review identities/content using bounded GETs and existing private config."""
    credentials = config.required()
    if not isinstance(node, dict) or not isinstance(contact, dict):
        _fail("zernio_plan_invalid")
    settings = node.get("settings", {})
    if not isinstance(settings, dict) or not contact.get("id"):
        _fail("zernio_plan_invalid")
    if isinstance(binding, dict) and (
        binding.get("contact_id") is not None and str(binding["contact_id"]) != str(contact["id"])
    ):
        _fail("zernio_recipient_mismatch")
    account_id = _identifier(settings.get("account_id"), 160)
    account = _account(credentials, account_id, cache)
    platform, kind = account["platform"], node.get("kind")
    _takeover_consent(platform, settings)
    require_connections(db, "zernio", platform)
    plan = {
        "kind": kind,
        "profile_id": credentials["profile_id"],
        "account_id": account_id,
        "platform": platform,
        "contact_id": str(contact["id"]),
        "credential_revision": _digest(credentials),
        "account_revision": _digest(account),
        "conversation_id": None,
        "conversation_revision": None,
        "template_revision": None,
    }
    summary = {"account_id": account_id, "platform": platform}
    if platform in {"facebook", "instagram"}:
        plan["allow_provider_takeover"] = True
    if kind == "whatsapp_template":
        if platform != "whatsapp":
            _fail("zernio_template_account_mismatch")
        participant = _phone(contact.get("phone"))
        templates = [
            t
            for t in _templates(credentials, account_id, cache)
            if t.get("name") == settings.get("template_name")
            and t.get("language") == settings.get("language")
        ]
        if len(templates) != 1:
            _fail("zernio_template_not_approved")
        template = templates[0]
        info = _template_info(template)
        parameters = settings.get("parameters")
        if not isinstance(parameters, list) or len(parameters) != info["parameter_count"]:
            _fail("zernio_template_parameters_mismatch")
        parameters = [_render(v, contact, 1024) for v in parameters]
        conversations = _conversations(credentials, account_id, complete=True, cache=cache)
        matches = [c for c in conversations if c["participantId"] == participant]
        if len(matches) > 1:
            _fail("zernio_ambiguous_conversation")
        if matches:
            conversation = matches[0]
            if conversation.get("platform") != platform:
                _fail("zernio_conversation_account_mismatch")
            _control(conversation)
            plan.update(
                conversation_id=conversation["id"],
                conversation_revision=_conversation_revision(conversation),
            )
        plan["template_revision"] = _digest(template)
        plan["payload"] = {
            "accountId": account_id,
            "participantId": participant,
            "templateName": info["name"],
            "templateLanguage": info["language"],
            "templateParams": parameters,
        }
        summary.update(
            description="Plantilla aprobada de WhatsApp; aceptación no confirma entrega.",
            template_name=info["name"],
            language=info["language"],
            parameters=parameters,
            template_body=info["body"],
            template_components=[
                {"type": c["type"], "text": c["text"]} for c in template["components"]
            ],
        )
    elif kind == "social_message":
        if settings.get("platform") != platform:
            _fail("zernio_conversation_account_mismatch")
        if not isinstance(binding, dict) or binding.get("account_id") != account_id:
            _fail("zernio_exact_conversation_required")
        conversation_id = _identifier(binding.get("conversation_id"))
        rows = [
            c
            for c in _conversations(credentials, account_id, cache=cache)
            if c["id"] == conversation_id and c.get("platform") == platform
        ]
        if len(rows) != 1:
            _fail("zernio_exact_conversation_required")
        conversation = rows[0]
        _control(conversation)
        _window(credentials, conversation)
        participant = conversation["participantId"]
        if platform == "whatsapp" and participant != _phone(contact.get("phone")):
            _fail("zernio_recipient_mismatch")
        text = _render(settings.get("text"), contact)
        plan.update(
            conversation_id=conversation_id,
            conversation_revision=_conversation_revision(conversation),
            payload={"accountId": account_id, "message": text},
        )
        summary.update(
            description="Respuesta a la conversación seleccionada; no confirma entrega.",
            conversation_id=conversation_id,
            text=text,
        )
        if platform in {"facebook", "instagram"}:
            summary["description"] += (
                " Autorización explícita: Zernio puede recuperar el control de esta"
                " conversación y reenviar una vez si Meta cambia su propietario."
                " Solo ventana de 24 horas; nunca HUMAN_AGENT automatizado."
            )
    else:
        _fail("zernio_unsupported_workflow_action")
    plan["participant_id"] = participant
    plan["summary"] = {**summary, "recipient": participant}
    # Only frozen rendered content + identity metadata; never provider keys/raw bodies.
    plan["seal"] = _seal(plan, credentials)
    return plan


def _check(plan, credentials):
    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("seal"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", plan["seal"])
    ):
        _fail("zernio_plan_invalid")
    unsigned = {k: v for k, v in plan.items() if k != "seal"}
    if not hmac.compare_digest(plan["seal"], _seal(unsigned, credentials)):
        _fail("zernio_plan_changed")
    if _digest(credentials) != plan["credential_revision"]:
        _fail("zernio_connection_changed")
    _takeover_consent(plan["platform"], plan)
    account = _account(credentials, plan["account_id"])
    if _digest(account) != plan["account_revision"]:
        _fail("zernio_account_changed")
    with connect() as db:
        require_connections(db, "zernio", plan["platform"])
    conversations = _conversations(
        credentials, plan["account_id"], complete=plan["kind"] == "whatsapp_template"
    )
    if plan["conversation_id"]:
        matches = [c for c in conversations if c["id"] == plan["conversation_id"]]
        if len(matches) != 1 or _conversation_revision(matches[0]) != plan["conversation_revision"]:
            _fail("zernio_conversation_changed")
        _control(matches[0])
        if plan["kind"] == "social_message":
            _window(credentials, matches[0])
    elif any(c["participantId"] == plan["participant_id"] for c in conversations):
        # A thread appeared after approval; do not implicitly take its ownership.
        _fail("zernio_conversation_changed")
    if plan["kind"] == "whatsapp_template":
        payload = plan["payload"]
        matches = [
            t
            for t in _templates(credentials, plan["account_id"])
            if t.get("name") == payload["templateName"]
            and t.get("language") == payload["templateLanguage"]
        ]
        if len(matches) != 1 or _digest(matches[0]) != plan["template_revision"]:
            _fail("zernio_template_changed")
        _template_info(matches[0])


def check(plan):
    """Revalidate current identity, connection preferences, template/window/control."""
    _check(plan, config.required())


def dispatch(plan, request_id):
    """Exactly one attempt after caller's committed reservation; NEVER retry unknown."""
    _identifier(request_id, 200)
    with config.locked():
        credentials = config.required()
        _check(plan, credentials)
        try:
            result = _request(
                credentials,
                "open" if plan["kind"] == "whatsapp_template" else "reply",
                account_id=plan["account_id"],
                conversation_id=plan["conversation_id"],
                payload=plan["payload"],
                request_id=request_id,
            )
            data = result.get("data")
            if result.get("success") is not True or not isinstance(data, dict):
                _fail()
            message_id = _identifier(data.get("messageId"))
            receipt = {"status": "accepted", "message_id": message_id}
            if data.get("conversationId") is not None:
                receipt["conversation_id"] = _identifier(data["conversationId"])
            # This is provider acceptance, not delivery/read/sale. Vendor bodies stay private.
            return {"state": "completed", "receipt": receipt}
        except HTTPException:
            return {"state": "unknown", "receipt": {}, "error": "zernio_submission_unknown"}


def options(db, account_id=None):
    result = {"available": False, "accounts": [], "templates": [], "conversations": []}
    try:
        credentials = config.required()
        require_connections(db, "zernio")
        accounts = _accounts(credentials)
        for account in accounts:
            platform = account.get("platform")
            available = (
                platform in PLATFORMS
                and account.get("isActive") is True
                and account.get("needsReconnection") is not True
            )
            reason = (
                None
                if available
                else (
                    "zernio_tiktok_eligibility_unverified"
                    if platform == "tiktok"
                    else "zernio_personal_channel_unsupported"
                    if platform == "telegram"
                    else "zernio_account_unavailable"
                )
            )
            if available:
                try:
                    require_connections(db, platform)
                except HTTPException:
                    available, reason = False, "connection_disabled"
            row = {
                "id": account["_id"],
                "platform": platform,
                "name": str(account.get("displayName") or account.get("username") or platform)[
                    :160
                ],
                "available": available,
            }
            if reason:
                row["reason"] = reason
            result["accounts"].append(row)
        result["available"] = any(a["available"] for a in result["accounts"])
        if account_id is None:
            if not result["available"]:
                result["reason"] = "zernio_no_supported_accounts"
            return result
        account = _account(credentials, _identifier(account_id, 160))
        require_connections(db, account["platform"])
        if account["platform"] == "whatsapp":
            for template in _templates(credentials, account_id):
                try:
                    result["templates"].append(_template_info(template))
                except HTTPException:
                    continue
        for conversation in _conversations(credentials, account_id):
            if conversation.get("platform") != account["platform"]:
                continue
            name = conversation.get("participantName")
            row = {
                "id": conversation["id"],
                "account_id": account_id,
                "platform": conversation["platform"],
                "participant_id": conversation["participantId"],
                "label": (
                    name if isinstance(name, str) and name else conversation["participantId"]
                )[:160],
                "can_reply": False,
            }
            if isinstance(name, str):
                row["participant_name"] = name[:160]
            if conversation["platform"] == "whatsapp":
                try:
                    row["phone"] = "+" + _phone(conversation["participantId"])
                except HTTPException:
                    pass
            try:
                _control(conversation)
                # Avoid up to 100 serial upstream window probes in the options UI.
                # Preparation independently confirms a current incoming message.
                row["reason"] = "zernio_window_verification_required"
            except HTTPException as error:
                row["reason"] = error.detail
            result["conversations"].append(row)
        return result
    except HTTPException as error:
        result.update(available=False, reason=error.detail)
        return result


def normalize_event(payload):
    """Parser ONLY. Caller must first authenticate HMAC, dedupe and verify ownership."""
    if (
        not isinstance(payload, dict)
        or payload.get("test") is not None
        or payload.get("event") != "message.received"
    ):
        return None
    try:
        metadata = payload.get("metadata")
        metadata = {} if metadata is None else metadata
        if not isinstance(metadata, dict) or metadata.get("standby"):
            return None
        message, account, conversation = (
            payload["message"],
            payload["account"],
            payload["conversation"],
        )
        if any(not isinstance(v, dict) for v in (message, account, conversation)):
            return None
        if message.get("platform") not in PLATFORMS or message.get("direction") != "incoming":
            return None
        if account.get("platform") != message["platform"]:
            return None
        account_id = _identifier(account.get("accountId", account.get("id")), 160)
        if account.get("id") is not None and account["id"] != account_id:
            return None
        if conversation.get("id") != message.get("conversationId") or (
            conversation.get("platform") is not None
            and conversation["platform"] != message["platform"]
        ):
            return None
        sender = message["sender"]
        if not isinstance(sender, dict):
            return None
        participant = _identifier(conversation.get("participantId"))
        sender_ids = {sender.get("id"), sender.get("businessScopedUserId")}
        if sender.get("phoneNumber") is not None:
            sender_ids.add(_phone(sender["phoneNumber"]))
        if participant not in sender_ids:
            return None
        sent_at = _time(message.get("sentAt"))
        return {
            "event_id": _identifier(payload.get("id"), 200),
            "event": "message.received",
            "profile_id": _identifier(account.get("profileId"), 160),
            "account_id": account_id,
            "platform": message["platform"],
            "conversation_id": _identifier(conversation.get("platformConversationId")),
            "participant_id": participant,
            "message_id": _identifier(message.get("platformMessageId")),
            "sent_at": sent_at.isoformat(),
        }
    except (HTTPException, KeyError, TypeError, ValueError):
        return None
