"""Extract the reviewed inbox JSON operations from a downloaded Zernio OpenAPI JSON.

Usage: python build_inbox_registry.py /path/to/openapi.json
No downloads, dependencies, credentials or provider calls are performed here.
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(source):
    def resolve(value, trail=()):
        if isinstance(value, list):
            return [resolve(item, trail) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            if not ref.startswith("#/") or ref in trail:
                raise ValueError("External or recursive reference")
            target = source
            for part in ref[2:].split("/"):
                target = target[part]
            return resolve(target, (*trail, ref))
        result = {
            key: resolve(child, trail)
            for key, child in value.items()
            if key not in {"description", "example", "examples", "title", "deprecated"}
        }
        if result.pop("nullable", False):
            return {"anyOf": [result, {"type": "null"}]}
        if result.get("type") == "object" and "properties" in result:
            result.setdefault("additionalProperties", False)
        return result

    operations = {}
    for path, methods in source["paths"].items():
        if not path.startswith("/v1/inbox/"):
            continue
        for method, spec in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            request = {}
            for location in ("path", "query"):
                properties, required = {}, []
                for param in spec.get("parameters", []):
                    param = resolve(param)
                    if param.get("in") != location:
                        continue
                    properties[param["name"]] = param["schema"]
                    if param.get("required"):
                        required.append(param["name"])
                request[location] = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                }
            body = (
                spec.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
            )
            request["body"] = resolve(
                body.get(
                    "schema",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                )
            )
            # Only JSON attachment resolution is allowed; never redirect through the API.
            if spec["operationId"] == "getMessageAttachment":
                request["query"]["properties"]["format"] = {
                    "const": "json",
                    "type": "string",
                }
            operations[spec["operationId"]] = {
                "method": method.upper(),
                "path": path,
                "summary": spec.get("summary", ""),
                "description": spec.get("description", ""),
                "input": request,
            }
    return operations


if __name__ == "__main__":
    raw = Path(sys.argv[1]).read_bytes()
    operations = build(json.loads(raw))
    target = ROOT / "apps/api/app/inbox/registry.json"
    target.write_text(
        json.dumps(
            {
                "source": "https://zernio.com/openapi.yaml",
                "retrieved": "2026-11-15",
                "source_json_sha256": hashlib.sha256(raw).hexdigest(),
                "operations": operations,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"Extracted {len(operations)} fixed inbox operations")
