"""Process-isolated image handlers retain main-thread signal deadline protection."""

import base64
import importlib
import json
import multiprocessing
import struct
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops/hermes"))
images = importlib.import_module("image_server")


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


def call(url, path="/health", payload=None, timeout=3, headers=None):
    request = Request(
        url + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=timeout) as reply:
            return reply.status, json.load(reply)
    except HTTPError as error:
        return error.code, json.load(error)


def child(
    ready,
    role,
    provider_url=None,
    entered=None,
    release=None,
    slow=False,
    shorten=False,
):
    # Child process main thread owns the real production HTTPServer and SIGALRM.
    import operator_images

    def generate(payload):
        assert threading.current_thread() is threading.main_thread()
        if entered:
            entered.set()
            assert release.wait(8)
        if slow:
            time.sleep(2)
        return {
            "ok": True,
            "mime_type": "image/png",
            "data_base64": base64.b64encode(png()).decode(),
        }

    operator_images.generate = generate
    if shorten:
        images.PROVIDER_SECONDS = 0.1
    server = images.ImageServer(("127.0.0.1", 0), role, provider_url=provider_url)
    ready.put(server.server_port)
    server.serve_forever()


@pytest.fixture
def launch():
    processes = []
    context = multiprocessing.get_context("fork")

    def start(role, **kwargs):
        ready = context.Queue()
        process = context.Process(target=child, args=(ready, role), kwargs=kwargs)
        process.start()
        processes.append(process)
        return f"http://127.0.0.1:{ready.get(timeout=5)}"

    yield start
    for process in processes:
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)


def test_exact_image_routes_and_bad_frames(launch):
    provider = launch("provider")
    bridge = launch("bridge", provider_url=provider)
    assert call(provider)[1] == {"ok": True, "role": "provider"}
    assert call(bridge)[1] == {"ok": True, "role": "bridge"}
    payload = {"prompt": "Concept", "reference_images": [], "size": "1024x1024"}
    status, result = call(bridge, "/generate-image", payload)
    assert status == 200 and result["data_base64"] == base64.b64encode(png()).decode()
    for endpoint in (
        "/images/generate",
        "/generate-image?x=1",
        "/public-reply",
        "/run",
    ):
        assert call(bridge, endpoint, payload)[0] == 404
    assert call(provider, "/generate-image", payload)[0] == 404
    assert call(provider, "/images/generate?x=1", payload)[0] == 404
    assert (
        call(bridge, "/generate-image", {"url": "https://untrusted.example"})[0] == 400
    )
    from http.client import HTTPConnection
    from urllib.parse import urlsplit

    parsed = urlsplit(bridge)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        connection.putrequest("POST", "/generate-image")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(images.MAX_BODY + 1))
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"] == "image_request_denied"
    finally:
        connection.close()


def test_blocked_image_generation_does_not_block_text_server(launch):
    context = multiprocessing.get_context("fork")
    entered, release = context.Event(), context.Event()
    provider = launch("provider", entered=entered, release=release)
    bridge = launch("bridge", provider_url=provider)
    # Existing text server handler remains synchronous and unchanged, independently.
    ready = context.Queue()

    def text_server():
        from types import SimpleNamespace
        from unittest.mock import Mock

        import operator_provider

        operator_provider.ready = lambda: True
        operator_provider.SECRET = SimpleNamespace(read_text=lambda: "fake-test-key")
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Text still responsive",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode()
        operator_provider.HTTPSConnection = lambda *args, **kwargs: connection
        server = operator_provider.HTTPServer(
            ("127.0.0.1", 0), operator_provider.Handler
        )
        ready.put(server.server_port)
        server.serve_forever()

    process = context.Process(target=text_server)
    process.start()
    text_url = f"http://127.0.0.1:{ready.get(timeout=5)}"
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                call,
                bridge,
                "/generate-image",
                {"prompt": "Concept", "reference_images": [], "size": "1024x1024"},
                8,
            )
            assert entered.wait(5)
            started = time.monotonic()
            assert call(text_url)[0] == 200
            from operator_protocol import MODEL

            text_payload = {
                "model": MODEL,
                "messages": [{"role": "user", "content": "Read workspace"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "jardines_app",
                            "description": "Read workspace",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": ["crm.workspace"],
                                    },
                                    "arguments": {"type": "object"},
                                },
                                "required": ["action", "arguments"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
            }
            status, text_reply = call(
                text_url,
                "/v1/chat/completions",
                text_payload,
                headers={"Authorization": "Bearer " + "a" * 32},
            )
            assert status == 200
            assert (
                text_reply["choices"][0]["message"]["content"]
                == "Text still responsive"
            )
            assert time.monotonic() - started < 1.5
            assert not future.done()
            release.set()
            assert future.result(timeout=5)[0] == 200
    finally:
        release.set()
        process.terminate()
        process.join(5)


def test_real_main_thread_deadline_bounds_generation(launch):
    provider = launch("provider", slow=True, shorten=True)
    started = time.monotonic()
    status, value = call(
        provider,
        "/images/generate",
        {"prompt": "Concept", "reference_images": [], "size": "1024x1024"},
    )
    assert status == 502 and value == {
        "ok": False,
        "error": "image_generation_unavailable",
    }
    assert time.monotonic() - started < 1
    assert call(provider)[0] == 200


def test_server_role_and_provider_endpoint_fail_closed():
    for role in ("", "text", "provider "):
        with pytest.raises(ValueError):
            images.ImageServer(("127.0.0.1", 0), role)
    for url in (
        "https://image-provider:8083",
        "http://api:8000",
        "http://image-provider:8083/a",
        "http://u@127.0.0.1:1",
        "http://127.0.0.1:1?x=1",
    ):
        with pytest.raises(ValueError):
            images.provider_endpoint(url)


def test_compose_uses_disjoint_network_and_secret_boundaries():
    import subprocess

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "ops/hermes/operator.compose.yaml"),
            "config",
            "--format",
            "json",
        ],
        env={
            **__import__("os").environ,
            "HERMES_OPENAI_SECRET_FILE": "/tmp/not-a-real-secret",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(result.stdout)
    services = config["services"]
    bridge, provider = services["image-bridge"], services["image-provider"]
    assert set(bridge["networks"]) == {"images", "application"}
    assert set(provider["networks"]) == {"images", "egress"}
    assert (
        not bridge.get("secrets")
        and not bridge.get("ports")
        and not provider.get("ports")
    )
    assert provider["secrets"][0]["source"] == "openai_api_key"
    assert config["networks"]["images"]["internal"] is True
    for name, role in (("image-bridge", "bridge"), ("image-provider", "provider")):
        service = services[name]
        assert service["environment"]["IMAGE_ROLE"] == role
        assert service["read_only"] and service["user"] == "1000:1000"
        assert service["cap_drop"] == ["ALL"]
        assert "@sha256:" in service["image"]
    mounted = {item["target"]: item for item in provider["volumes"]}
    assert mounted["/opt/jardines-images/brand"]["read_only"]
    # Compose versions differ: normalized JSON can omit a false Go bool.
    # Keep the authored fail-closed setting explicit; never accept normalized true.
    assert (
        "bind: { create_host_path: false }"
        in (ROOT / "ops/hermes/operator.compose.yaml").read_text()
    )
    assert (
        mounted["/opt/jardines-images/brand"]
        .get("bind", {})
        .get("create_host_path", False)
        is False
    )
    for name in ("hermes-bridge", "operator-provider"):
        assert not any(
            "operator_images" in item["target"] or "jardines-images" in item["target"]
            for item in services[name]["volumes"]
        )


@pytest.mark.parametrize("host_path", ["omitted", False, True])
def test_compose_host_path_serialization_preserves_fail_closed_check(
    monkeypatch, host_path
):
    import os
    import subprocess
    from types import SimpleNamespace

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "ops/hermes/operator.compose.yaml"),
            "config",
            "--format",
            "json",
        ],
        env={**os.environ, "HERMES_OPENAI_SECRET_FILE": "/tmp/not-a-real-secret"},
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(result.stdout)
    mount = next(
        item
        for item in config["services"]["image-provider"]["volumes"]
        if item["target"] == "/opt/jardines-images/brand"
    )
    binding = mount.setdefault("bind", {})
    if host_path == "omitted":
        binding.pop("create_host_path", None)
    else:
        binding["create_host_path"] = host_path
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(config)),
    )
    if host_path is True:
        with pytest.raises(AssertionError):
            test_compose_uses_disjoint_network_and_secret_boundaries()
    else:
        test_compose_uses_disjoint_network_and_secret_boundaries()
