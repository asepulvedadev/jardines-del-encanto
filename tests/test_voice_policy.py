"""Validate the actual merged policy without reading env files or using a daemon."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VoicePolicyTests(unittest.TestCase):
    def test_gateway_overlay_preserves_existing_api_isolation(self):
        if not shutil.which("docker"):
            self.skipTest("Docker Compose CLI unavailable; no daemon is required")
        command = [
            "docker",
            "compose",
            "-f",
            "ops/crm.compose.yaml",
            "-f",
            "ops/elevenlabs/compose.yaml",
            "config",
            "--no-env-resolution",
            "--no-path-resolution",
            "--format",
            "json",
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "RELEASE": "a" * 40},
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        policy = json.loads(result.stdout)
        api, gateway = (policy["services"][key] for key in ("api", "voice-gateway"))
        self.assertEqual(set(api["networks"]), {"app", "data", "voice"})
        self.assertEqual(set(gateway["networks"]), {"voice", "voice_egress"})
        self.assertTrue(policy["networks"]["voice"]["internal"])
        self.assertFalse(gateway.get("ports"))
        self.assertTrue(gateway["read_only"])
        self.assertEqual(gateway["user"], "10001:10001")
        self.assertIn("ALL", gateway["cap_drop"])
        self.assertIn("no-new-privileges:true", gateway["security_opt"])
        self.assertEqual(
            [item["source"] for item in api["secrets"]], ["elevenlabs_gateway_token"]
        )
        for volume in api.get("volumes", []):
            self.assertNotEqual(volume["source"], "voice_config")
        self.assertEqual(
            {item["source"] for item in gateway["secrets"]},
            {"elevenlabs_gateway_token"},
        )
        self.assertNotIn("voice", policy["services"]["web"]["networks"])
        self.assertNotIn("voice", policy["services"]["db"]["networks"])
        self.assertNotIn("voice", policy["services"]["zernio-egress"]["networks"])
