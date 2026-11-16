"""Fixed image provider protocol: no URLs, uploads, dynamic models or retries."""

import base64
import binascii
import hashlib
import json
import signal
import struct
import threading
import zlib
from contextlib import contextmanager
from http.client import HTTPSConnection
from pathlib import Path

MODEL = "gpt-image-2.5-flare"
MAX_BODY = 4 * 1024 * 1024
MAX_REPLY = 12 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
SECRET = Path("/run/secrets/openai_api_key")
BRAND_ROOT = Path("/opt/jardines-images/brand")
ASSET_IDS = frozenset(
    {"logo-white", "logo-transparent", "photo-aerial", "photo-entrance", "photo-gate"}
)
SIZES = {"1024x1024", "1536x1024", "1024x1536"}


class ImageDeadline(TimeoutError):
    pass


@contextmanager
def request_deadline(seconds=90):
    # HTTPServer runs requests on the main thread; non-main callers fail closed.
    if threading.current_thread() is not threading.main_thread():
        raise ImageDeadline("image_deadline_unavailable")
    previous = signal.getsignal(signal.SIGALRM)
    prior_timer = signal.getitimer(signal.ITIMER_REAL)

    def expired(*_):
        raise ImageDeadline("image_deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if prior_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *prior_timer)


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "prompt",
        "reference_images",
        "size",
    }:
        raise ValueError("image_request_denied")
    prompt, references, size = (
        payload["prompt"],
        payload["reference_images"],
        payload["size"],
    )
    if (
        not isinstance(prompt, str)
        or not 1 <= len(prompt.strip()) <= 4000
        or "\x00" in prompt
        or not isinstance(size, str)
        or size not in SIZES
        or not isinstance(references, list)
        or len(references) > 3
    ):
        raise ValueError("image_request_denied")
    if len(json.dumps(payload, allow_nan=False).encode()) > MAX_BODY:
        raise ValueError("image_request_denied")
    images, used = [], set()
    manifest = None
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {
            "id",
            "mime_type",
            "data_base64",
        }:
            raise ValueError("image_reference_denied")
        identifier, mime, encoded = (
            reference["id"],
            reference["mime_type"],
            reference["data_base64"],
        )
        if (
            not isinstance(identifier, str)
            or identifier not in ASSET_IDS
            or identifier in used
        ):
            raise ValueError("image_reference_denied")
        used.add(identifier)
        if manifest is None:
            manifest = json.loads((BRAND_ROOT / "manifest.json").read_text())
        entry = next(
            (item for item in manifest["assets"] if item["id"] == identifier), None
        )
        if (
            not entry
            or mime != entry["mime_type"]
            or not isinstance(encoded, str)
            or len(encoded) > MAX_BODY
        ):
            raise ValueError("image_reference_denied")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("image_reference_denied") from None
        if (
            len(raw) != entry["size"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
        ):
            raise ValueError("image_reference_denied")
        images.append({"image_url": f"data:{mime};base64,{encoded}"})
    result = {
        "model": MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": "low",
        "output_format": "png",
    }
    if images:
        result["images"] = images
    return result


def validate_png(data, size):
    if (
        not isinstance(data, bytes)
        or not 57 <= len(data) <= MAX_IMAGE
        or data[:8] != b"\x89PNG\r\n\x1a\n"
    ):
        raise ValueError("image_reply_denied")
    offset, seen_data, first = 8, False, True
    while offset + 12 <= len(data):
        length = struct.unpack("!I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + length + 12
        if end > len(data):
            break
        body = data[offset + 8 : end - 4]
        if zlib.crc32(kind + body) != struct.unpack("!I", data[end - 4 : end])[0]:
            break
        if first:
            if kind != b"IHDR" or length != 13:
                break
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack("!IIBBBBB", body)
            )
            if (
                f"{width}x{height}" != size
                or depth not in {8, 16}
                or color not in {0, 2, 4, 6}
                or compression
                or filtering
                or interlace not in {0, 1}
            ):
                break
            first = False
        elif kind == b"IHDR":
            break
        if kind == b"IDAT":
            seen_data = True
        if kind == b"IEND":
            if length == 0 and seen_data and end == len(data):
                return data
            break
        offset = end
    raise ValueError("image_reply_denied")


def generate(payload):
    connection = None
    try:
        with request_deadline():
            body = validate_request(payload)
            key = SECRET.read_text().strip()
            if not key or len(key) > 4096 or any(char.isspace() for char in key):
                raise ValueError("image_provider_unavailable")
            connection = HTTPSConnection("api.openai.com", timeout=90)
            path = (
                "/v1/images/edits" if body.get("images") else "/v1/images/generations"
            )
            connection.request(
                "POST",
                path,
                body=json.dumps(body, allow_nan=False).encode(),
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            # No HTTP redirects, proxies, follow-up fetches or retries.
            if response.status != 200:
                raise ValueError("image_provider_unavailable")
            raw = response.read(MAX_REPLY + 1)
            if len(raw) > MAX_REPLY:
                raise ValueError("image_reply_denied")
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("data"), list)
                or len(value["data"]) != 1
            ):
                raise ValueError("image_reply_denied")
            encoded = value["data"][0].get("b64_json")
            if not isinstance(encoded, str) or len(encoded) > 4 * (
                (MAX_IMAGE + 2) // 3
            ):
                raise ValueError("image_reply_denied")
            data = base64.b64decode(encoded, validate=True)
            validate_png(data, payload["size"])
            return {
                "ok": True,
                "mime_type": "image/png",
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
    except Exception:  # noqa: BLE001 - Do not return raw provider, request, filesystem or credential errors.
        return {"ok": False, "error": "image_generation_unavailable"}
    finally:
        if connection:
            connection.close()
