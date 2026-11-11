"""Deployment commands must reject arbitrary SSH input before side effects."""

import importlib.util
import unittest
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).parents[1] / "ops/deploy.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CommandTests(unittest.TestCase):
    def test_exact_deploy_sha(self):
        sha = "a" * 40
        self.assertEqual(module.parse_command("deploy " + sha), ("deploy", sha))

    def test_rollback_only_existing_sha_format(self):
        sha = "b" * 40
        self.assertEqual(module.parse_command("rollback " + sha), ("rollback", sha))

    def test_reject_shell_and_invalid_arguments(self):
        for value in [
            "",
            "id",
            "deploy main",
            "deploy " + "a" * 40 + "; id",
            "deploy " + "a" * 40 + " extra",
            "deploy ../etc",
            "deploy " + "A" * 40,
            "deploy " + "a" * 39,
            "rollback latest",
            "deploy\n" + "a" * 40,
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.parse_command(value)

    def test_invalid_command_exits_before_side_effects(self):
        result = subprocess.run(
            [sys.executable, str(spec.origin), "deploy main"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Expected:", result.stderr)


class DeploymentStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="jardines-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ["healthy", "releases"]:
            (self.root / name).mkdir()
        self.previous = "a" * 40
        self.target = "b" * 40
        (self.root / "current").write_text(self.previous + "\n")
        self.root_patch = patch.object(module, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_unknown_rollback_does_not_activate_or_change_current(self):
        with patch.object(module, "run"), patch.object(module, "activate") as activate:
            with self.assertRaises(ValueError):
                module.deploy("rollback", self.target)
        activate.assert_not_called()
        self.assertEqual((self.root / "current").read_text(), self.previous + "\n")

    def test_successful_rollback_updates_current_after_activation(self):
        (self.root / "healthy" / self.target).touch()
        with patch.object(module, "run"), patch.object(module, "activate") as activate:
            module.deploy("rollback", self.target)
        activate.assert_called_once_with(self.target)
        self.assertEqual((self.root / "current").read_text(), self.target + "\n")

    def test_failed_activation_restores_previous_and_preserves_pointer(self):
        (self.root / "healthy" / self.target).touch()
        with (
            patch.object(module, "run"),
            patch.object(
                module, "activate", side_effect=[RuntimeError("unhealthy"), None]
            ) as activate,
        ):
            with self.assertRaises(RuntimeError):
                module.deploy("rollback", self.target)
        self.assertEqual(
            [call.args[0] for call in activate.call_args_list],
            [self.target, self.previous],
        )
        self.assertEqual((self.root / "current").read_text(), self.previous + "\n")

    def test_stale_deployment_is_rejected_before_builds(self):
        with (
            patch.object(module, "run"),
            patch.object(module, "git") as git,
            patch.object(module, "activate") as activate,
        ):
            git.return_value.stdout = self.previous + "\n"
            with self.assertRaisesRegex(ValueError, "stale"):
                module.deploy("deploy", self.target)
        activate.assert_not_called()
        self.assertFalse((self.root / "releases" / self.target).exists())

    def test_interrupted_materialization_is_not_reused(self):
        with (
            patch.object(module, "git"),
            patch.object(module.tarfile, "open", side_effect=OSError),
        ):
            with self.assertRaises(OSError):
                module.materialize(self.target)
        self.assertFalse((self.root / "releases" / self.target).exists())
        with (
            patch.object(module, "git"),
            patch.object(module.tarfile, "open") as archive,
        ):
            archive.return_value.__enter__.return_value.getmembers.return_value = []
            module.materialize(self.target)
        self.assertTrue((self.root / "releases" / self.target).is_dir())
        archive.assert_called_once()

    def test_builder_must_have_project_resource_caps(self):
        with patch.object(module, "run") as run:
            run.return_value.stdout = (
                '{"Memory":0,"CpuQuota":0,"CpuPeriod":0,"PidsLimit":0}'
            )
            with self.assertRaisesRegex(ValueError, "builder"):
                module.verify_builder()

    def test_operator_refresh_follows_application_readiness(self):
        events = []
        with (
            patch.object(module, "compose", side_effect=lambda *args: events.append("compose")),
            patch.object(module, "run", side_effect=lambda *args: events.append("health")),
            patch.object(module, "refresh_operator", side_effect=lambda: events.append("operator")),
        ):
            module.activate(self.target)
        self.assertEqual(events, ["compose", "health", "operator"])

    def test_operator_refresh_does_not_activate_an_absent_or_stopped_profile(self):
        with patch.object(module, "run") as run:
            module.refresh_operator()
            run.assert_not_called()
            policy = self.root / "hermes-operator" / "operator.compose.yaml"
            policy.parent.mkdir()
            policy.touch()
            run.return_value.stdout = "operator-provider\n"
            module.refresh_operator()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][-4:], ["ps", "--status", "running", "--services"])

    def test_operator_refresh_restarts_only_running_bridge_after_api_ip_changes(self):
        policy = self.root / "hermes-operator" / "operator.compose.yaml"
        policy.parent.mkdir()
        policy.touch()
        with patch.object(module, "run") as run:
            run.return_value.stdout = "operator-provider\nhermes-bridge\n"
            module.refresh_operator()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][-3:], ["restart", "--no-deps", "hermes-bridge"])
        self.assertIn(str(policy), run.call_args.args[0])

    def test_optional_operator_failure_does_not_fail_healthy_application(self):
        policy = self.root / "hermes-operator" / "operator.compose.yaml"
        policy.parent.mkdir()
        policy.touch()
        with patch.object(module, "run", side_effect=subprocess.CalledProcessError(1, "docker")):
            module.refresh_operator()

    def test_runtime_policy_is_bound_to_each_release(self):
        markers = self.root / "crm-releases"
        markers.mkdir()
        (markers / self.target).touch()
        with patch.object(module.subprocess, "run") as run:
            module.compose(self.previous, "config", "--quiet")
            self.assertIn(str(self.root / "compose.yaml"), run.call_args.args[0])
            module.compose(self.target, "config", "--quiet")
            self.assertIn(str(self.root / "crm.compose.yaml"), run.call_args.args[0])

    def test_migrations_complete_before_application_activation(self):
        events = []
        with (
            patch.object(module, "run"),
            patch.object(module, "git") as git,
            patch.object(module, "materialize", return_value=self.root / "releases" / self.target),
            patch.object(module, "verify_builder"),
            patch.object(module, "prepare_crm", create=True, side_effect=lambda sha: events.append("migrate")),
            patch.object(module, "activate", side_effect=lambda sha: events.append("activate")),
        ):
            git.return_value.stdout = self.target + "\n"
            module.deploy("deploy", self.target)
        self.assertEqual(events, ["migrate", "activate"])

    def test_failed_migration_restores_previous_without_advancing_release(self):
        with (
            patch.object(module, "run"),
            patch.object(module, "git") as git,
            patch.object(module, "materialize", return_value=self.root / "releases" / self.target),
            patch.object(module, "verify_builder"),
            patch.object(module, "prepare_crm", create=True, side_effect=RuntimeError("migration failed")),
            patch.object(module, "activate") as activate,
        ):
            git.return_value.stdout = self.target + "\n"
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                module.deploy("deploy", self.target)
        activate.assert_called_once_with(self.previous)
        self.assertEqual((self.root / "current").read_text(), self.previous + "\n")


if __name__ == "__main__":
    unittest.main()
