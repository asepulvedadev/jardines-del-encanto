"""Local preview secrets stay in the ignored directory and out of web environment."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("crm_dev", Path(__file__).parents[1] / "ops/dev/preview_config.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreviewConfigurationTests(unittest.TestCase):
    def test_private_api_environment_and_non_root_secret_volume_policy(self):
        with TemporaryDirectory(prefix="jardines-preview-test-") as temporary:
            state = Path(temporary)
            with patch.object(module, "STATE", state):
                module.write_preview_configuration({"app": "test-runtime-password"})
            value = (state / "app.env").read_text()
            self.assertIn("CRM_ORIGIN=http://127.0.0.1:4321", value)
            self.assertIn("@db:5432/jardines_crm", value)
            self.assertEqual((state / "app.env").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("ZERNIO_API_KEY", value)
            compose = (Path(__file__).parents[1] / "ops/dev/app.compose.yaml").read_text()
            self.assertIn("127.0.0.1:4321:3000", compose)
            self.assertIn("social_config:/var/lib/jardines-zernio", compose)
            self.assertNotIn("15432", compose)
            self.assertIn("networks: [app, ingress]", compose)
            self.assertIn("app: { internal: true }", compose)


if __name__ == "__main__":
    unittest.main()
