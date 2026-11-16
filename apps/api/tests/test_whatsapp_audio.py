"""Explicit audio replies retain the original source and never grant agent tools."""
# ruff: noqa: F811

import base64
import copy
import hashlib
import json
from contextlib import nullcontext
from email import policy
from email.parser import BytesParser
from pathlib import Path

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from test_crm import authenticated  # noqa: F401
from test_image_delivery import real_child_fixture
from test_whatsapp_agent import configured, jobs, payload, send  # noqa: F401
from test_workflow_social import vendor  # noqa: F401

from app.social import audio_media, media, media_process, workflow
from app.social import whatsapp_agent as agent
from app.voice import service as voice

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"fixture-audio" * 5
REAL_ISOLATED = media._isolated
REAL_PREPARE = workflow.prepare_literal_reply
REAL_CHECK = workflow._check
REAL_SOURCE = agent.source_verified


def test_original_maximum_audio_message_and_full_history_fit_real_public_protocol(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "ops/hermes"))
    from operator_public import MAX_PUBLIC_BODY, validate_public

    from app.social.whatsapp_audio import public_messages

    text = "Respóndeme en audio " + "x" * (2000 - len("Respóndeme en audio "))
    history = [{"role": role, "content": "h" * 2000} for role in ("user", "assistant") * 3]
    body = {
        "messages": public_messages(history, text, "i" * 2000, "k" * 4000),
        "instructions": "i" * 2000,
        "knowledge": "k" * 4000,
    }
    assert validate_public(body) == body
    assert body["messages"][-1]["content"] == text
    assert len(body["messages"]) == 8
    # The hint must never make an otherwise valid near-limit request invalid.
    original = {**body, "messages": [*history, {"role": "user", "content": text}], "knowledge": ""}
    overhead = len(json.dumps(original, ensure_ascii=False).encode())
    knowledge = "😀" * ((MAX_PUBLIC_BODY - overhead) // 4)
    original["knowledge"] = knowledge
    assert validate_public(original) == original
    final = {
        **original,
        "messages": public_messages(history, text, original["instructions"], knowledge),
    }
    assert validate_public(final) == final
    assert final["messages"] == original["messages"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Respóndeme en audio por favor", True),
        ("Envíame una nota de voz sobre los lotes", True),
        ("Quiero que me respondas por audio", True),
        ("/audio Cuéntame sobre el proyecto", True),
        ("Respóndeme por voz", True),
        ("¿Puedes enviarme una nota de voz?", True),
        ("Quiero un audio", True),
        ("¿Cómo envío un audio?", False),
        ("Quiero un lote cerca de un estudio de audio", False),
        ("Responde sobre el audio que te envié", False),
        ("No me respondas en audio", False),
        ("No quiero audio, solo texto", False),
        ("/aprender Responde en audio", False),
        ("Hola", False),
    ],
)
def test_audio_requires_an_explicit_current_message_request(text, expected):
    from app.social.whatsapp_audio import requested

    assert requested(text) is expected


@pytest.fixture
def audio_setup(configured, monkeypatch):
    client, owner, c = configured
    state = {
        "available": True,
        "configured": True,
        "verified": True,
        "revision": 3,
        "defaults": {"voice_id": "voice-one", "model_id": "model-one"},
    }
    with psycopg.connect(owner) as db:
        db.execute("UPDATE crm.control_connections SET enabled=true WHERE key='elevenlabs'")
        db.execute(
            "INSERT INTO crm.voice_catalog(id,revision,catalog) VALUES(true,3,%s) "
            "ON CONFLICT(id) DO UPDATE SET revision=3,catalog=EXCLUDED.catalog",
            (Jsonb({"voices": [{"id": "voice-one"}], "models": [{"id": "model-one"}]}),),
        )
    monkeypatch.setattr(voice, "state", lambda: copy.deepcopy(state))
    monkeypatch.setattr(agent, "source_verified", lambda *_: True)
    monkeypatch.setattr(media.config, "locked", nullcontext)
    calls, requests, prompts = [], [], []

    def tts(path, body, **kwargs):
        assert path == "/execute" and body["operation"] == "tts"
        with psycopg.connect(owner) as db:
            assert (
                db.execute(
                    "SELECT state FROM crm.whatsapp_agent_jobs WHERE id=%s", (body["id"],)
                ).fetchone()[0]
                == "reserved"
            )
            assert (
                db.execute(
                    "SELECT state FROM crm.whatsapp_agent_audio WHERE job_id=%s", (body["id"],)
                ).fetchone()[0]
                == "synthesizing"
            )
        calls.append(copy.deepcopy(body))
        return {
            "status": "completed",
            "mime_type": "audio/mpeg",
            "data_base64": base64.b64encode(MP3).decode(),
        }

    def public(path, body, **kwargs):
        assert path == "/public-reply"
        prompts.append(body)
        return {
            "ok": True,
            "tools": 0,
            "response": "Esta es la respuesta con el conocimiento compartido.",
        }

    def prepare(db, source, text):
        return {
            "kind": "social_message",
            "platform": "whatsapp",
            "account_id": source["account_id"],
            "conversation_id": source["conversation_id"],
            "credential_revision": workflow._digest(c),
            "payload": {"accountId": source["account_id"], "message": text},
        }

    class Response:
        status = 201

        def read(self, maximum):
            return json.dumps(
                {
                    "success": True,
                    "data": {"messageId": "wamid.audio", "conversationId": "internal-thread"},
                }
            ).encode()[:maximum]

        def close(self):
            pass

    class Connection:
        def request(self, method, path, *, body, headers):
            requests.append((method, path, body, headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(voice.bridge, "request", tts)
    monkeypatch.setattr(agent.bridge, "request", public)
    monkeypatch.setattr(workflow, "prepare_literal_reply", prepare)
    monkeypatch.setattr(workflow, "_check", lambda *_: None)
    monkeypatch.setattr(media, "_isolated", media_process.execute)
    monkeypatch.setattr(audio_media, "https_connection", lambda *_a, **_k: Connection())
    return client, owner, c, state, calls, requests, prompts


def enqueue(audio_setup, text="Respóndeme en audio sobre los lotes"):
    client, _, c, *_ = audio_setup
    event = payload("573001110003")  # Public customer, never a developer.
    event["message"]["text"] = text
    assert send(client, c, event).status_code == 200
    return event


def test_real_worker_synthesizes_shared_answer_and_sends_original_private_mp3_once(audio_setup):
    _, owner, _, _, calls, requests, prompts = audio_setup
    event = enqueue(audio_setup)
    agent.tick()
    job = jobs(owner)[0]
    assert job["state"] == "completed", job["error"]
    assert job["content"] == event["message"]["text"]
    assert job["receipt"] == {
        "status": "accepted",
        "message_id": "wamid.audio",
        "conversation_id": "internal-thread",
    }
    assert len(calls) == len(requests) == len(prompts) == 1
    assert calls[0]["arguments"] == {
        "text": job["reply"],
        "voice_id": "voice-one",
        "model_id": "model-one",
    }
    assert prompts[0]["messages"][-1]["content"] == event["message"]["text"]
    assert "Project reference information." in prompts[0]["knowledge"]
    method, path, body, headers = requests[0]
    assert method == "POST" and "internal-thread" in path
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + body
    )
    parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
    assert set(parts) == {"accountId", "message", "attachment"}
    assert parts["accountId"].get_content() == event["account"]["id"]
    assert parts["message"].get_content() == audio_media.CAPTION
    assert parts["attachment"].get_payload(decode=True) == MP3
    assert parts["attachment"].get_content_type() == "audio/mpeg"
    with psycopg.connect(owner) as db:
        row = db.execute(
            "SELECT state,data,content_hash FROM crm.whatsapp_agent_audio WHERE job_id=%s",
            (job["id"],),
        ).fetchone()
        assert row == ("completed", MP3, hashlib.sha256(MP3).hexdigest())
        assert (
            db.execute("SELECT count(*) FROM crm.whatsapp_developer_authority").fetchone()[0] == 0
        )
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0
    agent.tick()
    assert len(calls) == len(requests) == 1
    assert send(audio_setup[0], audio_setup[2], event).status_code == 200
    agent.tick()
    assert len(jobs(owner)) == len(calls) == len(requests) == 1


@pytest.mark.parametrize(
    "failure",
    ["tts_timeout", "invalid_mp3", "revoked_after_tts", "provider_changed", "delivery_timeout"],
)
def test_paid_or_delivery_uncertainty_never_regenerates_or_replays(
    audio_setup, monkeypatch, failure
):
    _, owner, _, state, calls, requests, _ = audio_setup
    original = voice.bridge.request

    def tts(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure == "tts_timeout":
            raise HTTPException(503, "private-provider-diagnostics")
        if failure == "invalid_mp3":
            result["data_base64"] = base64.b64encode(b"not an MP3 payload").decode()
        if failure == "revoked_after_tts":
            with psycopg.connect(owner) as db:
                db.execute("UPDATE crm.whatsapp_agent SET enabled=false")
        if failure == "provider_changed":
            state["revision"] += 1
        return result

    monkeypatch.setattr(voice.bridge, "request", tts)
    if failure == "delivery_timeout":
        monkeypatch.setattr(
            audio_media,
            "submit",
            lambda *_: {"state": "unknown", "receipt": {}, "error": "audio_delivery_unknown"},
        )
    enqueue(audio_setup)
    agent.tick()
    job = jobs(owner)[0]
    assert job["state"] == "unknown"
    assert "private-provider" not in str(job)
    assert len(calls) == 1 and not requests
    agent.tick()
    assert len(calls) == 1 and not requests
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT state FROM crm.whatsapp_agent_audio").fetchone()[0] == "unknown"


def test_recipient_preparation_failure_blocks_before_paid_generation(audio_setup, monkeypatch):
    _, owner, _, _, calls, requests, _ = audio_setup
    monkeypatch.setattr(
        audio_media,
        "prepare_reply",
        lambda *_: (_ for _ in ()).throw(HTTPException(409, "thread_control_other")),
    )
    enqueue(audio_setup)
    agent.tick()
    assert jobs(owner)[0]["state"] == "blocked"
    assert not calls and not requests


def test_existing_text_reply_does_not_invoke_tts(audio_setup, monkeypatch):
    from test_whatsapp_agent import mock_dispatch

    _, owner, _, _, calls, requests, _ = audio_setup
    sent = mock_dispatch(monkeypatch)
    enqueue(audio_setup, "No quiero audio, solo texto")
    agent.tick()
    assert jobs(owner)[0]["state"] == "completed"
    assert len(sent) == 1 and not calls and not requests


@pytest.mark.parametrize(
    "failure", ["disabled", "unverified", "missing_voice", "capability_disabled"]
)
def test_provider_preflight_failure_never_spends_or_uploads(audio_setup, failure):
    _, owner, _, state, calls, requests, _ = audio_setup
    if failure == "disabled":
        with psycopg.connect(owner) as db:
            db.execute("UPDATE crm.control_connections SET enabled=false WHERE key='elevenlabs'")
    elif failure == "unverified":
        state["verified"] = False
    elif failure == "capability_disabled":
        with psycopg.connect(owner) as db:
            actor = db.execute(
                "SELECT owner_id FROM crm.whatsapp_agent WHERE singleton"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO crm.control_items(actor_id,kind,name,definition,enabled,origin) "
                "VALUES(%s,'tool','Voice disabled by owner',%s,false,'human')",
                (actor, Jsonb({"action": "voice.execute"})),
            )
    else:
        state["defaults"]["voice_id"] = "not-in-the-catalog"
    enqueue(audio_setup)
    agent.tick()
    assert jobs(owner)[0]["state"] == "blocked"
    assert not calls and not requests


@pytest.mark.parametrize("mutation", ["bytes", "recipient", "mime", "identifier"])
def test_sealed_audio_cannot_be_changed_before_submission(audio_setup, mutation):
    _, owner, _, _, calls, requests, _ = audio_setup
    enqueue(audio_setup)
    source, _ = agent.claim()
    plan = audio_media.prepare(source, MP3)
    data = MP3
    if mutation == "bytes":
        data = MP3 + b"changed"
    elif mutation == "recipient":
        plan["reply"]["conversation_id"] = "different-recipient"
    elif mutation == "mime":
        plan["mime_type"] = "image/png"
    else:
        plan["audio_id"] = "not-an-id"
    with pytest.raises((ValueError, HTTPException)):
        audio_media.submit(plan, data, "sara-audio-test")
    assert not calls and not requests
    assert jobs(owner)[0]["state"] == "generating"


def test_developer_audio_prompt_keeps_verified_identity_and_original_message(
    configured, monkeypatch
):
    from app.crm.database import connect
    from app.hermes import developer

    client, _, credentials = configured
    event = payload()
    event["message"]["text"] = "Respóndeme en audio sobre el conocimiento de Sara"
    assert send(client, credentials, event).status_code == 200
    source, _ = agent.claim()
    monkeypatch.setattr(agent, "source_verified", lambda *_: True)
    with connect() as db:
        _, token = developer.issue(db, source["id"])
    response = client.post(
        "/internal/hermes/claim", json={}, headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 200
    prompt = json.loads(response.json()["prompt"])
    assert prompt["verified_developer_name"] == "Developer One"
    assert prompt["message"] == event["message"]["text"]
    assert prompt["response_format"] == "spoken_answer"
    actions = response.json()["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    assert "voice.execute" not in actions  # Audio transport does not widen the developer grant.


@pytest.mark.parametrize("mutation", ["none", "handover", "window", "pre_handover", "pre_window"])
def test_actual_source_and_workflow_guards_for_audio(vendor, audio_setup, monkeypatch, mutation):
    from datetime import UTC, datetime, timedelta

    _, owner, _, _, calls, requests, _ = audio_setup
    event = enqueue(audio_setup)
    monkeypatch.setattr(agent, "source_verified", REAL_SOURCE)
    monkeypatch.setattr(workflow, "prepare_literal_reply", REAL_PREPARE)
    monkeypatch.setattr(workflow, "_check", REAL_CHECK)
    vendor["conversations"] = [
        {
            "id": "internal-thread",
            "accountId": event["account"]["id"],
            "platform": "whatsapp",
            "participantId": "573001110003",
            "threadControl": "app",
        }
    ]
    vendor["messages"] = [
        {
            "id": event["message"]["platformMessageId"],
            "accountId": event["account"]["id"],
            "conversationId": "internal-thread",
            "platform": "whatsapp",
            "senderId": "573001110003",
            "direction": "incoming",
            "message": event["message"]["text"],
            "createdAt": datetime.now(UTC).isoformat(),
        }
    ]

    def mutate():
        if "handover" in mutation:
            vendor["conversations"][0]["threadControl"] = "human"
        elif "window" in mutation:
            vendor["messages"][0]["createdAt"] = (
                datetime.now(UTC) - timedelta(hours=25)
            ).isoformat()

    original = audio_media.prepare

    def prepare(*args):
        plan = original(*args)
        mutate()
        return plan

    monkeypatch.setattr(audio_media, "prepare", prepare)
    if mutation.startswith("pre_"):
        mutate()
    agent.tick()
    assert jobs(owner)[0]["state"] == (
        "completed"
        if mutation == "none"
        else "blocked"
        if mutation.startswith("pre_")
        else "unknown"
    )
    assert len(calls) == (0 if mutation.startswith("pre_") else 1)
    assert len(requests) == (1 if mutation == "none" else 0)


def test_real_audio_child_is_killed_before_a_slow_dns_can_send(audio_setup, monkeypatch, tmp_path):
    import os
    import time

    enqueue(audio_setup)
    source, _ = agent.claim()
    plan = audio_media.prepare(source, MP3)
    marker = tmp_path / "audio-dns-entered"
    setup = f"""
import http.client,os,socket,time
from pathlib import Path
from app.social import audio_media
def slow_dns(host,*args,**kwargs):
    assert host=='zernio-egress'
    Path({str(marker)!r}).write_text(str(os.getpid()))
    time.sleep(3)
    return []
socket.getaddrinfo=slow_dns
def connection(host,timeout):
    assert host=='zernio.com'
    return http.client.HTTPConnection('zernio-egress',1,timeout=3)
audio_media.https_connection=connection
"""
    real_child_fixture(monkeypatch, media, REAL_ISOLATED, setup)
    started = time.monotonic()
    assert audio_media.submit(plan, MP3, "audio-deadline")["state"] == "unknown"
    assert time.monotonic() - started < 1.5
    assert marker.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_official_pause_serializes_with_inflight_audio_and_no_send_after_it_returns(
    audio_setup, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from test_whatsapp_agent import DOC

    client, owner, _, _, _, requests, _ = audio_setup
    enqueue(audio_setup)
    entered, release, pause_started, attempting_lock = (threading.Event() for _ in range(4))
    original_tts = voice.bridge.request
    original_lock = agent.lock

    def tts(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_tts(*args, **kwargs)

    def lock(db):
        if pause_started.is_set():
            attempting_lock.set()
        return original_lock(db)

    def pause():
        pause_started.set()
        return client.patch(
            "/crm/social/whatsapp-agent", json={**DOC, "version": 1, "enabled": False}
        )

    monkeypatch.setattr(voice.bridge, "request", tts)
    monkeypatch.setattr(agent, "lock", lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(agent.tick)
        assert entered.wait(5)
        paused = pool.submit(pause)
        try:
            assert attempting_lock.wait(5)
            assert not paused.done()
        finally:
            release.set()
        running.result(timeout=10)
        result = paused.result(timeout=10)
    assert result.status_code == 200, result.text
    assert result.json()["enabled"] is False
    assert len(requests) == 1 and jobs(owner)[0]["state"] == "completed"
    agent.tick()
    assert len(requests) == 1
