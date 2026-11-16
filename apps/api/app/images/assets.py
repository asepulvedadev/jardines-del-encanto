"""Only versioned, owner-provided originals are valid reference assets."""

import base64
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException

from .models import ASSET_IDS

ROOT = Path(__file__).resolve().parent / "brand"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


def get(identifier):
    if not isinstance(identifier, str) or identifier not in ASSET_IDS:
        raise HTTPException(422, "invalid_image_reference")
    entry = next((item for item in MANIFEST["assets"] if item["id"] == identifier), None)
    if not entry:
        raise HTTPException(503, "image_asset_unavailable")
    path = ROOT / entry["filename"]
    if path.name != entry["filename"] or path.is_symlink():
        raise HTTPException(503, "image_asset_unavailable")
    try:
        with path.open("rb") as handle:
            raw = handle.read(2 * 1024 * 1024 + 1)
    except OSError:
        raise HTTPException(503, "image_asset_unavailable") from None
    if len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise HTTPException(503, "image_asset_unavailable")
    return entry, raw


def catalog():
    return [
        {key: value for key, value in entry.items() if key not in {"filename", "source"}}
        | {"url": f"/api/crm/images/assets/{entry['id']}/content"}
        for entry in MANIFEST["assets"]
    ]


def references(identifiers):
    result = []
    for identifier in identifiers:
        entry, raw = get(identifier)
        result.append(
            {
                "id": identifier,
                "mime_type": entry["mime_type"],
                "data_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    return result
