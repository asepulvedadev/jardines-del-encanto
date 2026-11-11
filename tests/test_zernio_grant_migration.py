"""No real credentials: grant migration is allowlisted and destination-locked."""

import importlib.util
import json
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location(
    "migration", Path(__file__).parents[1] / "ops/zernio/migrate_grant.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class GrantMigrationTests(unittest.TestCase):
    def grant(self):
        return {
            "client": {
                "id": "fixture-client",
                "redirect_uri": "http://127.0.0.1:4321/crm?zernio_callback=1",
            },
            "tokens": {
                "access_token": "fixture-access",
                "refresh_token": "fixture-refresh",
                "expires_at": time.time() + 120,
            },
            "pending": {"verifier": "must-not-transfer"},
            "verified_at": 123,
            "account_observations": {"accounts": []},
            "api_key": "must-not-transfer",
        }

    def test_only_durable_allowlisted_fields_transfer(self):
        config = Mock()
        config.locked.return_value = nullcontext()
        config.read_private.return_value = None
        result = migration.import_grant(json.dumps(self.grant()), config)
        saved = config.store_private.call_args.args[1]
        self.assertEqual(set(saved), {"client", "tokens", "grant_generation"})
        self.assertTrue(result["requires_verification"])
        self.assertNotIn("verified_at", saved)

    def test_existing_or_pending_destination_never_overwritten(self):
        for existing in (
            {"tokens": {"access_token": "existing"}},
            {"pending": {"actor": "admin"}},
        ):
            config = Mock()
            config.locked.return_value = nullcontext()
            config.read_private.return_value = existing
            with self.assertRaises(ValueError):
                migration.import_grant(json.dumps(self.grant()), config)
            config.store_private.assert_not_called()

    def test_invalid_source_fails_without_persistence(self):
        for field, value in (
            ("expires_at", float("nan")),
            ("expires_at", True),
            ("access_token", "bad\nvalue"),
        ):
            data = self.grant()
            data["tokens"][field] = value
            with self.assertRaises(ValueError):
                migration.durable_grant(data)
        data = self.grant()
        data["client"]["redirect_uri"] = "https://other.example/crm?zernio_callback=1"
        with self.assertRaises(ValueError):
            migration.durable_grant(data)

    def test_oversized_source_is_rejected_before_storage(self):
        config = Mock()
        with self.assertRaises(ValueError):
            migration.import_grant(" " * (migration.MAXIMUM + 1), config)
        config.locked.assert_not_called()
