"""Credential provisioning never adopts unrelated roles or leaks privileged settings."""

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("crm_provision", Path(__file__).parents[1] / "ops/crm-provision.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="jardines-provision-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "secrets"
        self.folder.mkdir(mode=0o700)

    def test_rejects_other_projects_before_database_access(self):
        with patch.object(module, "database") as database:
            with self.assertRaises(ValueError):
                module.provision("unrelated", self.root)
        database.assert_not_called()

    def test_existing_role_without_managed_credentials_is_not_adopted(self):
        with patch.object(module, "database", return_value="jardines_crm_app"):
            with self.assertRaisesRegex(ValueError, "refusing adoption"):
                module.provision(root=self.root)
        self.assertFalse((self.folder / "crm-credentials.json").exists())

    def test_private_write_rejects_symlink(self):
        target = self.folder / "outside"
        target.write_text("unchanged")
        path = self.folder / "crm-runtime.env"
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            module.private_write(path, "unsafe")
        self.assertEqual(target.read_text(), "unchanged")

    def test_runtime_and_migrator_secrets_are_separate_and_preserved(self):
        config = {"app": "a" * 64, "migrator": "b" * 64}
        path = self.folder / "crm-credentials.json"
        module.private_write(path, json.dumps(config))

        def database(project, query, name="postgres"):
            if "SELECT rolname" in query:
                return "jardines_crm_app\njardines_crm_migrator"
            if "SELECT rolsuper" in query:
                return "f"
            if "pg_auth_members" in query:
                return "0"
            if "pg_get_userbyid" in query:
                return "jardines_crm_migrator"
            return ""

        with patch.object(module, "database", side_effect=database) as db:
            module.provision(root=self.root)
        runtime = (self.folder / "crm-runtime.env").read_text()
        self.assertIn(config["app"], runtime)
        self.assertNotIn(config["migrator"], runtime)
        self.assertEqual(json.loads(path.read_text()), config)
        self.assertEqual((self.folder / "crm-runtime.env").stat().st_mode & 0o777, 0o600)
        self.assertFalse(any("PASSWORD" in call.args[1] for call in db.call_args_list))


if __name__ == "__main__":
    unittest.main()
