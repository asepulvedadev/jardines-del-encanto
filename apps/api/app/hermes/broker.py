"""Session-scoped broker identities, exact-action proposals and once-only consumption."""

import json
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from ..control import service
from ..crm import security
from ..crm.database import connect


def proposal_view(row):
    return {key: row[key] for key in ("id", "action", "arguments", "status", "version")}


def dispatch(db, action, arguments, admin, run_id=None, parent=None):
    service.lock(db)
    if action.startswith("custom."):
        try:
            item_id = UUID(action.removeprefix("custom."))
        except ValueError:
            raise HTTPException(422, "unsupported_action") from None
        return run_item(db, item_id, arguments, admin, run_id)
    args = service.validate(action, arguments)
    frozen = service.revisions(db, [action], parent)
    if action == "social.connect":
        service.require_connections(db, args.platform)
        pref = db.execute(
            "SELECT version FROM crm.control_connections WHERE key=%s", (args.platform,)
        ).fetchone()
        frozen["connection:" + args.platform] = pref["version"]
    if action in service.READ_ACTIONS:
        return {"result": jsonable_encoder(service.execute(db, action, args, admin))}
    row = db.execute(
        """INSERT INTO crm.hermes_proposals
        (actor_id,session_hash,run_id,action,arguments,revisions) VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING *""",
        (
            admin["id"],
            admin["token_hash"],
            run_id,
            action,
            Jsonb(args.model_dump(mode="json")),
            Jsonb(frozen),
        ),
    ).fetchone()
    service.audit(
        db, admin, "proposal.create", {"action": action, "arguments": arguments}, row["id"]
    )
    return {"proposals": [proposal_view(row)]}


def run_item(db, item_id, arguments, admin, run_id=None):
    item = db.execute("SELECT * FROM crm.control_items WHERE id=%s", (item_id,)).fetchone()
    if not item:
        raise HTTPException(404, "not_found")
    if not service.item_view(db, item)["effective"]:
        raise HTTPException(409, "item_disabled")
    kind, definition = item["kind"], item["definition"]
    if kind == "tool":
        return dispatch(
            db, definition["action"], {**definition["defaults"], **arguments}, admin, run_id, item
        )
    if kind in ("plugin", "connection"):
        if set(arguments) != {"action", "arguments"} or not isinstance(
            arguments["arguments"], dict
        ):
            raise HTTPException(422, "invalid_input")
        if arguments["action"] not in definition["actions"]:
            raise HTTPException(422, "unsupported_action")
        return dispatch(db, arguments["action"], arguments["arguments"], admin, run_id, item)
    if kind == "script":
        if arguments:
            raise HTTPException(422, "invalid_input")
        results, proposals = [], []
        for step in definition["steps"]:
            response = dispatch(db, step["action"], step["arguments"], admin, run_id, item)
            if "result" in response:
                results.append({"action": step["action"], "result": response["result"]})
            proposals.extend(response.get("proposals", []))
        return {"result": {"steps": results}, "proposals": proposals}
    raise HTTPException(409, "item_not_executable")


def resolve(proposal_id, version, admin, approve):
    external = None
    with connect() as db:
        service.lock(db)
        row = db.execute(
            """SELECT * FROM crm.hermes_proposals
            WHERE id=%s AND actor_id=%s AND session_hash=%s FOR UPDATE""",
            (proposal_id, admin["id"], admin["token_hash"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "not_found")
        if row["status"] != "pending" or row["version"] != version:
            raise HTTPException(409, "proposal_changed")
        if row["expires_at"] <= datetime.now(UTC):
            db.execute(
                "UPDATE crm.hermes_proposals SET status='expired',version=version+1 WHERE id=%s",
                (proposal_id,),
            )
            db.commit()
            raise HTTPException(410, "proposal_expired")
        result = None
        if approve:
            service.check_revisions(db, row["revisions"])
            args = service.validate(row["action"], row["arguments"])
            if row["action"] == "social.connect":
                service.require_connections(db, args.platform)
            if row["action"] in service.SOCIAL_ACTIONS:
                # Reserve before network dispatch. An uncertain external outcome is NOT retryable.
                external = (row["action"], args)
                result = {"status": "dispatch_reserved", "retryable": False}
            else:
                result = service.execute(db, row["action"], args, admin)
        updated = db.execute(
            """UPDATE crm.hermes_proposals SET status=%s,version=version+1,
            result=%s WHERE id=%s RETURNING *""",
            ("approved" if approve else "rejected", Jsonb(jsonable_encoder(result)), proposal_id),
        ).fetchone()
        service.audit(
            db,
            admin,
            "proposal.approve" if approve else "proposal.reject",
            {"action": row["action"], "arguments": row["arguments"]},
            proposal_id,
        )
    if external:
        from ..social import routes

        try:
            action, args = external
            result = (
                routes.sync_settings(routes.EmptyInput(), admin)
                if action == "social.sync"
                else routes.start_connection(args.platform, routes.EmptyInput(), admin)
            )
        except HTTPException:
            result = {"status": "external_outcome_unconfirmed", "retryable": False}
        except Exception:  # noqa: BLE001 - consumed external actions must remain fail-closed
            # Provider/transport failures never expose secrets or reopen a consumed action.
            result = {"status": "external_outcome_unconfirmed", "retryable": False}
        with connect() as db:
            db.execute(
                "UPDATE crm.hermes_proposals SET result=%s WHERE id=%s",
                (Jsonb(jsonable_encoder(result)), proposal_id),
            )
    response = {"proposal": proposal_view(updated)}
    if approve:
        response["result"] = jsonable_encoder(result)
    return response


def issue(db, admin, prompt):
    token = secrets.token_urlsafe(32)
    row = db.execute(
        """INSERT INTO crm.hermes_runs(actor_id,session_hash,token_hash,prompt)
        VALUES (%s,%s,%s,%s) RETURNING id""",
        (admin["id"], admin["token_hash"], security.digest(token), prompt),
    ).fetchone()
    return row["id"], token


def identity(db, bearer):
    if not bearer or not bearer.startswith("Bearer ") or len(bearer) > 100:
        raise HTTPException(401, "service_authentication_required")
    token = bearer.removeprefix("Bearer ")
    row = db.execute(
        """SELECT r.*,u.username,u.role FROM crm.hermes_runs r
        JOIN crm.users u ON u.id=r.actor_id JOIN crm.sessions s ON s.token_hash=r.session_hash
        WHERE r.token_hash=%s AND r.expires_at>now() AND s.expires_at>now()
          AND s.last_seen>now()-interval '30 minutes' AND u.enabled AND u.role='admin'
        FOR UPDATE OF r FOR SHARE OF s""",
        (security.digest(token),),
    ).fetchone()
    if not row:
        raise HTTPException(401, "service_authentication_required")
    service.require_connections(db, "hermes")
    return row


def actor(run):
    return {
        "id": run["actor_id"],
        "token_hash": run["session_hash"],
        "username": run["username"],
        "role": run["role"],
    }


def tools(db):
    actions = [action for action in service.ACTION_MODELS if service.capability_enabled(db, action)]
    items = [
        item
        for item in service.rows(db)
        if item["kind"] != "skill" and service.item_view(db, item)["effective"]
    ]
    custom = {
        "custom." + str(item["id"]): {
            "kind": item["kind"],
            "name": item["name"],
            "definition": {
                key: value for key, value in item["definition"].items() if key != "instructions"
            },
        }
        for item in items
    }
    actions.extend(custom)

    def compact(value):
        if isinstance(value, dict):
            return {key: compact(entry) for key, entry in value.items() if key != "title"}
        if isinstance(value, list):
            return [compact(entry) for entry in value]
        return value

    manifest = {
        "actions": {
            key: compact(service.ACTION_MODELS[key].model_json_schema())
            for key in actions
            if key in service.ACTION_MODELS
        },
        "custom": custom,
        "definitions": {
            key: compact(model.model_json_schema())
            for key, model in service.models.DEFINITIONS.items()
        },
    }
    description = (
        "Consultar la aplicación o proponer cambios para aprobación exacta del administrador. "
        "Las mutaciones NO se aplican hasta aprobación humana. No inventar IDs ni versiones; "
        "consultar crm.workspace y crm.activities primero. custom tool combina defaults con arguments; "
        "plugin/connection usa arguments={action,arguments}; script usa arguments={}. "
        "Contratos JSON de argumentos y definiciones: "
        + json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    )
    if len(description.encode()) > 16384:
        raise HTTPException(503, "hermes_catalog_too_large")
    return [
        {
            "type": "function",
            "function": {
                "name": "jardines_app",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": actions},
                        "arguments": {"type": "object"},
                    },
                    "required": ["action", "arguments"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def claim(db, run):
    service.lock(db)
    if run["state"] != "issued":
        raise HTTPException(409, "run_already_claimed")
    db.execute("UPDATE crm.hermes_runs SET state='claimed' WHERE id=%s", (run["id"],))
    skills = []
    for item in service.rows(db):
        if not service.item_view(db, item)["effective"]:
            continue
        content = (
            item["definition"].get("content")
            if item["kind"] == "skill"
            else (item["definition"].get("instructions") if item["kind"] == "plugin" else None)
        )
        if content:
            skills.append({"name": item["name"], "content": content})
    schemas = tools(db)
    keys = schemas[0]["function"]["parameters"]["properties"]["action"]["enum"]
    scope = {}
    for key in keys:
        if key.startswith("custom."):
            item = db.execute(
                "SELECT version FROM crm.control_items WHERE id=%s",
                (UUID(key.removeprefix("custom.")),),
            ).fetchone()
            scope[key] = item["version"]
        else:
            override = db.execute(
                "SELECT id,version FROM crm.control_items WHERE kind='tool' "
                "AND definition->>'action'=%s",
                (key,),
            ).fetchone()
            scope[key] = str(override["id"]) + ":" + str(override["version"]) if override else None
    service.audit(db, actor(run), "run.claim", {"run_id": str(run["id"]), "scope": scope})
    return {"run_id": run["id"], "prompt": run["prompt"], "skills": skills, "tools": schemas}


def call(db, run, data):
    if run["state"] != "claimed":
        raise HTTPException(409, "run_not_active")
    payload = data.model_dump(mode="json", exclude={"call_id"})
    old = db.execute(
        "SELECT request,response FROM crm.hermes_calls WHERE run_id=%s AND call_id=%s",
        (run["id"], data.call_id),
    ).fetchone()
    if old:
        if old["request"] != payload:
            raise HTTPException(409, "call_id_reused")
        return old["response"]
    if run["calls"] >= 12:
        raise HTTPException(429, "run_call_limit")
    previous = db.execute(
        "SELECT response FROM crm.hermes_calls WHERE run_id=%s", (run["id"],)
    ).fetchall()
    used_bytes = sum(
        len(json.dumps(row["response"], ensure_ascii=False, separators=(",", ":")).encode())
        for row in previous
    )
    # Reserve space for bounded errors on every remaining call, never truncate tool output.
    response_limit = 65536 - (11 - run["calls"]) * 128
    # Failed calls also consume budget and are deduplicated; a savepoint retains only the error.
    db.execute("UPDATE crm.hermes_runs SET calls=calls+1 WHERE id=%s", (run["id"],))
    try:
        with db.transaction():
            service.lock(db)
            claim = db.execute(
                "SELECT arguments FROM crm.control_audit WHERE action='run.claim' "
                "AND arguments->>'run_id'=%s",
                (str(run["id"]),),
            ).fetchone()
            scope = claim["arguments"]["scope"] if claim else {}
            if data.action not in scope:
                raise HTTPException(409, "capability_not_in_run")
            if data.action.startswith("custom."):
                parent = db.execute(
                    "SELECT * FROM crm.control_items WHERE id=%s",
                    (UUID(data.action.removeprefix("custom.")),),
                ).fetchone()
                if not parent or parent["version"] != scope[data.action]:
                    raise HTTPException(409, "definition_changed")
            else:
                service.check_revisions(db, {"action:" + data.action: scope[data.action]})
            result = dispatch(db, data.action, data.arguments, actor(run), run["id"])
            current_bytes = len(
                json.dumps(
                    jsonable_encoder(result), ensure_ascii=False, separators=(",", ":")
                ).encode()
            )
            if used_bytes + current_bytes > response_limit:
                raise HTTPException(409, "run_output_limit")
    except HTTPException as error:
        result = {"result": {"error": error.detail}}
    encoded = jsonable_encoder(result)
    db.execute(
        """INSERT INTO crm.hermes_calls(run_id,call_id,request,response) VALUES (%s,%s,%s,%s)""",
        (run["id"], data.call_id, Jsonb(payload), Jsonb(encoded)),
    )
    return encoded


def run_result(db, run):
    calls = db.execute(
        "SELECT response FROM crm.hermes_calls WHERE run_id=%s ORDER BY call_id", (run["id"],)
    ).fetchall()
    proposals = db.execute(
        "SELECT * FROM crm.hermes_proposals WHERE run_id=%s ORDER BY created_at,id", (run["id"],)
    ).fetchall()
    return {
        "run_id": run["id"],
        "reply": run["reply"],
        "results": [row["response"]["result"] for row in calls if "result" in row["response"]],
        "proposals": [proposal_view(row) for row in proposals],
    }


def finish(db, run, data):
    if run["state"] != "claimed":
        raise HTTPException(409, "run_not_active")
    run["reply"] = data.reply
    db.execute(
        "UPDATE crm.hermes_runs SET state='finished',reply=%s WHERE id=%s", (data.reply, run["id"])
    )
    return run_result(db, run)
