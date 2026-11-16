"""Private generated pixels travel once to the verified developer's source thread."""

# ruff: noqa: F811
import base64
import copy
import json
from contextlib import nullcontext
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from test_crm import authenticated  # noqa: F401
from test_sara_images import png
from test_whatsapp_agent import configured  # noqa: F401
from test_whatsapp_developer import call, issue
from test_workflow_social import vendor  # noqa: F401


def prepared(monkeypatch):
    from app.social import media, workflow

    credentials = {"api_key": "private-fixture", "webhook_secret": "fixture-signature"}
    reply = {
        "kind": "social_message",
        "platform": "whatsapp",
        "account_id": "a" * 24,
        "conversation_id": "thread/opaque:1",
        "credential_revision": "revision",
        "payload": {"accountId": "a" * 24, "message": media.CAPTION},
    }

    def isolated(frame):
        if frame["operation"] == "prepare":
            return copy.deepcopy(reply)
        return media._transmit(
            frame["plan"],
            base64.b64decode(frame["data_base64"]),
            frame["credentials"],
            frame["request_id"],
        )

    monkeypatch.setattr(media, "_isolated", isolated)
    monkeypatch.setattr(workflow, "_check", lambda *_: None)
    monkeypatch.setattr(media.config, "required", lambda: credentials)
    monkeypatch.setattr(media.config, "locked", nullcontext)
    data = png()
    image = {"id": uuid4(), "data": data, "image_size": "1024x1024"}
    return (
        media,
        media.prepare(
            None,
            {
                "id": str(uuid4()),
                "account_id": "a" * 24,
                "conversation_id": "thread/opaque:1",
                "participant_id": "573001110001",
            },
            image,
        ),
        data,
    )


def capture(monkeypatch, media, *, response=None, timeout=False):
    calls = []

    class Response:
        status = 201

        def close(self):
            pass

        def read(self, maximum):
            return json.dumps(
                response
                or {
                    "success": True,
                    "data": {
                        "messageId": "wamid.image",
                        "conversationId": "thread/opaque:1",
                        "attachments": [{"url": "https://vendor.example/private-diagnostics"}],
                    },
                }
            ).encode()[:maximum]

    class Connection:
        sock = None

        def connect(self):
            pass

        def request(self, method, path, body=None, headers=None):
            calls.append((method, path, body, headers))

        def getresponse(self):
            if timeout:
                raise TimeoutError("private credential upstream diagnostics")
            return Response()

        def close(self):
            pass

    def connection(host, timeout):
        assert host == "zernio.com" and 0 < timeout <= 12
        return Connection()

    monkeypatch.setattr(media, "https_connection", connection)
    return calls


def test_multipart_exact_original_bytes_and_bound_recipient(monkeypatch):
    media, plan, data = prepared(monkeypatch)
    calls = capture(monkeypatch, media)
    result = media.submit(plan, data, "image-" + plan["image_id"])
    assert result == {
        "state": "completed",
        "receipt": {
            "status": "accepted",
            "message_id": "wamid.image",
            "conversation_id": "thread/opaque:1",
        },
    }
    method, path, body, headers = calls[0]
    assert method == "POST" and path == "/api/v1/inbox/conversations/thread%2Fopaque%3A1/messages"
    assert headers["Idempotency-Key"] == "image-" + plan["image_id"]
    parsed = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + body
    )
    parts = {p.get_param("name", header="content-disposition"): p for p in parsed.iter_parts()}
    assert set(parts) == {"accountId", "message", "attachment"}
    assert parts["accountId"].get_payload(decode=True) == b"a" * 24
    assert parts["message"].get_payload(decode=True).decode() == media.CAPTION
    assert parts["attachment"].get_payload(decode=True) == data
    assert parts["attachment"].get_content_type() == "image/png"
    assert parts["attachment"].get_filename() == "jardines-" + plan["image_id"] + ".png"
    assert b"attachmentUrl" not in body and b"attachmentType" not in body
    assert "vendor.example" not in str(result)


@pytest.mark.parametrize("mutation", ["bytes", "recipient", "caption", "oversized", "mime"])
def test_changed_or_oversized_media_never_sends(monkeypatch, mutation):
    media, plan, data = prepared(monkeypatch)
    calls = capture(monkeypatch, media)
    if mutation == "bytes":
        data = png() + b"tamper"
    elif mutation == "recipient":
        plan["reply"]["conversation_id"] = "foreign"
    elif mutation == "caption":
        plan["reply"]["payload"]["message"] = "changed"
    elif mutation == "mime":
        plan["mime_type"] = "application/pdf"
    else:
        data = b"x" * 5_000_001
    with pytest.raises(HTTPException):
        media.submit(plan, data, "image-" + plan["image_id"])
    assert calls == []


def test_ambiguous_submission_is_not_reported_delivered_or_retried(monkeypatch):
    media, plan, data = prepared(monkeypatch)
    calls = capture(monkeypatch, media, timeout=True)
    assert media.submit(plan, data, "image-" + plan["image_id"]) == {
        "state": "unknown",
        "receipt": {},
        "error": "image_delivery_unknown",
    }
    assert len(calls) == 1


def test_provider_wrong_conversation_cannot_confirm_submission(monkeypatch):
    media, plan, data = prepared(monkeypatch)
    calls = capture(
        monkeypatch,
        media,
        response={
            "success": True,
            "data": {"messageId": "wamid.image", "conversationId": "other-thread"},
        },
    )
    assert media.submit(plan, data, "image-" + plan["image_id"])["state"] == "unknown"
    assert len(calls) == 1


def generated(configured, monkeypatch, data=None):
    from app.images import worker

    client, owner, source, _channel, _run, headers = issue(configured, monkeypatch)
    assert client.post("/internal/hermes/claim", json={}, headers=headers).status_code == 200
    image = call(
        client,
        headers,
        "images.generate",
        {"request_id": str(uuid4()), "prompt": "A brand concept"},
    )
    assert image.status_code == 200, image.text
    receipt = image.json()["result"]
    assert (
        client.post(
            "/internal/hermes/finish", json={"reply": "Concepto en preparación."}, headers=headers
        ).status_code
        == 200
    )
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.whatsapp_agent_jobs SET state='completed' WHERE id=%s", (source["id"],)
        )
    monkeypatch.setattr(worker.bridge, "generate", lambda _: data if data is not None else png())
    assert worker.tick()
    return client, owner, source, receipt


def outbox(owner, identifier):
    from psycopg.rows import dict_row

    with psycopg.connect(owner, row_factory=dict_row) as db:
        return db.execute(
            "SELECT * FROM crm.sara_image_deliveries WHERE image_id=%s", (identifier,)
        ).fetchone()


def stub_media(monkeypatch, owner, identifier):
    from app.social import media

    sent = []

    def prepare(db, source, image):
        return {"reply": {"credential_revision": source["credential_revision"]}}

    def submit(plan, data, request_id):
        assert outbox(owner, identifier)["state"] == "reserved", (
            "Reservation must commit before external POST"
        )
        assert data == png()
        sent.append(request_id)
        return {
            "state": "completed",
            "receipt": {"status": "accepted", "message_id": "wamid.image"},
        }

    monkeypatch.setattr(media, "prepare", prepare)
    monkeypatch.setattr(media, "submit", submit)
    return sent


def test_actual_developer_generation_enqueues_once_and_reserves_before_send(
    configured, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from app.images import delivery

    client, owner, _source, image = generated(configured, monkeypatch)
    assert outbox(owner, image["id"])["state"] == "pending"
    sent = stub_media(monkeypatch, owner, image["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: delivery.tick(), range(2)))
    assert len(sent) == 1 and outbox(owner, image["id"])["state"] == "completed"
    delivery.tick()
    assert len(sent) == 1
    receipt = client.get("/crm/images/" + image["id"]).json()
    assert receipt["whatsapp_delivery"]["state"] == "completed"
    assert receipt["whatsapp_delivery"]["accepted"] is True
    assert "participant_id" not in str(receipt)


@pytest.mark.parametrize(
    "mutation", ["developer", "owner", "channel", "credentials", "hash", "handover", "window"]
)
def test_live_revocation_and_target_change_blocks_outbound(configured, monkeypatch, mutation):
    from app.images import delivery
    from app.social import media

    _client, owner, _source, image = generated(configured, monkeypatch)
    sent = stub_media(monkeypatch, owner, image["id"])
    with psycopg.connect(owner) as db:
        if mutation == "developer":
            db.execute(
                "UPDATE crm.whatsapp_agent SET document=jsonb_set(document,'{developers}','[]')"
            )
        elif mutation == "owner":
            db.execute("UPDATE crm.users SET enabled=false")
        elif mutation == "channel":
            db.execute("UPDATE crm.whatsapp_agent SET enabled=false")
        elif mutation == "hash":
            db.execute(
                "UPDATE crm.sara_image_jobs SET data=%s WHERE id=%s",
                (png() + b"changed", image["id"]),
            )
        elif mutation == "credentials":
            configured[2]["api_key"] = "rotated"
    if mutation in {"handover", "window"}:

        def rejected(*_):
            raise HTTPException(409, "zernio_" + mutation + "_changed")

        monkeypatch.setattr(media, "prepare", rejected)
    delivery.tick()
    assert not sent and outbox(owner, image["id"])["state"] == "blocked"


def test_interrupted_reservation_never_replays(configured, monkeypatch):
    from app.images import delivery

    _client, owner, _source, image = generated(configured, monkeypatch)
    sent = stub_media(monkeypatch, owner, image["id"])
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.sara_image_deliveries SET state='reserved',claimed_at=now()-interval '4 minutes' WHERE image_id=%s",
            (image["id"],),
        )
    delivery.tick()
    delivery.tick()
    assert not sent and outbox(owner, image["id"])["state"] == "unknown"


def test_web_image_has_no_implicit_whatsapp_recipient(authenticated, monkeypatch):
    from app.images import worker

    client, owner, _ = authenticated
    from app.crm.database import connect

    with connect() as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='hermes'")
    receipt = client.post(
        "/crm/images", json={"request_id": str(uuid4()), "prompt": "Web-only concept"}
    ).json()
    monkeypatch.setattr(worker.bridge, "generate", lambda _: png())
    assert worker.tick()
    assert outbox(owner, receipt["id"]) is None


def test_oversized_valid_png_stays_private_without_regeneration_or_upload(configured, monkeypatch):
    import struct
    import zlib

    from app.images import delivery
    from app.images.png import validate_png

    original = png()
    payload = b"x" * 5_000_001
    ancillary = (
        struct.pack("!I", len(payload))
        + b"tEXt"
        + payload
        + struct.pack("!I", zlib.crc32(b"tEXt" + payload))
    )
    data = original[:-12] + ancillary + original[-12:]
    assert validate_png(data, "1024x1024") == data
    client, owner, _source, image = generated(configured, monkeypatch, data)
    sent = stub_media(monkeypatch, owner, image["id"])
    assert not delivery.tick()
    row = outbox(owner, image["id"])
    assert row["state"] == "blocked" and row["error"] == "image_exceeds_whatsapp_limit"
    assert client.get("/crm/images/" + image["id"] + "/content").content == data
    assert not sent


def test_final_guard_rechecks_revocation_after_preparation(configured, monkeypatch):
    from app.images import delivery
    from app.social import media

    _client, owner, _source, image = generated(configured, monkeypatch)
    sent = stub_media(monkeypatch, owner, image["id"])
    original = media.prepare

    def prepare(db, source, row):
        result = original(db, source, row)
        with psycopg.connect(owner) as connection:
            connection.execute("UPDATE crm.whatsapp_agent SET enabled=false")
        return result

    monkeypatch.setattr(media, "prepare", prepare)
    delivery.tick()
    assert not sent and outbox(owner, image["id"])["state"] == "blocked"


def test_runtime_cannot_rewrite_delivery_recipient_or_content_binding(configured, monkeypatch):
    from app.crm.database import connect

    _client, owner, _source, image = generated(configured, monkeypatch)
    before = outbox(owner, image["id"])
    for column, value in [
        ("binding", "'{}'::jsonb"),
        ("content_hash", "repeat('0',64)"),
        ("origin_run_id", "gen_random_uuid()"),
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connect() as db:
            db.execute(
                f"UPDATE crm.sara_image_deliveries SET {column}={value} WHERE image_id=%s",
                (image["id"],),
            )
    assert outbox(owner, image["id"]) == before


@pytest.mark.parametrize("mutation", ["none", "handover", "window"])
def test_actual_workflow_media_checks_live_window_and_control(
    vendor, configured, monkeypatch, mutation
):
    from datetime import UTC, datetime, timedelta

    from app.images import delivery
    from app.social import media
    from app.social.media_process import execute

    monkeypatch.setattr(media, "_isolated", execute)
    _client, owner, source, image = generated(configured, monkeypatch)
    vendor["conversations"] = [
        {
            "id": source["conversation_id"],
            "accountId": source["account_id"],
            "platform": "whatsapp",
            "participantId": source["participant_id"],
            "threadControl": "app",
        }
    ]
    vendor["messages"] = [
        {
            "id": "incoming.1",
            "conversationId": source["conversation_id"],
            "accountId": source["account_id"],
            "platform": "whatsapp",
            "senderId": source["participant_id"],
            "direction": "incoming",
            "createdAt": datetime.now(UTC).isoformat(),
        }
    ]
    calls = capture(
        monkeypatch,
        media,
        response={
            "success": True,
            "data": {"messageId": "wamid.actual", "conversationId": source["conversation_id"]},
        },
    )
    # A real prepared plan must still reject a human takeover at the final check.
    actual = media.prepare

    def prepare(db, src, img):
        plan = actual(db, src, img)
        if mutation == "handover":
            vendor["conversations"][0]["threadControl"] = "human"
        elif mutation == "window":
            vendor["messages"][0]["createdAt"] = (
                datetime.now(UTC) - timedelta(hours=25)
            ).isoformat()
        return plan

    monkeypatch.setattr(media, "prepare", prepare)
    delivery.tick()
    expected = "completed" if mutation == "none" else "unknown"
    assert len(calls) == (1 if mutation == "none" else 0)
    assert outbox(owner, image["id"])["state"] == expected
    # A terminal reservation is never replayed, even when control returns.
    vendor["conversations"][0]["threadControl"] = "app"
    vendor["messages"][0]["createdAt"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    delivery.tick()
    assert len(calls) == (1 if mutation == "none" else 0)


def real_child_fixture(monkeypatch, media, original, setup):
    """Only this test injects loopback networking into the fixed trusted child."""
    actual_run = media.subprocess.run

    def run(command, **kwargs):
        assert command[1:3] == ["-I", "-B"]
        assert "private-fixture" not in str(command) and "api_key" not in kwargs["env"]
        script = (
            "import sys;sys.path.insert(0,sys.argv[1]);"
            "from app.social import media,workflow;"
            "workflow._check=lambda *args:None;\n"
            + setup
            + "\nfrom app.social.media_process import main;main()"
        )
        command = list(command)
        command[command.index("-c") + 1] = script
        return actual_run(command, **kwargs)

    monkeypatch.setattr(media.subprocess, "run", run)
    monkeypatch.setattr(media, "_isolated", original)
    monkeypatch.setattr(media, "SEND_TIMEOUT", 0.8)


def test_process_deadline_bounds_dns_and_kills_before_late_send(monkeypatch, tmp_path):
    import os
    import time

    from app.social import media

    original = media._isolated
    media, plan, data = prepared(monkeypatch)
    marker = tmp_path / "dns-entered"
    setup = f"""
import http.client,os,socket,time
from pathlib import Path
original_dns=socket.getaddrinfo
def slow_dns(host,*args,**kwargs):
    assert host=='zernio-egress'
    Path({str(marker)!r}).write_text(str(os.getpid()))
    time.sleep(3)
    return original_dns('127.0.0.1',*args,**kwargs)
socket.getaddrinfo=slow_dns
def connection(host,timeout):
    assert host=='zernio.com'
    return http.client.HTTPConnection('zernio-egress',1,timeout=3)
media.https_connection=connection
"""
    real_child_fixture(monkeypatch, media, original, setup)
    started = time.monotonic()
    assert media.submit(plan, data, "image-" + plan["image_id"])["state"] == "unknown"
    assert time.monotonic() - started < 1.5
    assert marker.exists(), "Probe must reach real DNS setup, not just fail child startup"
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_process_deadline_bounds_body_after_connection_close(monkeypatch):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.social import media

    original = media._isolated
    media, plan, data = prepared(monkeypatch)
    entered = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.send_header("Content-Length", "10000")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            entered.set()
            release.wait(3)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    setup = f"""
import http.client
def connection(host,timeout):
    assert host=='zernio.com'
    return http.client.HTTPConnection('127.0.0.1',{server.server_port},timeout=3)
media.https_connection=connection
"""
    real_child_fixture(monkeypatch, media, original, setup)
    try:
        started = time.monotonic()
        assert media.submit(plan, data, "image-" + plan["image_id"])["state"] == "unknown"
        assert time.monotonic() - started < 1.5 and entered.is_set()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(1)
