"""Shared provider and Hermes wiring without a database or provider requests."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.control import service
from app.hermes import broker


class Database:
    def __init__(self, preferences=()):
        self.preferences = preferences

    def execute(self, query, args=None):
        self.query = query
        return self

    def fetchall(self):
        return self.preferences if "FROM crm.control_connections" in self.query else []

    def fetchone(self):
        return None


class RetellWiringTests(unittest.TestCase):
    def views(self, state):
        rows = [
            {"key": "zernio", "enabled": False, "version": 1},
            {"key": "retell", "enabled": True, "version": 1},
            {"key": "future-provider", "enabled": True, "version": 1},
        ]
        with (
            patch("app.hermes.bridge.health", return_value={"available": False}),
            patch(
                "app.voice.service.state",
                return_value={"available": False, "verified": False},
            ),
            patch("app.retell.service.state", return_value=state),
            patch(
                "app.social.routes.settings",
                return_value={"configured": False, "oauth": {}, "connections": []},
            ),
        ):
            return service.connection_views(Database(rows))

    def test_new_provider_does_not_inherit_zernio_or_expose_unknown_future_rows(self):
        rows = self.views({"available": True, "configured": True, "verified": True})
        self.assertEqual([row["key"] for row in rows], ["zernio", "retell"])
        self.assertTrue(rows[1]["effective"])

    def test_provider_requires_configuration_even_if_gateway_claims_verification(self):
        rows = self.views({"available": True, "configured": False, "verified": True})
        self.assertFalse(rows[1]["available"])
        self.assertFalse(rows[1]["effective"])

    def test_compact_manifest_is_accepted_by_installed_policy_contract(self):
        manifest = broker.tools(Database())[0]
        self.assertLessEqual(len(manifest["function"]["description"].encode()), 16384)
        actions = manifest["function"]["parameters"]["properties"]["action"]["enum"]
        self.assertTrue(
            {"retell.catalog", "retell.schema", "retell.execute"} <= set(actions)
        )
        spec = importlib.util.spec_from_file_location(
            "retell_test_protocol", ROOT / "ops/hermes/operator_protocol.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.tool_schema(manifest), manifest)


if __name__ == "__main__":
    unittest.main()


class RetellProductionDependencies(unittest.TestCase):
    def test_gateway_dependency_is_in_hashed_container_requirements(self):
        requirements = (ROOT / 'apps/api/requirements.txt').read_text()
        self.assertTrue('jsonschema==4.26.0' in requirements, 'Production image requires pinned jsonschema')
        self.assertTrue('jsonschema-specifications==' in requirements, 'Production schema resources missing')
