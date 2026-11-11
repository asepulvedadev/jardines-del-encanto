"""A failed CRM discovery query must prevent a falsely successful safety backup."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


class BackupTests(unittest.TestCase):
    def test_failed_crm_discovery_is_a_backup_failure(self):
        with TemporaryDirectory(prefix="jardines-backup-") as temporary:
            root = Path(temporary)
            (root / "backups").mkdir()
            (root / "current").write_text("a" * 40 + "\n")
            script = root / "backup.sh"
            source = (Path(__file__).parents[1] / "ops/backup.sh").read_text()
            script.write_text(source.replace("base=/srv/jardines-del-encanto", f"base={root}"))
            docker = root / "docker"
            docker.write_text('#!/bin/sh\ncase " $* " in *" pg_dump "*) echo "-- isolated dump";; *" psql "*) exit 42;; *) exit 1;; esac\n')
            docker.chmod(0o700)
            result = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True, check=False,
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}"},
            )
            self.assertEqual(result.returncode, 42)
            self.assertNotIn("CRM backup created", result.stdout)


if __name__ == "__main__":
    unittest.main()
