"""Image-only processes: slow paid calls never share the chat HTTPServer.

The bridge has no provider import, credential, SDK, arbitrary destination or egress.
Only the provider role imports the reviewed fixed OpenAI image implementation.
"""

import base64
import binascii
import json
import os
import signal
import socket
import struct
import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from operator_audio import read_json
from operator_protocol import bounded_json

MAX_BODY = 4 * 1024 * 1024
MAX_REPLY = 12 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
BRIDGE_SECONDS = 105
PROVIDER_SECONDS = 100
FAILURE = {"ok": False, "error": "image_generation_unavailable"}
SIZES = {"1024x1024", "1536x1024", "1024x1536"}
ASSETS = {
    "logo-white",
    "logo-transparent",
    "photo-aerial",
    "photo-entrance",
    "photo-gate",
}


class ImageDeadline(BaseException):
    """A total request budget cannot be swallowed by ordinary vendor handlers."""


@contextmanager
def deadline(seconds):
    if threading.current_thread() is not threading.main_thread():
        raise ImageDeadline("image_main_thread_required")

    def expired(*_):
        raise ImageDeadline("image_deadline")

    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    # A vendor helper also uses SIGALRM. The independent hard-stop cannot be
    # extended by a nested helper replacing/restoring its own signal timer.
    watchdog = threading.Timer(seconds + 1, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        watchdog.cancel()
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if timer[0]:
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.000001, timer[0] - (time.monotonic() - started)),
                timer[1],
            )


def provider_endpoint(url):
    """Only the fixed service or a strict loopback fixture may be selected at boot."""
    if (
        not isinstance(url, str)
        or not url.isascii()
        or any(char.isspace() for char in url)
    ):
        raise ValueError("image_endpoint_denied")
    try:
        parts = urlsplit(url)
        port, host = parts.port, parts.hostname
    except ValueError:
        raise ValueError("image_endpoint_denied") from None
    if (
        parts.scheme != "http"
        or not port
        or parts.path
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or parts.netloc != f"{host}:{port}"
        or url != f"http://{host}:{port}"
        or not (
            url == "http://image-provider:8083" or host in {"127.0.0.1", "localhost"}
        )
    ):
        raise ValueError("image_endpoint_denied")
    return host, port


def validate_frame(payload):
    """Inert bounded frame; the credential process additionally verifies asset hashes."""
    if not isinstance(payload, dict) or set(payload) != {
        "prompt",
        "reference_images",
        "size",
    }:
        raise ValueError("image_frame_denied")
    if (
        not isinstance(payload["prompt"], str)
        or not 1 <= len(payload["prompt"].strip()) <= 4000
        or "\x00" in payload["prompt"]
        or not isinstance(payload["size"], str)
        or payload["size"] not in SIZES
        or not isinstance(payload["reference_images"], list)
        or len(payload["reference_images"]) > 3
    ):
        raise ValueError("image_frame_denied")
    used = set()
    for item in payload["reference_images"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "mime_type", "data_base64"}
            or not isinstance(item["id"], str)
            or item["id"] not in ASSETS
            or item["id"] in used
            or item["mime_type"] not in {"image/png", "image/webp"}
            or not isinstance(item["data_base64"], str)
            or not 1 <= len(item["data_base64"]) <= MAX_BODY
        ):
            raise ValueError("image_frame_denied")
        used.add(item["id"])
    return payload


def checked_result(value, size):
    if (
        not isinstance(value, dict)
        or set(value) != {"ok", "mime_type", "data_base64"}
        or value["ok"] is not True
        or value["mime_type"] != "image/png"
        or not isinstance(value["data_base64"], str)
        or not 1 <= len(value["data_base64"]) <= 4 * ((MAX_IMAGE + 2) // 3)
    ):
        raise ValueError("image_reply_denied")
    data = base64.b64decode(value["data_base64"], validate=True)
    # The provider and API run the full chunk-checksum validator. This transport
    # also rejects a wrong signature, oversized bytes or unexpected dimensions.
    if (
        not 57 <= len(data) <= MAX_IMAGE
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[12:16] != b"IHDR"
        or struct.unpack("!I", data[8:12])[0] != 13
    ):
        raise ValueError("image_reply_denied")
    width, height = struct.unpack("!II", data[16:24])
    if f"{width}x{height}" != size:
        raise ValueError("image_reply_denied")
    return {
        "ok": True,
        "mime_type": "image/png",
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


class PrivateProvider:
    def __init__(self, url):
        host, self.port = provider_endpoint(url)
        self.ip = socket.gethostbyname(host)

    def generate(self, payload):
        raw = json.dumps(payload, allow_nan=False).encode()
        if len(raw) > MAX_BODY:
            raise ValueError("image_frame_denied")
        connection = HTTPConnection(self.ip, self.port, timeout=100)
        try:
            connection.request(
                "POST",
                "/images/generate",
                body=raw,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("image_provider_unavailable")
            raw = response.read(MAX_REPLY + 1)
            value = bounded_json(raw, MAX_REPLY)
            return checked_result(value, payload["size"])
        finally:
            connection.close()


class ImageServer(HTTPServer):
    request_queue_size = 4
    allow_reuse_address = True

    def __init__(self, address, role, *, provider_url=None):
        if role not in {"bridge", "provider"}:
            raise ValueError("image_role_denied")
        self._role = role
        self.provider = None
        self.generator = None
        if role == "bridge":
            self.provider = PrivateProvider(
                provider_url or "http://image-provider:8083"
            )
        else:
            # Never import this module in the secretless bridge or text process.
            from operator_images import generate

            self.generator = generate
        super().__init__(address, Handler)

    @property
    def role(self):
        return self._role


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "SaraImages"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def handle(self):
        # Header parsing itself is bounded, before endpoint-level budgets begin.
        try:
            with deadline(
                BRIDGE_SECONDS if self.server.role == "bridge" else PROVIDER_SECONDS
            ):
                signal.setitimer(signal.ITIMER_REAL, 5)
                super().handle()
        except ImageDeadline:
            self.close_connection = True

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        raw = json.dumps(body, allow_nan=False).encode()
        if len(raw) > MAX_REPLY:
            status, raw = 502, json.dumps(FAILURE).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def do_GET(self):
        if self.path != "/health":
            return self.reply(404, {"ok": False, "error": "route_denied"})
        # Liveness only: no credential read or network call even in provider mode.
        self.reply(200, {"ok": True, "role": self.server.role})

    def do_POST(self):
        path = "/generate-image" if self.server.role == "bridge" else "/images/generate"
        if self.path != path:
            return self.reply(404, {"ok": False, "error": "route_denied"})
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
            with deadline(
                BRIDGE_SECONDS if self.server.role == "bridge" else PROVIDER_SECONDS
            ):
                try:
                    payload = validate_frame(read_json(self, MAX_BODY, body_seconds=5))
                except (ValueError, TypeError, OSError, RecursionError):
                    return self.reply(
                        400, {"ok": False, "error": "image_request_denied"}
                    )
                if self.server.role == "bridge":
                    result = checked_result(
                        self.server.provider.generate(payload), payload["size"]
                    )
                else:
                    result = checked_result(
                        self.server.generator(payload), payload["size"]
                    )
                self.reply(200, result)
        except ImageDeadline:
            self.reply(502, FAILURE)
        except (Exception, binascii.Error):  # noqa: BLE001 - Never return vendor errors.
            self.reply(502, FAILURE)


def main():
    role = os.environ.get("IMAGE_ROLE")
    if role not in {"bridge", "provider"}:
        raise SystemExit("IMAGE_ROLE must be bridge or provider")
    server = ImageServer(
        ("0.0.0.0", 8082 if role == "bridge" else 8083),
        role,
        provider_url=os.environ.get("IMAGE_PROVIDER_URL") if role == "bridge" else None,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
