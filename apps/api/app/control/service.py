"""Durable registry and typed dispatch. No host-code or arbitrary network adapters."""

from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from ..crm import models as crm_models
from ..crm import services
from ..crm.database import connect
from . import models

ACTION_MODELS = {
    "crm.workspace": models.Workspace,
    "crm.activities": models.RecordID,
    "crm.contact.create": crm_models.ContactInput,
    "crm.contact.update": models.ContactUpdate,
    "crm.deal.update": models.DealUpdate,
    "crm.note.create": models.NoteCreate,
    "crm.task.create": crm_models.TaskInput,
    "crm.task.update": models.TaskUpdate,
    "control.catalog": models.Empty,
    "control.item.create": models.ItemCreate,
    "control.item.update": models.ItemActionUpdate,
    "control.connection.update": models.ConnectionActionUpdate,
    "social.status": models.Empty,
    "social.sync": models.Empty,
    "social.connect": models.SocialConnect,
}
READ_ACTIONS = {"crm.workspace", "crm.activities", "control.catalog", "social.status"}
SOCIAL_ACTIONS = {"social.sync", "social.connect"}
CONNECTION_NAMES = {
    "hermes": "Sara IA",
    "zernio": "Zernio",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
}


def lock(db):
    # Serializes registry changes with approval capability/revision checks.
    db.execute("SELECT pg_advisory_xact_lock(2026111105)")


def validate(action, arguments):
    if action not in ACTION_MODELS:
        raise HTTPException(422, "unsupported_action")
    try:
        return ACTION_MODELS[action].model_validate(arguments)
    except (ValidationError, TypeError, ValueError):
        raise HTTPException(422, "invalid_input") from None


def rows(db):
    return db.execute("SELECT * FROM crm.control_items ORDER BY created_at,id LIMIT 201").fetchall()


def definition_actions(item):
    definition = item["definition"]
    if item["kind"] == "tool":
        return [definition["action"]]
    if item["kind"] in ("plugin", "connection"):
        return definition["actions"]
    if item["kind"] == "script":
        return [step["action"] for step in definition["steps"]]
    return []


def supported(item):
    actions = definition_actions(item)
    if any(action not in ACTION_MODELS for action in actions):
        return False
    try:
        if item["kind"] == "script":
            for step in item["definition"]["steps"]:
                validate(step["action"], step["arguments"])
        if item["kind"] == "tool":
            model = ACTION_MODELS[item["definition"]["action"]]
            if set(item["definition"]["defaults"]) - set(model.model_fields):
                return False
            try:
                model.model_validate(item["definition"]["defaults"])
            except ValidationError as error:
                if any(entry["type"] != "missing" for entry in error.errors()):
                    return False
    except HTTPException:
        return False
    return True


def capability_enabled(db, action):
    override = db.execute(
        "SELECT enabled FROM crm.control_items WHERE kind='tool' AND definition->>'action'=%s",
        (action,),
    ).fetchone()
    return not override or override["enabled"]


def require_capability(db, action):
    if action not in ACTION_MODELS or not capability_enabled(db, action):
        raise HTTPException(409, "capability_disabled")


def require_connections(db, *keys):
    prefs = db.execute(
        "SELECT key,enabled FROM crm.control_connections WHERE key=ANY(%s)", (list(keys),)
    ).fetchall()
    if len(prefs) != len(set(keys)) or any(not pref["enabled"] for pref in prefs):
        raise HTTPException(409, "connection_disabled")


def require_social_enabled(*keys):
    with connect() as db:
        require_connections(db, "zernio", *keys)


def item_view(db, item):
    result = {key: value for key, value in item.items() if key != "actor_id"}
    result["effective"] = bool(
        item["enabled"]
        and supported(item)
        and all(capability_enabled(db, action) for action in definition_actions(item))
    )
    return result


def connection_views(db):
    from ..hermes.bridge import health
    from ..social.routes import settings

    bridge = health()
    try:
        state = settings()
    except HTTPException:
        state = {"configured": False, "oauth": {}, "connections": []}
    output = []
    preferences = db.execute("SELECT * FROM crm.control_connections ORDER BY key").fetchall()
    parent_enabled = next(row["enabled"] for row in preferences if row["key"] == "zernio")
    for pref in preferences:
        key = pref["key"]
        available = (
            bridge["available"]
            if key == "hermes"
            else bool(state["configured"] or state.get("oauth", {}).get("verified_at"))
            if key == "zernio"
            else any(
                row["platform"] == key and row["status"] == "connected"
                for row in state["connections"]
            )
        )
        desired = pref["enabled"] and (parent_enabled if key not in ("hermes", "zernio") else True)
        effective = bool(desired and available)
        output.append(
            {
                **pref,
                "name": CONNECTION_NAMES[key],
                "available": available,
                "effective": effective,
                "status": "connected" if effective else "paused" if not desired else "unavailable",
            }
        )
    return output


def catalog(db):
    return {
        "items": [item_view(db, item) for item in rows(db)],
        "capabilities": [
            {
                "key": action,
                "name": action,
                "description": action,
                "input_schema": model.model_json_schema(),
                "mutating": action not in READ_ACTIONS,
                "enabled": capability_enabled(db, action),
            }
            for action, model in ACTION_MODELS.items()
        ],
        "connections": connection_views(db),
    }


def audit(db, admin, action, arguments, proposal_id=None):
    db.execute(
        """INSERT INTO crm.control_audit(actor_id,action,arguments,proposal_id)
                  VALUES (%s,%s,%s,%s)""",
        (admin["id"], action, Jsonb(jsonable_encoder(arguments)), proposal_id),
    )


def create_item(db, data, admin):
    lock(db)
    if len(rows(db)) >= 200:
        raise HTTPException(409, "registry_limit")
    candidate = data.model_dump()
    if data.enabled and not supported(candidate):
        raise HTTPException(422, "unsupported_definition")
    result = db.execute(
        """INSERT INTO crm.control_items
        (actor_id,kind,name,description,definition,enabled) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (admin["id"], data.kind, data.name, data.description, Jsonb(data.definition), data.enabled),
    ).fetchone()
    audit(db, admin, "control.item.create", candidate)
    return item_view(db, result)


def update_item(db, item_id, data, admin):
    lock(db)
    old = db.execute(
        "SELECT * FROM crm.control_items WHERE id=%s FOR UPDATE", (item_id,)
    ).fetchone()
    if not old:
        raise HTTPException(404, "not_found")
    if old["version"] != data.version:
        raise HTTPException(409, "record_changed")
    payload = {key: old[key] for key in ("kind", "name", "description", "definition", "enabled")}
    payload.update(data.model_dump(exclude_unset=True, exclude={"version", "id"}))
    try:
        candidate = models.ItemCreate.model_validate(payload)
    except ValidationError:
        raise HTTPException(422, "invalid_input") from None
    if candidate.enabled and not supported(candidate.model_dump()):
        raise HTTPException(422, "unsupported_definition")
    result = db.execute(
        """UPDATE crm.control_items SET name=%s,description=%s,definition=%s,
        enabled=%s,version=version+1,updated_at=now() WHERE id=%s RETURNING *""",
        (
            candidate.name,
            candidate.description,
            Jsonb(candidate.definition),
            candidate.enabled,
            item_id,
        ),
    ).fetchone()
    audit(db, admin, "control.item.update", {"id": str(item_id), **data.model_dump(mode="json")})
    return item_view(db, result)


def update_connection(db, key, data, admin):
    lock(db)
    if key not in CONNECTION_NAMES:
        raise HTTPException(404, "not_found")
    if key == "hermes" and data.enabled:
        from ..hermes.bridge import health

        if not health()["available"]:
            raise HTTPException(503, "hermes_unavailable")
    pref = db.execute(
        """UPDATE crm.control_connections SET enabled=%s,version=version+1
        WHERE key=%s AND version=%s RETURNING *""",
        (data.enabled, key, data.version),
    ).fetchone()
    if not pref:
        raise HTTPException(409, "record_changed")
    audit(db, admin, "control.connection.update", {"key": key, **data.model_dump()})
    return next(row for row in connection_views(db) if row["key"] == key)


def execute(db, action, args, admin):
    """Invoked only for reads, direct human configuration, or consumed proposals."""
    if action == "crm.workspace":
        state = services.workspace(db, admin)
        query = args.query.casefold()
        matches = [
            row
            for row in state["contacts"]
            if not query
            or any(query in str(row.get(key, "")).casefold() for key in ("name", "phone", "source"))
        ]
        selected = matches[args.offset : args.offset + args.limit]
        contact_ids = {row["id"] for row in selected}
        deals = [row for row in state["deals"] if row["contact_id"] in contact_ids]
        deal_ids = {row["id"] for row in deals}
        activities = [row for row in state["activities"] if row["deal_id"] in deal_ids]
        return {
            **state,
            "contacts": selected,
            "deals": deals,
            "tasks": [row for row in state["tasks"] if row["contact_id"] in contact_ids],
            "activities": activities[:30],
            "paging": {
                "offset": args.offset,
                "limit": args.limit,
                "matched_in_snapshot": len(matches),
                "snapshot_limit": 500,
                "tasks_snapshot_limit": 500,
                "deals_snapshot_limit": 500,
                "activities_recent_snapshot_limit": 100,
                "activities_limit": 30,
                "has_more": len(matches) > args.offset + args.limit or state["limited"],
            },
            "limited": state["limited"] or len(matches) > len(selected) or len(activities) > 30,
        }
    if action == "crm.activities":
        return {"activities": services.deal_activities(db, args.deal_id, admin)}
    if action == "crm.contact.create":
        return services.create_contact(db, args, admin)
    if action == "crm.contact.update":
        return services.edit_contact(db, args.contact_id, args, admin)
    if action == "crm.deal.update":
        return services.move_deal(db, args.deal_id, args, admin)
    if action == "crm.note.create":
        return services.add_note(db, args.deal_id, args, admin)
    if action == "crm.task.create":
        return services.create_task(db, args, admin)
    if action == "crm.task.update":
        return services.complete_task(db, args.task_id, args, admin)
    if action == "control.catalog":
        return catalog(db)
    if action == "control.item.create":
        return create_item(db, args, admin)
    if action == "control.item.update":
        return update_item(db, args.id, args, admin)
    if action == "control.connection.update":
        return update_connection(db, args.key, args, admin)
    if action == "social.status":
        from ..social.routes import settings

        return settings()
    raise HTTPException(422, "unsupported_action")


def revisions(db, actions, parent=None):
    current = {}
    for action in actions:
        require_capability(db, action)
        override = db.execute(
            "SELECT id,version FROM crm.control_items WHERE kind='tool' "
            "AND definition->>'action'=%s",
            (action,),
        ).fetchone()
        # Missing overrides must also be frozen so newly disabled tools revoke pending proposals.
        current["action:" + action] = (
            str(override["id"]) + ":" + str(override["version"]) if override else None
        )
        if action in SOCIAL_ACTIONS:
            require_connections(db, "zernio")
            pref = db.execute(
                "SELECT version FROM crm.control_connections WHERE key='zernio'"
            ).fetchone()
            current["connection:zernio"] = pref["version"]
    if parent:
        current["item:" + str(parent["id"])] = parent["version"]
    return current


def check_revisions(db, frozen):
    actions = [key.removeprefix("action:") for key in frozen if key.startswith("action:")]
    current = revisions(db, actions)
    for key, value in frozen.items():
        if key.startswith("item:"):
            row = db.execute(
                "SELECT * FROM crm.control_items WHERE id=%s", (UUID(key.removeprefix("item:")),)
            ).fetchone()
            if not row or not item_view(db, row)["effective"] or row["version"] != value:
                raise HTTPException(409, "definition_changed")
        elif key.startswith("connection:"):
            pref = db.execute(
                "SELECT version,enabled FROM crm.control_connections WHERE key=%s",
                (key.removeprefix("connection:"),),
            ).fetchone()
            if not pref or not pref["enabled"] or pref["version"] != value:
                raise HTTPException(409, "connection_changed")
        elif current.get(key) != value:
            raise HTTPException(409, "capability_changed")
