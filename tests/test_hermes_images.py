"""No image test contacts OpenAI or reads a real credential."""

import base64
import importlib.util
import json
import struct
import zlib
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "operator_images", ROOT / "ops/hermes/operator_images.py"
)
images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(images)


def png():
    def chunk(kind, data):
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", 1024, 1024, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * 3072) * 1024))
        + chunk(b"IEND", b"")
    )


def payload():
    return {"prompt": "Branded concept", "reference_images": [], "size": "1024x1024"}


def test_reject_arbitrary_url_path_model_count_and_bytes(monkeypatch):
    monkeypatch.setattr(images, "BRAND_ROOT", ROOT / "apps/api/app/images/brand")
    for value in (
        {"url": "https://bad/"},
        {"model": "bad"},
        {"n": 2},
        {
            "reference_images": [
                {"id": "../secret", "mime_type": "image/png", "data_base64": "AAAA"}
            ]
        },
        {"prompt": "x" * 5000},
    ):
        with pytest.raises(ValueError):
            images.validate_request(payload() | value)
    assert images.validate_request(payload())["model"] == "gpt-image-2.5-flare"


def test_allowed_assets_use_json_data_urls_and_hash_validation(monkeypatch):
    root = ROOT / "apps/api/app/images/brand"
    monkeypatch.setattr(images, "BRAND_ROOT", root)
    entry = json.loads((root / "manifest.json").read_text())["assets"][0]
    encoded = base64.b64encode((root / entry["filename"]).read_bytes()).decode()
    value = payload() | {
        "reference_images": [
            {"id": entry["id"], "mime_type": entry["mime_type"], "data_base64": encoded}
        ]
    }
    validated = images.validate_request(value)
    assert validated["images"] == [{"image_url": "data:image/png;base64," + encoded}]
    value["reference_images"][0]["data_base64"] = "AAAA"
    with pytest.raises(ValueError):
        images.validate_request(value)


def test_provider_fixed_destination_once_and_sanitized_failure(monkeypatch):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = json.dumps(
        {"data": [{"b64_json": base64.b64encode(png()).decode()}]}
    ).encode()
    monkeypatch.setattr(
        images,
        "HTTPSConnection",
        lambda host, timeout: (
            connection if host == "api.openai.com" and timeout <= 90 else None
        ),
    )
    monkeypatch.setattr(images, "SECRET", Mock(read_text=lambda: "test-secret"))
    assert images.generate(payload())["ok"] is True
    args = connection.request.call_args
    assert args.args[:2] == ("POST", "/v1/images/generations")
    body = json.loads(args.kwargs["body"])
    assert (
        body["n"] == 1 and body["quality"] == "low" and body["output_format"] == "png"
    )
    assert connection.request.call_count == 1
    response.status = 500
    response.read.return_value = b"vendor sensitive error"
    result = images.generate(payload())
    assert result == {"ok": False, "error": "image_generation_unavailable"}
    assert "sensitive" not in json.dumps(result)
