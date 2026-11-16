"""Offline image dispatch and published profile protocol integration."""

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops/hermes"))
spec = importlib.util.spec_from_file_location(
    "jardines_operator", Path(__file__).resolve().parents[1] / "ops/hermes/operator.py"
)
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)
provider = importlib.import_module("operator_provider")
protocol = importlib.import_module("operator_protocol")


def test_image_provider_route_is_exact_and_uses_dedicated_generator():
    images = importlib.import_module("image_server")
    payload = {"prompt": "concept", "reference_images": [], "size": "1024x1024"}
    h = Mock(path="/images/generate")
    h.server.role = "provider"
    h.server.generator.return_value = {
        "ok": False,
        "error": "image_generation_unavailable",
    }
    with patch.object(images, "read_json", return_value=payload) as read:
        images.Handler.do_POST(h)
        h.server.generator.assert_called_once_with(payload)
        assert read.call_args.args[1] == 4 * 1024 * 1024
        h.reply.assert_called_once_with(502, images.FAILURE)


def test_dedicated_bridge_frame_is_bounded_and_only_fixed_private_path():
    images = importlib.import_module("image_server")
    payload = {"prompt": "concept", "reference_images": [], "size": "1024x1024"}
    h = Mock(path="/generate-image")
    h.server.role = "bridge"
    h.server.provider.generate.side_effect = ValueError("private upstream error")
    with patch.object(images, "read_json", return_value=payload) as read:
        images.Handler.do_POST(h)
        assert read.call_args.args[1] == 4 * 1024 * 1024
        h.server.provider.generate.assert_called_once_with(payload)
        h.reply.assert_called_once_with(502, images.FAILURE)
    assert images.provider_endpoint("http://image-provider:8083") == (
        "image-provider",
        8083,
    )
    assert images.MAX_REPLY == 12 * 1024 * 1024


def test_configuration_claim_bounded_and_runtime_authority_denied():
    tool = {
        "type": "function",
        "function": {
            "name": "jardines_app",
            "description": "test",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["sara.config.get", "images.generate"],
                    },
                    "arguments": {"type": "object"},
                },
                "required": ["action", "arguments"],
                "additionalProperties": False,
            },
        },
    }
    cfg = {
        "version": 1,
        "name": "Sara",
        "instructions": "Proyecto",
        "knowledge": "Hechos",
        "greeting": "Hola",
        "response_style": "brief",
    }
    claim = {
        "run_id": "run",
        "prompt": "hola",
        "skills": [],
        "tools": [tool],
        "configuration": cfg,
    }
    assert protocol.validate_claim(claim) == claim
    for patchvalue in (
        {"api_key": "secret"},
        {"version": True},
        {"knowledge": "x" * 4001},
    ):
        with pytest.raises(ValueError):
            protocol.validate_claim({**claim, "configuration": {**cfg, **patchvalue}})


def test_actual_public_bridge_envelope_completes_simulation_without_business_io():
    from contextlib import nullcontext

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
    from app.sara import profile, simulations

    agent = Mock(tools=[])
    agent.run_conversation.return_value = {"final_response": "Respuesta sintética."}
    payload = {
        "messages": [{"role": "user", "content": "Hola"}],
        "instructions": "Breve",
        "knowledge": "Proyecto",
    }
    # Exercise the actual producer, not a separately invented mock envelope.
    answer = operator.run_public_reply(
        payload, Mock(ip="127.0.0.1", port=1), (Mock(return_value=agent), Mock())
    )
    db = Mock()
    db.execute.return_value.fetchone.return_value = {"id": "owner"}
    row = {
        "id": "synthetic",
        "owner_id": "owner",
        "input": {"customer_turns": ["Hola"]},
        "profile": profile.DEFAULT,
    }
    with (
        patch.object(simulations, "connect", lambda: nullcontext(db)),
        patch.object(simulations, "claim", lambda _: row),
        patch.object(simulations.control, "require_connections", lambda *a: None),
        patch.object(simulations.bridge, "request", return_value=answer),
    ):
        simulations.tick()
    saved = db.execute.call_args.args[1]
    assert saved[0] == "completed"
    assert saved[1].obj == [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Respuesta sintética."},
    ]
