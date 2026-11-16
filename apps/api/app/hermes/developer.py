"""Revocable, source-bound WhatsApp developer authority, never a browser session."""

import json
import secrets

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from ..control import extensions, service
from ..crm import security

ACTIONS = frozenset(
    {
        # Business access is restricted to the source-verified developer channel.
        # Reuse canonical services; never mint browser sessions or activation grants.
        "analytics.summary",
        "crm.workspace",
        "crm.activities",
        "crm.contact.create",
        "crm.contact.update",
        "crm.deal.update",
        "crm.note.create",
        "crm.task.create",
        "crm.task.update",
        "workflows.catalog",
        "workflows.definitions",
        "workflows.run",
        "workflows.draft.create",
        "workflows.draft.update",
        "workflows.pause",
        "workflows.stop",
        "control.catalog",
        "control.extension.create",
        "control.extension.update",
        "control.extension.test",
        "control.extension.install",
        "sara.config.get",
        "sara.config.update",
        "sara.learn",
        "sara.simulate",
        "sara.simulation",
        "images.catalog",
        "images.generate",
        "images.status",
    }
)
TARGETS = ACTIONS - service.EXTENSION_ACTIONS - {"control.catalog"}


def denied():
    raise HTTPException(401, "service_authentication_required")


def safe_definition(item):
    return item.get("kind") in {"skill", "tool"} and all(
        action in TARGETS for action in service.definition_actions(item)
    )


def owned_items(db, owner_id):
    # Filter in SQL before the bound: another owner's items cannot crowd this catalog.
    return db.execute(
        "SELECT * FROM crm.control_items WHERE actor_id=%s AND origin='sara' "
        "AND kind IN ('skill','tool') ORDER BY created_at,id LIMIT 201",
        (owner_id,),
    ).fetchall()


def authority(db, run, *, queued=False):
    """Call under the control lock, shared with config/revocation and registry writes."""
    from ..social import config, workflow
    from ..social import whatsapp_agent as agent

    service.lock(db)
    grant = db.execute(
        """SELECT g.*,j.state AS job_state,j.agent_version AS job_version,
        j.account_id AS job_account,j.profile_id AS job_profile,
        j.conversation_id AS job_conversation,j.participant_id AS job_participant
        FROM crm.whatsapp_developer_authority g JOIN crm.whatsapp_agent_jobs j ON j.id=g.job_id
        WHERE g.run_id=%s""",
        (run["id"],),
    ).fetchone()
    channel = agent.current(db)
    if not grant or not channel or not channel["enabled"]:
        denied()
    owner = db.execute(
        "SELECT id,username,role FROM crm.users WHERE id=%s AND enabled AND role='admin'",
        (grant["owner_id"],),
    ).fetchone()
    if (
        not owner
        or owner["id"] != run["actor_id"]
        or channel["owner_id"] != owner["id"]
        or channel["version"] != grant["agent_version"]
        or grant["job_version"] != grant["agent_version"]
        or grant["job_state"]
        not in ({"generating", "reserved", "completed"} if queued else {"generating"})
        or channel["document"]["account_id"] != grant["account_id"]
        or not agent.developer(channel["document"], grant["participant_id"])
        or any(
            grant[key] != grant["job_" + suffix]
            for key, suffix in (
                ("account_id", "account"),
                ("profile_id", "profile"),
                ("conversation_id", "conversation"),
                ("participant_id", "participant"),
            )
        )
    ):
        denied()
    try:
        credentials = config.required()
        if (
            workflow._digest(credentials) != grant["credential_revision"]
            or channel["credential_revision"] != grant["credential_revision"]
            or credentials["profile_id"] != grant["profile_id"]
        ):
            denied()
        service.require_connections(db, "hermes", "zernio", "whatsapp")
    except HTTPException:
        denied()
    return {
        "id": owner["id"],
        "username": owner["username"],
        "role": owner["role"],
        "channel": "whatsapp_developer",
        "developer_job_id": grant["job_id"],
        "developer_run_id": run["id"],
    }


def issue(db, job_id, history=None):
    """Only an actual currently claimed, vendor-verified source job can issue a run."""
    from ..social import config, workflow
    from ..social import whatsapp_agent as agent
    from .broker import validated_history

    service.lock(db)
    job = db.execute(
        "SELECT * FROM crm.whatsapp_agent_jobs WHERE id=%s FOR UPDATE", (job_id,)
    ).fetchone()
    channel = agent.current(db)
    if not job or not channel or not channel["owner_id"] or not channel["enabled"]:
        denied()
    owner = db.execute(
        "SELECT id FROM crm.users WHERE id=%s AND enabled AND role='admin'", (channel["owner_id"],)
    ).fetchone()
    if (
        not owner
        or job["state"] != "generating"
        or job["agent_version"] != channel["version"]
        or job["account_id"] != channel["document"]["account_id"]
        or not agent.developer(channel["document"], job["participant_id"])
    ):
        denied()
    credentials = config.required()
    if (
        job["profile_id"] != credentials["profile_id"]
        or workflow._digest(credentials) != channel["credential_revision"]
        or not agent.source_verified(job, credentials)
    ):
        denied()
    service.require_connections(db, "hermes", "zernio", "whatsapp")
    if db.execute(
        "SELECT 1 FROM crm.whatsapp_developer_authority WHERE job_id=%s", (job_id,)
    ).fetchone():
        raise HTTPException(409, "developer_source_already_used")
    # Supply the configured label only after exact source-bound authorization.
    # Keep the original inbound job unchanged; names never grant permissions.
    prompt = json.dumps(
        {
            "channel": "whatsapp_developer",
            "verified_developer_name": agent.developer(
                channel["document"], job["participant_id"]
            ),
            "message": job["content"],
        },
        ensure_ascii=False,
    )
    from ..social.whatsapp_audio import requested

    if requested(job["content"]):
        document = json.loads(prompt)
        document["response_format"] = "spoken_answer"
        document["instruction"] = (
            "Return the answer as natural spoken text. The application synthesizes it "
            "separately; do not claim audio was sent or propose another TTS action."
        )
        prompt = json.dumps(document, ensure_ascii=False)
    token = secrets.token_urlsafe(32)
    run = db.execute(
        """INSERT INTO crm.hermes_runs(actor_id,session_hash,token_hash,prompt,history,authentication)
        VALUES(%s,NULL,%s,%s,%s,'whatsapp_developer') RETURNING id""",
        (owner["id"], security.digest(token), prompt, Jsonb(validated_history(history))),
    ).fetchone()
    db.execute(
        """INSERT INTO crm.whatsapp_developer_authority(run_id,job_id,owner_id,agent_version,
        account_id,profile_id,conversation_id,participant_id,credential_revision)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            run["id"],
            job["id"],
            owner["id"],
            channel["version"],
            job["account_id"],
            job["profile_id"],
            job["conversation_id"],
            job["participant_id"],
            channel["credential_revision"],
        ),
    )
    return run["id"], token


def dispatch(db, action, arguments, actor, run_id):
    """Least-scope dispatch revalidates the grant even for nested owned tool targets."""
    service.lock(db)
    run = db.execute(
        "SELECT * FROM crm.hermes_runs WHERE id=%s AND expires_at>now()", (run_id,)
    ).fetchone()
    if not run or run["authentication"] != "whatsapp_developer" or run["state"] != "claimed":
        denied()
    actual = authority(db, run)
    if actual["id"] != actor["id"]:
        denied()
    if action.startswith("custom."):
        item = next(
            (row for row in owned_items(db, actual["id"]) if "custom." + str(row["id"]) == action),
            None,
        )
        if (
            not item
            or not safe_definition(item)
            or item["kind"] != "tool"
            or not service.item_view(db, item)["effective"]
        ):
            raise HTTPException(409, "developer_action_denied")
        service.require_capability(db, item["definition"]["action"])
        return dispatch(
            db,
            item["definition"]["action"],
            {**item["definition"]["defaults"], **arguments},
            actual,
            run_id,
        )
    if action not in ACTIONS:
        raise HTTPException(409, "developer_action_denied")
    args = service.validate(action, arguments)
    service.require_capability(db, action)
    if action == "control.catalog":
        return {
            "result": {
                "items": [
                    jsonable_encoder(service.item_view(db, row))
                    for row in owned_items(db, actual["id"])
                    if safe_definition(row)
                ],
                "capabilities": sorted(ACTIONS),
            }
        }
    if action in service.EXTENSION_ACTIONS:
        if action == "control.extension.create":
            candidate = args.model_dump()
        else:
            existing = extensions.owned(db, args, actual)
            candidate = {
                **existing,
                **args.model_dump(exclude_unset=True, exclude={"id", "version"}),
            }
        if not safe_definition(candidate):
            raise HTTPException(409, "developer_action_denied")
        return {"result": jsonable_encoder(extensions.execute(db, action, args, actual))}
    return {"result": jsonable_encoder(service.execute(db, action, args, actual))}


def generate(job, channel, history):
    """The worker enters this branch only for verified channel developers."""
    from ..crm.database import connect
    from . import bridge, broker

    with connect() as db:
        run_id, token = issue(db, job["id"], history)
    try:
        bridge.request("/run", {"token": token}, timeout=90)
    except HTTPException:
        with connect() as db:
            db.execute(
                "UPDATE crm.hermes_runs SET state='failed' WHERE id=%s AND state!='finished'",
                (run_id,),
            )
        raise
    with connect() as db:
        run = db.execute("SELECT * FROM crm.hermes_runs WHERE id=%s", (run_id,)).fetchone()
        if not run or run["state"] != "finished":
            raise HTTPException(503, "hermes_unavailable")
        result = broker.run_result(db, run)
    from ..social.workflow import _text

    return _text(result["reply"], 1500)


def queue_origin(admin):
    """Only a server-issued developer actor can attach channel provenance to work."""
    if admin.get("channel") != "whatsapp_developer":
        return "web", None
    if not admin.get("developer_run_id"):
        denied()
    return "whatsapp_developer", admin["developer_run_id"]


def queue_authority(db, row):
    """Revalidate delayed paid authority without requiring its completed chat run to stay active."""
    if row.get("origin_kind", "web") == "web":
        return
    if row.get("origin_kind") != "whatsapp_developer" or not row.get("origin_run_id"):
        denied()
    run = db.execute(
        "SELECT * FROM crm.hermes_runs WHERE id=%s AND actor_id=%s AND authentication='whatsapp_developer'",
        (row["origin_run_id"], row["owner_id"]),
    ).fetchone()
    if not run or run["state"] not in {"claimed", "finished"}:
        denied()
    authority(db, run, queued=True)
