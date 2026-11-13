"""Complete private editor snapshots; fixed reads only, never chat/audit payloads."""

import json
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from jsonschema import Draft202012Validator, FormatChecker

from ..control import service as control
from ..crm.database import connect
from . import bridge, inventory, models, service

KINDS = {
    "agent": ("getAgent", "updateAgent", "agent_id"),
    "instructions": ("getRetellLLM", "updateRetellLLM", "llm_id"),
}
REASONS = {
    "editor_field_private",
    "editor_field_too_large",
    "editor_field_too_complex",
    "editor_field_invalid",
    "editor_field_schema_mismatch",
}
MAXIMUM = 96 * 1024


def properties(schema):
    result = dict(schema.get("properties", {}))
    for branch in schema.get("allOf", []):
        for key, value in properties(branch).items():
            result[key] = {"allOf": [result[key], value]} if key in result else value
    return result


def nullable_schema(value):
    if isinstance(value, list):
        return [nullable_schema(child) for child in value]
    if not isinstance(value, dict):
        return value
    result = {key: nullable_schema(child) for key, child in value.items() if key != "nullable"}
    return {"anyOf": [result, {"type": "null"}]} if value.get("nullable") is True else result


def validate_result(value, request, field_schemas):
    """Validate complete/blocked coverage. Never silently turn invalid data into a fragment."""
    endpoint, _, identity = KINDS[request.kind]
    if (
        not isinstance(value, dict)
        or set(value) != {"status", "endpoint", "data", "editor"}
        or value["status"] != "completed"
        or value["endpoint"] != endpoint
        or not isinstance(value["data"], dict)
        or not isinstance(value["editor"], dict)
        or set(value["editor"]) != {"complete_fields", "blocked_fields"}
        or len(json.dumps(value, allow_nan=False).encode()) > MAXIMUM
    ):
        raise ValueError("invalid_editor_response")
    data, metadata = value["data"], value["editor"]
    complete, blocked = metadata["complete_fields"], metadata["blocked_fields"]
    if (
        not isinstance(complete, list)
        or not all(isinstance(key, str) for key in complete)
        or len(complete) != len(set(complete))
        or not isinstance(blocked, dict)
        or set(complete) & set(blocked)
        or set(complete) | set(blocked) != set(field_schemas)
        or any(reason not in REASONS for reason in blocked.values())
        or set(data) - {identity, "version"} - set(complete)
        or data.get(identity) != request.id
    ):
        raise ValueError("invalid_editor_response")
    version = data.get("version")
    if (version is not None and (type(version) is not int or not 0 <= version <= 2**53 - 1)) or (
        request.version is not None and version != request.version
    ):
        raise ValueError("editor_version_changed")
    for key in complete:
        field = field_schemas[key]
        if models.sensitive(key) or field.get("readOnly") is True:
            raise ValueError("invalid_editor_response")
        if key in data:
            models.check_arguments(data[key])
            if next(
                Draft202012Validator(
                    nullable_schema(field), format_checker=FormatChecker()
                ).iter_errors(data[key]),
                None,
            ):
                raise ValueError("invalid_editor_field")
    return {"provider": "retell", **value}


def remaining(deadline, maximum, reserved=0):
    duration = deadline - monotonic() - reserved
    if duration <= 0:
        raise HTTPException(503, "retell_editor_timeout")
    return min(maximum, duration)


def snapshot(data, admin):
    """Full read with shared concurrency, preflight and live-session policy checks."""
    endpoint, update_endpoint, identity = KINDS[data.kind]
    arguments = {identity: data.id}
    if data.version is not None:
        arguments["version"] = data.version
    args = models.Execute(endpoint=endpoint, arguments=arguments)
    deadline = monotonic() + 85
    try:
        with inventory._slot():
            with connect() as db:
                version = inventory._current(db, admin)
                revision, digest = service.preflight(
                    db, args, data.revision, timeout=remaining(deadline, 5, reserved=3)
                )
                schema = service.schema(
                    db, models.Schema(revision=revision, endpoint=update_endpoint)
                )
                fields = properties(properties(schema["input_schema"])["requestBody"])
                row = {
                    "id": uuid4(),
                    "revisions": {
                        "provider:retell": revision,
                        "retell:schema_hash": digest,
                        "retell:requires_consent": False,
                        "retell:risk": "read",
                    },
                }
                payload = service.prepare(
                    db, row, args, admin, False, timeout=remaining(deadline, 5, reserved=3)
                )
                inventory._current(db, admin, version)
                metadata = {
                    "endpoint": endpoint,
                    "provider_revision": revision,
                    "connection_version": version,
                }
                control.audit(db, admin, "retell.editor_read", {**metadata, "stage": "prepared"})
            # The metadata audit commits before external read. Snapshot data is never persisted.
            value = bridge.request("/editor-read", payload, timeout=remaining(deadline, 65))
            result = validate_result(value, data, fields)
            with connect() as db:
                inventory._current(db, admin, version)
                _, current_digest = service.preflight(
                    db, args, revision, timeout=remaining(deadline, 5, reserved=3)
                )
                if current_digest != digest:
                    raise HTTPException(409, "retell_schema_changed")
                inventory._current(db, admin, version)
                control.audit(db, admin, "retell.editor_read", {**metadata, "stage": "completed"})
            return result
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - never reflect snapshot data or provider errors
        raise HTTPException(503, "retell_editor_unavailable") from None
