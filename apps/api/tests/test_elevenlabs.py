"""Private shared ElevenLabs adapter: fake gateway only, guarded test database."""

# ruff: noqa: F811
import base64
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_crm import ORIGIN, authenticated, customer  # noqa: F401

from app.main import app
from app.voice import bridge


@pytest.fixture
def voiced(authenticated, monkeypatch):
    client, owner, _password = authenticated
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='elevenlabs'")
    calls = []
    state = {
        "configured": True,
        "verified": True,
        "revision": 1,
        "key_suffix": "abcd",
        "defaults": {
            "voice_id": "voice1",
            "model_id": "model1",
            "agent_id": "agent1",
            "phone_number_id": "phone1",
        },
    }
    catalog = {
        "revision": 1,
        "voices": [{"id": "voice1", "name": "Voice"}],
        "models": [{"id": "model1", "name": "Model"}],
        "agents": [{"id": "agent1", "name": "Agent"}],
        "phone_numbers": [{"id": "phone1", "name": "Phone"}],
        "limited": False,
        "errors": [],
    }

    def request(path, body=None, timeout=3):
        calls.append((path, body))
        if path == "/state":
            return state.copy()
        if path == "/catalog":
            return catalog.copy()
        if path == "/configure":
            state["revision"] += 1
            return state.copy()
        if path == "/disconnect":
            state.update(configured=False, verified=False, revision=state["revision"] + 1)
            return state.copy()
        if path.endswith("/claim"):
            return {"token": "ephemeral_secret_token", "conversation_id": "conversation1"}
        if path == "/execute":
            op = body["operation"]
            if op == "tts":
                return {
                    "status": "completed",
                    "mime_type": "audio/mpeg",
                    "data_base64": base64.b64encode(b"ID3" + b"a" * 20).decode(),
                }
            if op == "stt":
                return {"status": "completed", "text": "Transcripción privada"}
            if op == "agent_session":
                return {"status": "ready"}
            return {"status": "completed", "conversation_id": "conversation1", "call_id": "call1"}
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "request", request)
    assert client.post("/crm/voice/catalog", json={"revision": 1}).status_code == 200
    yield client, owner, state, calls
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='elevenlabs'")


def propose(client, operation="tts", arguments=None):
    response = client.post(
        "/crm/hermes/actions",
        json={
            "action": "voice.execute",
            "arguments": {
                "operation": operation,
                "arguments": arguments
                or {"text": "Hola", "voice_id": "voice1", "model_id": "model1"},
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["proposals"][0]


def approve(client, p, **extra):
    return client.post(
        "/crm/hermes/proposals/" + p["id"] + "/approve", json={"version": p["version"], **extra}
    )


def test_voice_auth_origin_csrf_and_unavailable_do_not_break_crm(authenticated, monkeypatch):
    client, _, _ = authenticated
    with TestClient(app) as anonymous:
        assert anonymous.get("/crm/voice/settings").status_code == 401
    assert (
        client.post(
            "/crm/voice/catalog", json={"revision": 0}, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/crm/voice/settings",
            json={"revision": 0, "api_key": "not_a_real_key_12345"},
            headers={"X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    monkeypatch.delenv("ELEVENLABS_GATEWAY_URL", raising=False)
    response = client.get("/crm/voice/settings")
    assert response.status_code == 200 and response.json()["available"] is False
    assert client.get("/crm/workspace").status_code == 200


def test_paid_tts_is_proposal_once_only_and_private_artifact(voiced):
    client, owner, _, calls = voiced
    p = propose(client)
    assert not [x for x in calls if x[0] == "/execute"]
    result = approve(client, p)
    assert result.status_code == 200, result.text
    value = result.json()["result"]
    assert value["artifact_id"] and "data_base64" not in result.text
    assert approve(client, p).status_code == 409
    assert len([x for x in calls if x[0] == "/execute"]) == 1
    blob = client.get("/crm/voice/artifacts/" + value["artifact_id"] + "/content")
    assert blob.status_code == 200 and blob.content.startswith(b"ID3")
    assert "attachment" in blob.headers["content-disposition"]
    with psycopg.connect(owner) as db:
        text = str(db.execute("SELECT result FROM crm.hermes_proposals").fetchall())
        assert "data_base64" not in text and "ephemeral_secret_token" not in text


def test_voice_catalog_is_readonly_and_manifest_bounded(voiced):
    client, _, _, calls = voiced
    count = len(calls)
    response = client.post("/crm/hermes/actions", json={"action": "voice.catalog", "arguments": {}})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["catalog"]["voices"][0]["id"] == "voice1"
    assert not any(x[0] in ["/catalog", "/execute"] for x in calls[count:])


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("tts", {"text": "Hola", "voice_id": "https://evil.invalid", "model_id": "model1"}),
        (
            "tts",
            {"text": "Hola", "voice_id": "voice1", "model_id": "model1", "api_key": "not_allowed"},
        ),
        ("tts", {"text": "x" * 1501, "voice_id": "voice1", "model_id": "model1"}),
        ("stt", {"data_base64": "SUQz", "mime_type": "audio/mpeg"}),
        ("stt", {"attachment_id": str(uuid4()), "url": "https://evil.invalid"}),
        ("agent_session", {"agent_id": "agent1", "token": "not_allowed"}),
        (
            "outbound_call",
            {"agent_id": "agent1", "phone_number_id": "phone1", "to_number": "+573001234567"},
        ),
        (
            "outbound_call",
            {
                "agent_id": "agent1",
                "phone_number_id": "phone1",
                "contact_id": str(uuid4()),
                "expected_phone": "+573001234567",
                "consent_confirmed": True,
            },
        ),
        ("arbitrary", {}),
    ],
)
def test_strict_operation_models_reject_secrets_urls_and_raw_broker_audio(
    voiced, operation, arguments
):
    client, owner, _, calls = voiced
    response = client.post(
        "/crm/hermes/actions",
        json={
            "action": "voice.execute",
            "arguments": {"operation": operation, "arguments": arguments},
        },
    )
    assert response.status_code == 422
    assert not [x for x in calls if x[0] == "/execute"]
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0


def test_outbound_call_exact_contact_strict_human_consent_and_recheck(voiced):
    client, owner, _, calls = voiced
    contact = customer(client)
    args = {
        "agent_id": "agent1",
        "phone_number_id": "phone1",
        "contact_id": contact["id"],
        "expected_phone": contact["phone"],
    }
    p = propose(client, "outbound_call", args)
    assert approve(client, p).status_code == 422
    assert approve(client, p, consent_confirmed="true").status_code == 422
    assert not [x for x in calls if x[0] == "/execute"]
    result = approve(client, p, consent_confirmed=True)
    assert result.status_code == 200 and result.json()["result"]["call_id"] == "call1"
    sent = next(x[1] for x in calls if x[0] == "/execute")
    assert sent["arguments"] == {
        "agent_id": "agent1",
        "phone_number_id": "phone1",
        "to_number": contact["phone"],
    }
    with psycopg.connect(owner) as db:
        row = db.execute(
            "SELECT arguments FROM crm.control_audit WHERE action='proposal.approve' AND proposal_id=%s",
            (p["id"],),
        ).fetchone()[0]
        assert row["consent_confirmed"] is True
    p = propose(client, "outbound_call", args)
    assert (
        client.patch(
            "/crm/contacts/" + contact["id"],
            json={
                "name": contact["name"],
                "phone": "+573001234568",
                "source": "web",
                "version": contact["version"],
            },
        ).status_code
        == 200
    )
    assert approve(client, p, consent_confirmed=True).status_code == 409
    assert len([x for x in calls if x[0] == "/execute"]) == 1
    stale = client.post(
        "/crm/hermes/actions",
        json={
            "action": "voice.execute",
            "arguments": {"operation": "outbound_call", "arguments": args},
        },
    )
    assert stale.status_code == 409


def test_provider_connection_changes_revoke_proposals_and_rejection_never_dispatches(voiced):
    client, owner, state, calls = voiced
    p = propose(client)
    state["revision"] = 2
    assert approve(client, p).status_code == 409
    state["revision"] = 1
    p = propose(client)
    with psycopg.connect(owner) as db:
        db.execute(
            "UPDATE crm.control_connections SET enabled=false,version=version+1 WHERE key='elevenlabs'"
        )
    assert approve(client, p).status_code == 409
    assert (
        client.post(
            "/crm/hermes/actions", json={"action": "voice.catalog", "arguments": {}}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/crm/hermes/proposals/" + p["id"] + "/reject", json={"version": p["version"]}
        ).status_code
        == 200
    )
    assert not [x for x in calls if x[0] == "/execute"]


def login_other(client, owner):
    from app.crm.security import password_hash

    with psycopg.connect(owner) as db:
        db.execute(
            "INSERT INTO crm.users(username,password_hash) VALUES (%s,%s)",
            ("voiceother", password_hash.hash("private_test_password_123")),
        )
    other = TestClient(app, base_url=ORIGIN)
    response = other.post(
        "/crm/auth/login",
        json={"username": "voiceother", "password": "private_test_password_123"},
        headers={"Origin": ORIGIN},
    )
    other.headers.update({"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
    return other


def test_session_claim_owned_session_bound_one_shot_and_never_persisted(voiced):
    client, owner, _, calls = voiced
    p = propose(client, "agent_session", {"agent_id": "agent1"})
    path = "/crm/voice/sessions/" + p["id"] + "/claim"
    assert client.post(path, json={}).status_code == 409
    assert approve(client, p).json()["result"] == {"status": "ready", "session_id": p["id"]}
    with login_other(client, owner) as other:
        assert other.post(path, json={}).status_code == 404
    response = client.post(path, json={})
    assert response.status_code == 200 and response.json()["token"] == "ephemeral_secret_token"
    assert "no-store" in response.headers["cache-control"]
    assert client.post(path, json={}).status_code == 409
    assert len([x for x in calls if x[0].endswith("/claim")]) == 1
    with psycopg.connect(owner) as db:
        for table in (
            "hermes_proposals",
            "hermes_calls",
            "hermes_runs",
            "control_audit",
            "voice_session_claims",
        ):
            rows = db.execute(f"SELECT row_to_json(x)::text FROM crm.{table} x").fetchall()
            assert "ephemeral_secret_token" not in str(rows)


def test_stage_audio_and_stt_without_openai_then_owner_only_access(voiced, monkeypatch):
    from app.hermes import bridge as hermes_bridge

    monkeypatch.setattr(
        hermes_bridge, "request", lambda *a, **k: pytest.fail("No OpenAI ingestion")
    )
    client, owner, _, calls = voiced
    raw = base64.b64encode(b"ID3" + b"a" * 20).decode()
    upload = client.post(
        "/crm/voice/attachments",
        json={"filename": "input.mp3", "mime_type": "audio/mpeg", "data_base64": raw},
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["attachment_id"]
    with login_other(client, owner) as other:
        response = other.post(
            "/crm/hermes/actions",
            json={
                "action": "voice.execute",
                "arguments": {"operation": "stt", "arguments": {"attachment_id": file_id}},
            },
        )
        assert response.status_code == 404
    p = propose(client, "stt", {"attachment_id": file_id})
    assert approve(client, p).json()["result"]["text"] == "Transcripción privada"
    dispatched = next(x[1] for x in calls if x[0] == "/execute")
    assert dispatched["arguments"] == {"data_base64": raw, "mime_type": "audio/mpeg"}
    with psycopg.connect(owner) as db:
        assert raw not in str(db.execute("SELECT arguments FROM crm.hermes_proposals").fetchall())
    assert (
        client.post(
            "/crm/voice/attachments",
            json={"filename": "data.txt", "mime_type": "text/plain", "data_base64": raw},
        ).status_code
        == 422
    )


def test_gateway_errors_and_secret_result_are_consumed_without_retry(voiced, monkeypatch):
    client, owner, _, calls = voiced
    original = bridge.request

    def request(path, body=None, timeout=3):
        if path == "/execute":
            calls.append((path, body))
            raise RuntimeError("provider credential must not appear")
        return original(path, body, timeout)

    monkeypatch.setattr(bridge, "request", request)
    p = propose(client)
    response = approve(client, p)
    assert response.status_code == 200 and response.json()["result"] == {
        "status": "external_outcome_unconfirmed",
        "retryable": False,
    }
    assert "credential" not in response.text and approve(client, p).status_code == 409
    assert len([x for x in calls if x[0] == "/execute"]) == 1
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.voice_artifacts").fetchone()[0] == 0


def test_keys_never_echo_or_enter_audit_and_configuration_invalidates_pending(voiced):
    client, owner, _, _ = voiced
    p = propose(client)
    key = "fake_vendor_key_never_print_123"
    response = client.post("/crm/voice/settings", json={"revision": 1, "api_key": key})
    assert response.status_code == 200 and key not in response.text
    assert approve(client, p).status_code == 409
    with psycopg.connect(owner) as db:
        for table in ("control_audit", "hermes_proposals", "voice_catalog"):
            assert key not in str(
                db.execute(f"SELECT row_to_json(x)::text FROM crm.{table} x").fetchall()
            )


def test_absent_disabled_voice_does_not_break_ordinary_sara_claim_or_business_actions(
    authenticated, monkeypatch
):
    from test_hermes_broker import issue

    client, owner, _ = authenticated
    monkeypatch.delenv("ELEVENLABS_GATEWAY_URL", raising=False)
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='elevenlabs'")
    _, _, headers = issue(client, owner)
    response = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert response.status_code == 200, response.text
    claim = response.json()
    fn = claim["tools"][0]["function"]
    assert len(fn["description"].encode()) <= 16384
    assert {"voice.catalog", "voice.execute"} <= set(
        fn["parameters"]["properties"]["action"]["enum"]
    )
    read = client.post(
        "/internal/hermes/call",
        headers=headers,
        json={"call_id": "read", "action": "crm.workspace", "arguments": {}},
    )
    assert read.status_code == 200 and read.json()["result"]["contacts"] == []
    catalog = client.post(
        "/internal/hermes/call",
        headers=headers,
        json={"call_id": "voice", "action": "voice.catalog", "arguments": {}},
    )
    assert catalog.json()["result"]["available"] is False
    finish = client.post(
        "/internal/hermes/finish", headers=headers, json={"reply": "Consulta completada."}
    )
    assert finish.status_code == 200 and finish.json()["reply"] == "Consulta completada."


@pytest.mark.parametrize(
    "url",
    [
        "https://api.elevenlabs.io",
        "http://evil.invalid:8092",
        "http://voice-gateway:8093",
        "http://user@voice-gateway:8092",
        "http://voice-gateway:8092/path",
        "http://127.0.0.1:8092?key=value",
        "http://voice-gateway:8092#fragment",
    ],
)
def test_gateway_transport_rejects_arbitrary_origins(monkeypatch, url):
    monkeypatch.setenv("ELEVENLABS_GATEWAY_URL", url)
    monkeypatch.setenv("CRM_ALLOW_INSECURE_HTTP", "0")
    assert bridge.base_url() is None


def test_fixed_gateway_transport_requires_secret_disables_proxy_redirects_and_sanitizes_errors(
    monkeypatch, tmp_path
):
    from urllib.error import HTTPError
    from urllib.request import ProxyHandler

    from fastapi import HTTPException

    monkeypatch.setenv("ELEVENLABS_GATEWAY_URL", "http://voice-gateway:8092")
    token_file = tmp_path / "gateway-token"
    token_file.write_text("S" * 43)
    monkeypatch.setenv("ELEVENLABS_GATEWAY_TOKEN_FILE", str(token_file))
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"configured":false}'

    class Opener:
        def open(self, req, timeout):
            calls.append((req, timeout))
            return Response()

    handlers = []

    def opener(*args):
        handlers.extend(args)
        return Opener()

    monkeypatch.setattr(bridge, "build_opener", opener)
    assert bridge.request("/state") == {"configured": False}
    assert calls[0][0].full_url == "http://voice-gateway:8092/state"
    assert calls[0][0].headers["Authorization"] == "Bearer " + "S" * 43
    assert any(isinstance(h, ProxyHandler) and not h.proxies for h in handlers)
    assert any(isinstance(h, bridge.NoRedirect) for h in handlers)
    assert bridge.NoRedirect().redirect_request(None, None, None, None, None, None) is None
    with pytest.raises(HTTPException):
        bridge.request("/unapproved")
    token_file.unlink()
    with pytest.raises(HTTPException) as error:
        bridge.request("/state")
    assert error.value.detail == "voice_unavailable"
    token_file.write_text("S" * 43)

    def failed(*args, **kwargs):
        raise HTTPError("http://private.invalid", 409, "SECRET_VENDOR_DETAIL", None, None)

    monkeypatch.setattr(Opener, "open", failed)
    with pytest.raises(HTTPException) as error:
        bridge.request("/state")
    assert error.value.status_code == 409 and error.value.detail == "voice_provider_changed"


def test_tts_download_is_owner_only_and_dispatch_reservation_visible_before_network(
    voiced, monkeypatch
):
    client, owner, _, _ = voiced
    original = bridge.request

    def request(path, body=None, timeout=3):
        if path == "/execute":
            with psycopg.connect(owner) as db:
                row = db.execute(
                    "SELECT status,result FROM crm.hermes_proposals WHERE id=%s", (body["id"],)
                ).fetchone()
                assert row == ("approved", {"status": "dispatch_reserved", "retryable": False})
        return original(path, body, timeout)

    monkeypatch.setattr(bridge, "request", request)
    p = propose(client)
    artifact = approve(client, p).json()["result"]["artifact_id"]
    with login_other(client, owner) as other:
        assert other.get("/crm/voice/artifacts/" + artifact + "/content").status_code == 404
    response = client.get("/crm/voice/artifacts/" + artifact + "/content")
    assert response.status_code == 200 and response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


def test_session_gateway_secret_smuggling_is_not_persisted_or_returned(voiced, monkeypatch):
    client, owner, _, _ = voiced
    original = bridge.request
    secret = "fake_ephemeral_token_cannot_echo"

    def request(path, body=None, timeout=3):
        if path == "/execute":
            return {"status": "ready", "token": secret}
        return original(path, body, timeout)

    monkeypatch.setattr(bridge, "request", request)
    p = propose(client, "agent_session", {"agent_id": "agent1"})
    response = approve(client, p)
    assert (
        secret not in response.text
        and response.json()["result"]["status"] == "external_outcome_unconfirmed"
    )
    assert client.post("/crm/voice/sessions/" + p["id"] + "/claim", json={}).status_code == 409
    with psycopg.connect(owner) as db:
        assert secret not in str(db.execute("SELECT result FROM crm.hermes_proposals").fetchall())


def test_voice_request_bodies_are_bounded_before_json_parsing(authenticated):
    client, _, _ = authenticated
    response = client.post(
        "/crm/voice/settings", content=b" " * 16385, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    response = client.post(
        "/crm/voice/attachments",
        content=b" " * (768 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_voice_quotas_and_bad_audio_are_rejected_without_any_provider_call(voiced):
    client, owner, _, calls = voiced
    bad = client.post(
        "/crm/voice/attachments",
        json={
            "filename": "input.mp3",
            "mime_type": "audio/mpeg",
            "data_base64": base64.b64encode(b"not audio").decode(),
        },
    )
    assert bad.status_code == 422
    with psycopg.connect(owner) as db:
        actor = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()[0]
        db.execute(
            "INSERT INTO crm.voice_artifacts(owner_id,kind,filename,mime_type,size,data) SELECT %s,'input','input.mp3','audio/mpeg',12,decode(repeat('61',12),'hex') FROM generate_series(1,100)",
            (actor,),
        )
    response = client.post(
        "/crm/voice/attachments",
        json={
            "filename": "input.mp3",
            "mime_type": "audio/mpeg",
            "data_base64": base64.b64encode(b"ID3" + b"a" * 20).decode(),
        },
    )
    assert response.status_code == 409
    response = client.post(
        "/crm/hermes/actions",
        json={
            "action": "voice.execute",
            "arguments": {
                "operation": "tts",
                "arguments": {"text": "Hola", "voice_id": "voice1", "model_id": "model1"},
            },
        },
    )
    assert response.status_code == 409
    assert not [x for x in calls if x[0] == "/execute"]


def test_private_session_cannot_be_claimed_from_another_session_of_same_admin(
    voiced, authenticated
):
    client, _, _, calls = voiced
    _, _, password = authenticated
    p = propose(client, "agent_session", {"agent_id": "agent1"})
    assert approve(client, p).status_code == 200
    with TestClient(app, base_url=ORIGIN) as second:
        login = second.post(
            "/crm/auth/login",
            json={"username": "testadmin", "password": password},
            headers={"Origin": ORIGIN},
        )
        second.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]})
        assert second.post("/crm/voice/sessions/" + p["id"] + "/claim", json={}).status_code == 404
    assert not [x for x in calls if x[0].endswith("/claim")]


def test_concurrent_approval_and_session_claim_are_once_only(voiced):
    from concurrent.futures import ThreadPoolExecutor

    client, _, _, calls = voiced
    p = propose(client, "agent_session", {"agent_id": "agent1"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: approve(client, p).status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    assert len([x for x in calls if x[0] == "/execute"]) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(
                lambda _: (
                    client.post("/crm/voice/sessions/" + p["id"] + "/claim", json={}).status_code
                ),
                range(2),
            )
        )
    assert sorted(statuses) == [200, 409]
    assert len([x for x in calls if x[0].endswith("/claim")]) == 1


def test_existing_owned_sara_audio_can_be_used_without_catalog_or_openai(voiced):
    client, owner, _, _ = voiced
    raw = b"ID3" + b"a" * 20
    with psycopg.connect(owner) as db:
        db.execute("DELETE FROM crm.voice_catalog")
        actor = db.execute("SELECT id FROM crm.users WHERE username='testadmin'").fetchone()[0]
        file_id = db.execute(
            "INSERT INTO crm.sara_attachments(owner_id,filename,mime_type,size,kind,data,text) VALUES (%s,'note.mp3','audio/mpeg',%s,'audio',%s,'Already transcribed') RETURNING id",
            (actor, len(raw), raw),
        ).fetchone()[0]
    p = propose(client, "stt", {"attachment_id": str(file_id)})
    assert approve(client, p).json()["result"]["text"] == "Transcripción privada"
