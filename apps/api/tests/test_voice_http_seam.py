"""Real private HTTP boundary with a fake vendor and guarded local test database.

No test calls ElevenLabs, uses a real key, starts a microphone or reads git history.
"""

# ruff: noqa: F401, F811
import base64
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_crm import ORIGIN, authenticated, customer
from test_elevenlabs import approve, login_other, propose

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "gateway_verifier", ROOT / "ops/elevenlabs/gateway.py"
)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


@pytest.fixture
def seam(authenticated, monkeypatch, tmp_path):
    client, owner, password = authenticated
    calls = []
    replies = {}

    def vendor(method, path, key, body=None, content_type="application/json", binary=False):
        calls.append((method, path, body))
        if path in replies:
            r = replies[path]
            if isinstance(r, Exception):
                raise r
            return r
        if path == "/v1/user":
            return {"user_id": "fixture"}
        if path.startswith("/v2/voices"):
            return {"voices": [{"voice_id": "voice1", "name": "Voice"}]}
        if path == "/v1/models":
            return [{"model_id": "model1", "name": "Model", "can_do_text_to_speech": True}]
        if path.startswith("/v1/convai/agents?"):
            return {"agents": [{"agent_id": "agent1", "name": "Agent"}]}
        if path.startswith("/v1/convai/phone-numbers"):
            return [{"phone_number_id": "phone1", "label": "Phone", "provider": "twilio"}]
        if path.startswith("/v1/text-to-speech/"):
            return b"ID3" + b"a" * 20
        if path == "/v1/speech-to-text":
            return {"text": "Private transcript"}
        if path.startswith("/v1/convai/conversation/token?"):
            return {"token": "VERIFIER_EPHEMERAL_PRIVATE", "conversation_id": "conv1"}
        if path == "/v1/convai/twilio/outbound-call":
            return {"success": True, "callSid": "call1"}
        raise AssertionError("unexpected fake route")

    gateway = g.Gateway(tmp_path / "state", transport=vendor)
    token = tmp_path / "service-token"
    token.write_text("S" * 43)
    token.chmod(0o600)
    handler = type("VerifierHandler", (g.Handler,), {"gateway": gateway, "token_file": str(token)})
    server = g.GatewayServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ELEVENLABS_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ELEVENLABS_GATEWAY_TOKEN_FILE", str(token))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    yield client, owner, password, gateway, calls, replies
    server.shutdown()
    server.server_close()
    gateway.close()
    thread.join()


def configure_enable(seam):
    c, owner, _, _gw, _calls, _replies = seam
    key = "VERIFIER_FAKE_VENDOR_KEY_1234567890"
    r = c.post(
        "/crm/voice/settings",
        json={
            "revision": 0,
            "api_key": key,
            "defaults": {
                "voice_id": "voice1",
                "model_id": "model1",
                "agent_id": "agent1",
                "phone_number_id": "phone1",
            },
        },
    )
    assert r.status_code == 200, r.text
    assert key not in r.text and r.json()["revision"] == 1
    assert c.post("/crm/voice/catalog", json={"revision": 1}).status_code == 200
    with psycopg.connect(owner) as db:
        v = db.execute(
            "SELECT version FROM crm.control_connections WHERE key='elevenlabs'"
        ).fetchone()[0]
    r = c.patch("/crm/control/connections/elevenlabs", json={"version": v, "enabled": True})
    assert r.status_code == 200, r.text
    return key


def test_full_real_http_seam(seam):
    c, owner, _password, gw, calls, _replies = seam
    assert c.get("/crm/voice/settings").json()["configured"] is False
    key = configure_enable(seam)
    assert c.get("/crm/voice/settings").json()["enabled"] is True
    p = propose(c)
    assert not [v for v in calls if v[0] == "POST"]
    r = approve(c, p)
    assert r.status_code == 200, r.text
    artifact = r.json()["result"]["artifact_id"]
    path = "/crm/voice/artifacts/" + artifact + "/content"
    audio = c.get(path)
    assert audio.status_code == 200 and audio.content == b"ID3" + b"a" * 20
    assert (
        "no-store" in audio.headers["cache-control"]
        and "attachment" in audio.headers["content-disposition"]
    )
    assert (
        audio.headers["x-content-type-options"] == "nosniff"
        and "sandbox" in audio.headers["content-security-policy"]
    )
    with login_other(c, owner) as other:
        assert other.get(path).status_code == 404
    with psycopg.connect(owner) as db:
        db.execute("DELETE FROM crm.users WHERE username='voiceother'")
    assert approve(c, p).status_code == 409
    raw = base64.b64encode(b"ID3" + b"a" * 20).decode()
    r = c.post(
        "/crm/voice/attachments",
        json={"filename": "fixture.mp3", "mime_type": "audio/mpeg", "data_base64": raw},
    )
    assert r.status_code == 201, r.text
    p = propose(c, "stt", {"attachment_id": r.json()["attachment_id"]})
    assert approve(c, p).json()["result"]["text"] == "Private transcript"
    sent = next(x for x in calls if x[1] == "/v1/speech-to-text")
    assert b"scribe_v2" in sent[2] and b"ID3" in sent[2]
    p = propose(c, "agent_session", {"agent_id": "agent1"})
    path = "/crm/voice/sessions/" + p["id"] + "/claim"
    assert c.post(path, json={}).status_code == 409
    assert approve(c, p).json()["result"] == {"status": "ready", "session_id": p["id"]}
    with login_other(c, owner) as other:
        assert other.post(path, json={}).status_code == 404
    r = c.post(path, json={})
    assert r.status_code == 200 and r.json()["token"] == "VERIFIER_EPHEMERAL_PRIVATE"
    assert "no-store" in r.headers["cache-control"]
    assert c.post(path, json={}).status_code == 409
    contact = customer(c)
    args = {
        "agent_id": "agent1",
        "phone_number_id": "phone1",
        "contact_id": contact["id"],
        "expected_phone": contact["phone"],
    }
    p = propose(c, "outbound_call", args)
    assert approve(c, p).status_code == 422
    assert approve(c, p, consent_confirmed="true").status_code == 422
    r = approve(c, p, consent_confirmed=True)
    assert r.json()["result"]["call_id"] == "call1", r.text
    sent = json.loads(next(x[2] for x in calls if x[1] == "/v1/convai/twilio/outbound-call"))
    assert sent == {
        "agent_id": "agent1",
        "agent_phone_number_id": "phone1",
        "to_number": contact["phone"],
        "call_recording_enabled": False,
    }
    p = propose(c)
    assert (
        c.post(
            "/crm/voice/settings", json={"revision": 1, "defaults": {"voice_id": "voice1"}}
        ).status_code
        == 200
    )
    assert approve(c, p).status_code == 409
    assert c.post("/crm/voice/catalog", json={"revision": 1}).status_code == 409
    assert (
        c.post(
            "/crm/voice/settings",
            json={"revision": 2, "defaults": {}},
            headers={"X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    with psycopg.connect(owner) as db:
        for table in (
            "hermes_proposals",
            "hermes_calls",
            "hermes_runs",
            "control_audit",
            "voice_session_claims",
            "voice_catalog",
        ):
            data = str(db.execute(f"SELECT row_to_json(x)::text FROM crm.{table} x").fetchall())
            assert key not in data and "VERIFIER_EPHEMERAL_PRIVATE" not in data
    assert "VERIFIER_EPHEMERAL_PRIVATE" not in (gw.store.directory / "state.json").read_text()


def test_uncertain_once_only_real_http(seam):
    c, _owner, _, gw, calls, replies = seam
    configure_enable(seam)
    replies["/v1/text-to-speech/voice1?output_format=mp3_22050_32"] = TimeoutError(
        "FAKE_SECRET_DO_NOT_FORWARD"
    )
    p = propose(c)
    r = approve(c, p)
    assert r.status_code == 200 and r.json()["result"] == {
        "status": "external_outcome_unconfirmed",
        "retryable": False,
    }, r.text
    assert "FAKE_SECRET" not in r.text and approve(c, p).status_code == 409
    assert len([x for x in calls if x[1].startswith("/v1/text-to-speech/")]) == 1
    assert p["id"] in (gw.store.directory / "state.json").read_text()


def test_catalog_boundary_names(seam):
    c, _owner, _, gw, _calls, replies = seam
    configure_enable(seam)
    replies["/v2/voices?page_size=50"] = {"voices": [{"voice_id": "voice1", "name": "V" * 121}]}
    direct = gw.catalog({"revision": 1})
    assert len(direct["voices"][0]["name"]) == 120
    r = c.post("/crm/voice/catalog", json={"revision": 1})
    assert r.status_code == 200, f"gateway-accepted catalog fails CRM: {r.status_code} {r.text}"
    assert r.json()["voices"] == [{"id": "voice1", "name": "V" * 120}]


def test_guard_and_concurrency_http(seam):
    from concurrent.futures import ThreadPoolExecutor

    c, owner, password, _gw, calls, _replies = seam
    configure_enable(seam)
    for op, args in [
        ("stt", {"data_base64": "SUQz", "mime_type": "audio/mpeg"}),
        (
            "outbound_call",
            {"agent_id": "agent1", "phone_number_id": "phone1", "to_number": "+573001234567"},
        ),
        ("tts", {"text": "Hello", "voice_id": "voice1", "model_id": "model1", "api_key": "NO"}),
    ]:
        r = c.post(
            "/crm/hermes/actions",
            json={"action": "voice.execute", "arguments": {"operation": op, "arguments": args}},
        )
        assert r.status_code == 422, r.text
    p = propose(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        r = list(pool.map(lambda _: approve(c, p), range(2)))
    assert sorted(x.status_code for x in r) == [200, 409]
    assert len([x for x in calls if x[1].startswith("/v1/text-to-speech/")]) == 1
    contact = customer(c)
    args = {
        "agent_id": "agent1",
        "phone_number_id": "phone1",
        "contact_id": contact["id"],
        "expected_phone": contact["phone"],
    }
    p = propose(c, "outbound_call", args)
    assert (
        c.patch(
            "/crm/contacts/" + contact["id"],
            json={
                "name": contact["name"],
                "source": contact["source"],
                "phone": "+573001234568",
                "version": contact["version"],
            },
        ).status_code
        == 200
    )
    assert approve(c, p, consent_confirmed=True).status_code == 409
    assert not [x for x in calls if x[1] == "/v1/convai/twilio/outbound-call"]
    p = propose(c, "agent_session", {"agent_id": "agent1"})
    assert approve(c, p).json()["result"]["status"] == "ready"
    claim = "/crm/voice/sessions/" + p["id"] + "/claim"
    c2 = TestClient(c.app, base_url=ORIGIN)
    login = c2.post(
        "/crm/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": "testadmin", "password": password},
    )
    assert login.status_code == 200
    c2.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]})
    assert c2.post(claim, json={}).status_code == 404
    c2.close()
    with psycopg.connect(owner) as db:
        v = db.execute(
            "SELECT version FROM crm.control_connections WHERE key='elevenlabs'"
        ).fetchone()[0]
    assert (
        c.patch(
            "/crm/control/connections/elevenlabs", json={"version": v, "enabled": False}
        ).status_code
        == 200
    )
    assert c.post(claim, json={}).status_code == 409
    assert not [x for x in calls if x[1].endswith("/claim")]
    r = c.post(
        "/crm/hermes/actions",
        json={
            "action": "voice.execute",
            "arguments": {
                "operation": "tts",
                "arguments": {"text": "Hi", "voice_id": "voice1", "model_id": "model1"},
            },
        },
    )
    assert r.status_code == 409


def test_actual_manifest_strict_protocol_and_ordinary_sara_without_provider(
    authenticated, monkeypatch
):
    from test_hermes_broker import issue

    c, owner, _ = authenticated
    monkeypatch.delenv("ELEVENLABS_GATEWAY_URL", raising=False)
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='elevenlabs'")
    _, _, headers = issue(c, owner)
    r = c.post("/internal/hermes/claim", json={}, headers=headers)
    assert r.status_code == 200, r.text
    spec = importlib.util.spec_from_file_location(
        "protocol_verifier", ROOT / "ops/hermes/operator_protocol.py"
    )
    protocol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(protocol)
    claim = protocol.validate_claim(r.json())
    description = claim["tools"][0]["function"]["description"]
    assert len(description.encode()) <= 16384
    enum = claim["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    assert {"voice.catalog", "voice.execute"} <= set(enum)
    r = c.post(
        "/internal/hermes/call",
        json={"call_id": "workspace", "action": "crm.workspace", "arguments": {}},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["result"]["contacts"] == []
    r = c.post(
        "/internal/hermes/call",
        json={"call_id": "voice", "action": "voice.catalog", "arguments": {}},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["result"]["available"] is False
    r = c.post(
        "/internal/hermes/finish",
        json={"reply": "Completed without voice provider."},
        headers=headers,
    )
    assert r.status_code == 200, r.text
