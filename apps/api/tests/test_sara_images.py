"""Image jobs use owned assets and committed, non-replayable reservations."""

# ruff: noqa: F811

import base64
import struct
import zlib
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from test_crm import authenticated  # noqa: F401

from app.images import assets, models, service, worker
from app.images.png import validate_png


def png(width=1024, height=1024):
    def chunk(kind, data):
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * width * 3) * height))
        + chunk(b"IEND", b"")
    )


def test_manifest_rejects_paths_and_unknown_ids():
    for value in ("../brand/logo.png", "https://example.com/a.png", "/etc/passwd", "poster"):
        with pytest.raises(HTTPException):
            assets.get(value)
    entries = assets.catalog()
    assert {entry["kind"] for entry in entries} == {"logo", "photo"}
    for entry in entries:
        assert len(entry["sha256"]) == 64
        assert assets.get(entry["id"])[1]


def test_models_reject_unbounded_or_duplicate_inputs():
    for values in (
        {"prompt": "x" * 2001},
        {"reference_ids": ["../secret"]},
        {"reference_ids": ["logo-white", "logo-white"]},
        {"size": "auto"},
        {"n": 2},
        {"model": "arbitrary"},
    ):
        with pytest.raises(ValidationError):
            models.Generate.model_validate(
                {"request_id": str(uuid4()), "prompt": "concept", **values}
            )


def test_png_limits_dimensions_and_structure():
    assert validate_png(png(), "1024x1024")
    for data in (b"not PNG", png(1, 1), png()[:-5], b"x" * (8 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            validate_png(data, "1024x1024")


def test_owner_status_has_no_global_lookup():
    db = Mock()
    db.execute.return_value.fetchone.return_value = None
    owner = uuid4()
    with pytest.raises(HTTPException) as caught:
        service.status(db, uuid4(), {"id": owner})
    assert caught.value.status_code == 404
    assert "owner_id=%s" in db.execute.call_args.args[0]
    assert db.execute.call_args.args[1][1] == owner


def test_duplicate_request_conflict_and_rate_limit(monkeypatch):
    monkeypatch.setattr(service.control, "lock", lambda db: None)
    monkeypatch.setattr(service.control, "require_connections", lambda *args: None)
    args = models.Generate(request_id=uuid4(), prompt="concept")
    db = Mock()
    db.execute.return_value.fetchone.return_value = {"payload_hash": "different"}
    with pytest.raises(HTTPException) as caught:
        service.enqueue(db, args, {"id": uuid4()})
    assert caught.value.status_code == 409
    db.execute.return_value.fetchone.side_effect = [None, {"total": 5}]
    with pytest.raises(HTTPException) as caught:
        service.enqueue(db, args, {"id": uuid4()})
    assert caught.value.status_code == 429


def test_tick_commits_claim_before_io_and_never_replays(monkeypatch):
    events = []
    row = {"id": uuid4(), "prompt": "concept", "reference_ids": [], "image_size": "1024x1024"}
    db = Mock()

    @contextmanager
    def connection():
        events.append("open")
        yield db
        events.append("commit")

    monkeypatch.setattr(worker, "connect", connection)
    monkeypatch.setattr(worker, "claim", lambda db: row)

    def call(payload):
        assert events == ["open", "commit"]
        events.append("io")
        raise TimeoutError("vendor secret error")

    monkeypatch.setattr(worker.bridge, "generate", call)
    worker.tick()
    assert db.execute.call_args.args[1][0] == "unknown"
    assert "vendor secret" not in str(db.execute.call_args)


def test_recover_only_abandoned_processing_and_claim_only_queued(monkeypatch):
    monkeypatch.setattr(worker.control, "lock", lambda db: None)
    db = Mock()
    db.execute.return_value.fetchone.return_value = None
    assert worker.claim(db) is None
    statements = "\n".join(call.args[0] for call in db.execute.call_args_list)
    assert "status='unknown'" in statements
    assert "status='processing'" in statements
    assert "WHERE status='queued'" in statements
    assert "SKIP LOCKED" in statements


def test_same_request_returns_existing_receipt_without_insert(monkeypatch):
    monkeypatch.setattr(service.control, "lock", lambda db: None)
    monkeypatch.setattr(service.control, "require_connections", lambda *args: None)
    args = models.Generate(request_id=uuid4(), prompt="concept")
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(
            args.model_dump(mode="json", exclude={"request_id"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    row = {
        "id": uuid4(),
        "payload_hash": digest,
        "status": "queued",
        "reference_ids": [],
        "reference_versions": {},
        "image_size": "1024x1024",
    }
    db = Mock()
    db.execute.return_value.fetchone.return_value = row
    assert service.enqueue(db, args, {"id": uuid4()})["id"] == str(row["id"])
    assert db.execute.call_count == 1


def test_private_bytes_never_leak_across_owners():
    db = Mock()
    db.execute.return_value.fetchone.return_value = None
    owner = uuid4()
    with pytest.raises(HTTPException) as caught:
        service.content(db, uuid4(), {"id": owner})
    assert caught.value.status_code == 404
    assert "owner_id=%s AND status='completed'" in db.execute.call_args.args[0]
    assert db.execute.call_args.args[1][1] == owner


def test_private_transport_fixed_route_proxy_policy_and_png(monkeypatch):
    import json

    from app.images import bridge

    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(
        {"ok": True, "mime_type": "image/png", "data_base64": base64.b64encode(png()).decode()}
    ).encode()
    opener = Mock()
    opener.open.return_value = response

    def build(*handlers):
        assert handlers[0].proxies == {}
        return opener

    monkeypatch.setattr(bridge, "build_opener", build)
    monkeypatch.setenv("HERMES_IMAGE_BRIDGE_URL", "http://image-bridge:8082")
    assert (
        bridge.generate({"prompt": "concept", "reference_images": [], "size": "1024x1024"}) == png()
    )
    req = opener.open.call_args.args[0]
    assert req.full_url == "http://image-bridge:8082/generate-image"
    assert opener.open.call_args.kwargs["timeout"] == 110
    response.read.return_value = b" " * (bridge.MAX_REPLY + 1)
    with pytest.raises(HTTPException):
        bridge.generate({"prompt": "concept", "reference_images": [], "size": "1024x1024"})
    monkeypatch.setenv("HERMES_IMAGE_BRIDGE_URL", "https://untrusted.example")
    with pytest.raises(HTTPException):
        bridge.generate({})


@pytest.fixture
def image_db(authenticated):
    _, owner_url, _ = authenticated
    with psycopg.connect(owner_url) as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='hermes'")
        owner = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()[0]
    return owner_url, {"id": owner}


def test_database_jobs_idempotency_cap_and_owner_bytes(image_db):
    from app.crm.database import connect

    owner_url, admin = image_db
    args = models.Generate(request_id=uuid4(), prompt="No invented commercial claims")
    with connect() as db:
        first = service.enqueue(db, args, admin)
    with connect() as db:
        assert service.enqueue(db, args, admin) == first
    with connect() as db, pytest.raises(HTTPException) as caught:
        service.enqueue(db, args.model_copy(update={"prompt": "Different"}), admin)
    assert caught.value.status_code == 409
    for _ in range(4):
        with connect() as db:
            service.enqueue(db, models.Generate(request_id=uuid4(), prompt="Concept"), admin)
    with connect() as db, pytest.raises(HTTPException) as caught:
        service.enqueue(db, models.Generate(request_id=uuid4(), prompt="Sixth"), admin)
    assert caught.value.status_code == 429
    with psycopg.connect(owner_url) as db:
        other = db.execute(
            "INSERT INTO crm.users(username,password_hash) VALUES('other-image-owner','not-used') RETURNING id"
        ).fetchone()[0]
        db.execute(
            "UPDATE crm.sara_image_jobs SET status='completed',data=%s WHERE id=%s",
            (png(), first["id"]),
        )
    for function in (service.status, service.content):
        with connect() as db, pytest.raises(HTTPException) as caught:
            function(db, first["id"], {"id": other})
        assert caught.value.status_code == 404
    with connect() as db:
        result = service.status(db, first["id"], admin)
        assert result["status"] == "completed" and result["size"] == len(png())
        assert service.content(db, first["id"], admin) == png()


def test_database_committed_claim_single_call_then_unknown_no_replay(image_db, monkeypatch):
    from app.crm.database import connect

    _, admin = image_db
    with connect() as db:
        queued = service.enqueue(db, models.Generate(request_id=uuid4(), prompt="Concept"), admin)
    calls = []

    def call(payload):
        with connect() as separate:
            assert service.status(separate, queued["id"], admin)["status"] == "processing"
        calls.append(payload)
        raise TimeoutError("sanitized")

    monkeypatch.setattr(worker.bridge, "generate", call)
    assert worker.tick() is True
    assert worker.tick() is False
    assert len(calls) == 1
    with connect() as db:
        assert service.status(db, queued["id"], admin)["status"] == "unknown"


def test_database_abandoned_processing_is_unknown_not_redispatched(image_db, monkeypatch):
    from app.crm.database import connect

    owner_url, admin = image_db
    with connect() as db:
        queued = service.enqueue(db, models.Generate(request_id=uuid4(), prompt="Concept"), admin)
    with psycopg.connect(owner_url) as db:
        db.execute(
            "UPDATE crm.sara_image_jobs SET status='processing',claimed_at=now()-interval '181 seconds' WHERE id=%s",
            (queued["id"],),
        )
    call = Mock()
    monkeypatch.setattr(worker.bridge, "generate", call)
    assert worker.tick() is False
    assert not call.called
    with connect() as db:
        assert service.status(db, queued["id"], admin)["status"] == "unknown"


def test_database_concurrent_workers_only_one_provider_call(image_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.crm.database import connect

    _, admin = image_db
    with connect() as db:
        queued = service.enqueue(db, models.Generate(request_id=uuid4(), prompt="Concept"), admin)
    entered, release = Event(), Event()
    calls = []

    def call(payload):
        calls.append(payload)
        entered.set()
        assert release.wait(5)
        return png()

    monkeypatch.setattr(worker.bridge, "generate", call)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.tick)
        assert entered.wait(5)
        second = pool.submit(worker.tick)
        try:
            assert second.result(timeout=5) is False
        finally:
            release.set()
        assert first.result(timeout=5) is True
    assert len(calls) == 1
    with connect() as db:
        assert service.status(db, queued["id"], admin)["status"] == "completed"


def test_image_bridge_ignores_text_endpoint_and_rejects_arbitrary_destinations(monkeypatch):
    from app.images import bridge

    monkeypatch.delenv("HERMES_IMAGE_BRIDGE_URL", raising=False)
    monkeypatch.setenv("HERMES_BRIDGE_URL", "http://hermes-bridge:8081")
    assert bridge.bridge_url() == "http://image-bridge:8082"
    for value in (
        "http://hermes-bridge:8081",
        "https://image-bridge:8082",
        "http://127.0.0.1:1/path",
        "http://user@127.0.0.1:1",
        "http://localhost:1?x=1",
        " http://127.0.0.1:1",
        "http://image-bridge:8083",
    ):
        monkeypatch.setenv("HERMES_IMAGE_BRIDGE_URL", value)
        assert bridge.bridge_url() is None
    monkeypatch.setenv("HERMES_IMAGE_BRIDGE_URL", "http://127.0.0.1:18082")
    assert bridge.bridge_url() == "http://127.0.0.1:18082"
