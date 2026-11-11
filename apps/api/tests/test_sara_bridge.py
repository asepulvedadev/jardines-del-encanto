"""Optional speech capability never widens legacy bridge readiness."""

from app.hermes import bridge


def test_legacy_bridge_health_shape_unchanged(monkeypatch):
    monkeypatch.setenv("HERMES_BRIDGE_URL", "http://hermes-bridge:8081")
    monkeypatch.setattr(
        bridge, "request", lambda *args, **kwargs: {"available": True, "model": "fixture"}
    )
    assert bridge.health() == {"configured": True, "available": True, "model": "fixture"}


def test_explicit_transcription_capability_requires_ready_bridge(monkeypatch):
    monkeypatch.setenv("HERMES_BRIDGE_URL", "http://hermes-bridge:8081")
    monkeypatch.setattr(
        bridge,
        "request",
        lambda *args, **kwargs: {
            "available": True,
            "model": "fixture",
            "transcription_available": True,
        },
    )
    assert bridge.health()["transcription_available"] is True
    monkeypatch.setattr(
        bridge,
        "request",
        lambda *args, **kwargs: {"available": False, "transcription_available": True},
    )
    assert bridge.health()["transcription_available"] is False


def test_truthy_string_cannot_enable_speech(monkeypatch):
    monkeypatch.setenv("HERMES_BRIDGE_URL", "http://hermes-bridge:8081")
    monkeypatch.setattr(
        bridge,
        "request",
        lambda *args, **kwargs: {"available": True, "transcription_available": "true"},
    )
    assert bridge.health().get("transcription_available", False) is False


def test_history_capability_is_explicit_and_requires_readiness(monkeypatch):
    monkeypatch.setenv("HERMES_BRIDGE_URL", "http://hermes-bridge:8081")
    monkeypatch.setattr(
        bridge, "request", lambda *a, **k: {"available": True, "history_available": True}
    )
    assert bridge.health()["history_available"] is True
    monkeypatch.setattr(
        bridge, "request", lambda *a, **k: {"available": False, "history_available": True}
    )
    assert bridge.health()["history_available"] is False
