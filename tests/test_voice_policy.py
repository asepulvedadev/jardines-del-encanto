"""Validate the actual merged policy without reading env files or using a daemon."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


class VoicePolicyTests(unittest.TestCase):
    def test_gateway_overlay_preserves_existing_api_isolation(self):
        if not shutil.which("docker"):
            self.skipTest("Docker Compose CLI unavailable; no daemon is required")
        command = [
            "docker",
            "compose",
            "-f",
            "-",
            "-f",
            "ops/elevenlabs/compose.yaml",
            "config",
            "--no-env-resolution",
            "--no-path-resolution",
            "--format",
            "json",
        ]
        # Some Compose versions still stat env_file paths with --no-env-resolution.
        # Only substitute the env-file inputs; validate the actual isolation policy.
        with TemporaryDirectory(prefix="jardines-compose-policy-") as scratch:
            empty_env = Path(scratch) / "empty.env"
            empty_env.touch()
            base = (ROOT / "ops/crm.compose.yaml").read_text()
            for filename in ("crm-runtime.env", "crm-migration.env"):
                source = f"/srv/jardines-del-encanto/secrets/{filename}"
                self.assertIn(f"env_file: {source}", base)
                base = base.replace(f"env_file: {source}", f"env_file: {empty_env}")
            result = subprocess.run(
                command,
                input=base,
                cwd=ROOT,
                env={**os.environ, "RELEASE": "a" * 40},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
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
