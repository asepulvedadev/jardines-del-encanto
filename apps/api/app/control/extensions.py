"""Immediate lifecycle for owned, declarative application extensions only."""

from fastapi import HTTPException

from . import models, service

# Flat canonical targets only: no indirection to another item, policy or connection action.
SAFE_ACTIONS = frozenset(
    {
        "crm.workspace",
        "crm.activities",
        "crm.contact.create",
        "crm.contact.update",
        "crm.deal.update",
        "crm.note.create",
        "crm.task.create",
        "crm.task.update",
        "social.status",
    }
)


def allowed(candidate):
    return candidate["kind"] in {"skill", "tool", "plugin", "script"} and all(
        action in SAFE_ACTIONS for action in service.definition_actions(candidate)
    )


def validate_candidate(db, candidate, *, installing=False):
    if not allowed(candidate) or not service.supported(candidate):
        raise HTTPException(422, "unsafe_extension_definition")
    if installing:
        for action in service.definition_actions(candidate):
            service.require_capability(db, action)


def owned(db, args, admin):
    service.lock(db)
    row = db.execute(
        "SELECT * FROM crm.control_items WHERE id=%s AND actor_id=%s AND origin='sara' FOR UPDATE",
        (args.id, admin["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "not_found")
    if row["version"] != args.version:
        raise HTTPException(409, "record_changed")
    return row


def execute(db, action, args, admin):
    service.lock(db)
    if action == "control.extension.create":
        data = models.ItemCreate.model_validate(args.model_dump())
        validate_candidate(db, data.model_dump())
        result = service.create_item(db, data, admin, origin="sara")
    else:
        row = owned(db, args, admin)
        if action == "control.extension.update":
            # Editing a live definition always stages a disabled draft for a separate install.
            data = models.ItemUpdate.model_validate(
                {
                    **args.model_dump(exclude_unset=True, exclude={"id"}),
                    "enabled": False,
                }
            )
            result = service.update_item(db, row["id"], data, admin)
        elif action == "control.extension.install":
            validate_candidate(db, row, installing=True)
            result = service.update_item(
                db,
                row["id"],
                models.ItemUpdate(
                    version=args.version,
                    enabled=True,
                ),
                admin,
            )
        elif action == "control.extension.test":
            # Never dispatch, connect, create a proposal, or mutate application/business state.
            validate_candidate(db, row, installing=True)
            result = {
                "id": str(row["id"]),
                "version": row["version"],
                "valid": True,
                "installed": row["enabled"],
                "side_effects": False,
                "checks": [
                    {"action": target, "requires_approval": target not in service.READ_ACTIONS}
                    for target in service.definition_actions(row)
                ],
            }
        else:
            raise HTTPException(422, "unsupported_action")
    service.audit(db, admin, action, {"id": str(result["id"]), "version": result["version"]})
    return result
