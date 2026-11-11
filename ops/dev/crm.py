"""Local-only CRM runner. Secrets are generated in an ignored, private directory."""

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg
from preview_config import write_preview_configuration
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".local" / "crm"
sys.path.insert(0, str(ROOT / "apps" / "api"))


def configuration():
    if not (STATE / "config.json").exists():
        raise SystemExit("Run init first")
    return json.loads((STATE / "config.json").read_text())


def dsn(config, role, database):
    return f"postgresql://jardines_crm_{role}:{config[role]}@127.0.0.1:15432/{database}"


def environment(config):
    return {
        **os.environ,
        "CRM_DATABASE_URL": dsn(config, "app", "jardines_crm"),
        "CRM_MIGRATION_DATABASE_URL": dsn(config, "migrator", "jardines_crm"),
        "CRM_TEST_DATABASE_URL": dsn(config, "app", "jardines_crm_test"),
        "CRM_TEST_MIGRATION_DATABASE_URL": dsn(config, "migrator", "jardines_crm_test"),
        "CRM_ORIGIN": "http://127.0.0.1:4320",
        "CRM_ALLOW_INSECURE_HTTP": "1",
        "API_BASE_URL": "http://127.0.0.1:8001",
        "ZERNIO_CONFIG_DIR": str(ROOT / ".local" / "zernio" / "private"),
        "PYTHONPATH": str(ROOT / "apps" / "api"),
    }


def initialize():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (STATE / "config.json").exists():
        config = {key: secrets.token_hex(32) for key in ("owner", "migrator", "app")}
        (STATE / "config.json").write_text(json.dumps(config))
        (STATE / "config.json").chmod(0o600)
        (STATE / "database-password").write_text(config["owner"])
        (STATE / "database-password").chmod(0o444)
    config = configuration()
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "ops/dev/compose.yaml"),
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "90",
        ],
        check=True,
    )
    with psycopg.connect(
        host="127.0.0.1",
        port=15432,
        dbname="postgres",
        user="jardines_local_owner",
        password=config["owner"],
        autocommit=True,
    ) as db:
        for role in ("migrator", "app"):
            username = "jardines_crm_" + role
            if not db.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (username,)
            ).fetchone():
                db.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(username), sql.Literal(config[role]))
                )
        for name in ("jardines_crm", "jardines_crm_test"):
            if not db.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (name,)
            ).fetchone():
                db.execute(
                    sql.SQL("CREATE DATABASE {} OWNER jardines_crm_migrator").format(
                        sql.Identifier(name)
                    )
                )
    from app.crm.manage import migrate

    for name in ("jardines_crm", "jardines_crm_test"):
        migrate(dsn(config, "migrator", name))
    write_preview_configuration(config)
    print("Local PostgreSQL initialized. Runtime and migration roles are separate.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init", "api", "web", "create-admin", "test"]
    )
    args = parser.parse_args()
    if args.command == "init":
        initialize()
        return
    env = environment(configuration())
    commands = {
        "api": [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        "web": [
            "npm",
            "run",
            "dev",
            "--workspace=apps/web",
            "--",
            "--hostname",
            "127.0.0.1",
            "--port",
            "4320",
        ],
        "create-admin": [sys.executable, "-m", "app.crm.manage", "create-admin"],
        "test": [sys.executable, "-m", "pytest", str(ROOT / "apps/api/tests"), "-q"],
    }
    raise SystemExit(subprocess.call(commands[args.command], cwd=ROOT, env=env))


if __name__ == "__main__":
    main()
