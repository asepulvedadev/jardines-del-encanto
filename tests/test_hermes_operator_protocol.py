"""Extension lifecycle stays inside the one typed application tool."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "ops/hermes"))
from operator_protocol import ACTIONS, call_arguments, tool_schema  # noqa: E402


class ExtensionProtocolTests(unittest.TestCase):
    def test_extension_lifecycle_requires_explicit_typed_action(self):
        actions = [
            "control.extension." + name
            for name in ("create", "update", "install", "test")
        ]
        self.assertTrue(set(actions) <= ACTIONS)
        schema = {
            "type": "function",
            "function": {
                "name": "jardines_app",
                "description": "Typed extensions only",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": actions},
                        "arguments": {"type": "object"},
                    },
                    "required": ["action", "arguments"],
                    "additionalProperties": False,
                },
            },
        }
        self.assertEqual(tool_schema(schema), schema)
        self.assertEqual(
            call_arguments(
                {"action": "control.extension.test", "arguments": {}}, actions
            )["action"],
            actions[-1],
        )
        for denied in (
            "shell.run",
            "filesystem.write",
            "skill.install",
            "control.extension.exec",
        ):
            with self.subTest(action=denied), self.assertRaises(ValueError):
                call_arguments({"action": denied, "arguments": {}}, actions)


class VoiceProtocolTests(unittest.TestCase):
    def test_voice_actions_use_only_the_application_broker(self):
        self.assertTrue({"voice.catalog", "voice.execute"} <= ACTIONS)
        for denied in ("voice.configure", "voice.session.claim", "elevenlabs.http", "voice.call.direct"):
            self.assertNotIn(denied, ACTIONS)
            with self.assertRaises(ValueError):
                call_arguments({"action": denied, "arguments": {}}, ACTIONS)

    def test_paid_voice_actions_are_explicit_not_native_tools(self):
        for action in ("voice.catalog", "voice.execute"):
            self.assertEqual(call_arguments({"action": action, "arguments": {}}, ACTIONS)["action"], action)
        source = (Path(__file__).parents[1] / "ops/hermes/operator.py").read_text()
        self.assertIn("voice.catalog", source)
        self.assertIn("voice.execute", source)
        self.assertIn("Never request API keys", source)
