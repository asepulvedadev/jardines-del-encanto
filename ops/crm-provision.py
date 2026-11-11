#!/usr/bin/python3
"""Administrator-only, project-scoped CRM database provisioning; never prints secrets."""

import argparse
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

ROOT = Path("/srv/jardines-del-encanto")
ORIGIN = "https://jardines.2.24.111.40.sslip.io"


def database(project, query, name="postgres"):
    result = subprocess.run(
        ["docker", "exec", "-i", f"{project}-db-1", "psql", "-X", "-q", "-t", "-A",
         "-v", "ON_ERROR_STOP=1", "-U", "jardines", "-d", name],
        input=query, text=True, capture_output=True, check=False,
    )
    if result.returncode:
        # Driver/psql diagnostics can contain connection or statement information.
        raise RuntimeError("Project CRM database provisioning failed; no credentials were printed")
    return result.stdout.strip()


def private_write(path, content):
    if path.is_symlink():
        raise ValueError("Refusing a symlink in the project secret directory")
    descriptor, temporary = tempfile.mkstemp(prefix=".crm-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def provision(project="jardines", root=ROOT):
    if not re.fullmatch(r"jardines(?:-ci|-release-check)?", project):
        raise ValueError("Only the project production or isolated verification stack is supported")
    folder = root / "secrets"
    if folder.is_symlink():
        raise ValueError("Refusing a symlink secret directory")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise ValueError("Project secret directory must be private")
    path = folder / "crm-credentials.json"
    existing = database(project, "SELECT rolname FROM pg_roles WHERE rolname IN "
                        "('jardines_crm_migrator','jardines_crm_app');")
    if not path.exists():
        if existing:
            raise ValueError("Existing CRM roles have no saved credentials; refusing adoption or rotation")
        private_write(path, json.dumps({role: secrets.token_hex(32) for role in ("migrator", "app")}))
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("CRM credential file must be private and not a symlink")
    config = json.loads(path.read_text())
    for role in ("migrator", "app"):
        password = config.get(role, "")
        if not isinstance(password, str) or not re.fullmatch(r"[0-9a-f]{64}", password):
            raise ValueError("Invalid saved CRM credentials")
        username = "jardines_crm_" + role
        if username not in existing.splitlines():
            database(project, f"CREATE ROLE {username} LOGIN NOSUPERUSER NOCREATEDB "
                     f"NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}';")
        privileged = database(project, f"SELECT rolsuper OR rolcreatedb OR rolcreaterole OR "
                              f"rolreplication OR rolbypassrls OR NOT rolcanlogin "
                              f"FROM pg_roles WHERE rolname='{username}';")
        memberships = database(project, "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r "
                               f"ON r.oid=m.member WHERE r.rolname='{username}';")
        if privileged != "f" or memberships != "0":
            raise ValueError("CRM role has unexpected privilege or membership")
    owner = database(project, "SELECT pg_get_userbyid(datdba) FROM pg_database "
                     "WHERE datname='jardines_crm';")
    if not owner:
        database(project, "CREATE DATABASE jardines_crm OWNER jardines_crm_migrator;")
    elif owner != "jardines_crm_migrator":
        raise ValueError("Existing CRM database has an unexpected owner; refusing adoption")
    database(project, "REVOKE ALL ON DATABASE jardines_crm FROM PUBLIC; "
             "GRANT CONNECT ON DATABASE jardines_crm TO jardines_crm_migrator,jardines_crm_app;")
    database(project, "REVOKE CREATE ON SCHEMA public FROM PUBLIC;", "jardines_crm")
    runtime = (f"CRM_DATABASE_URL=postgresql://jardines_crm_app:{config['app']}@db:5432/jardines_crm\n"
               f"CRM_ORIGIN={ORIGIN}\nZERNIO_CONFIG_DIR=/var/lib/jardines-zernio\n")
    maintenance = ("CRM_MIGRATION_DATABASE_URL=postgresql://jardines_crm_migrator:"
                   f"{config['migrator']}@db:5432/jardines_crm\n")
    private_write(folder / "crm-runtime.env", runtime)
    private_write(folder / "crm-migration.env", maintenance)
    print("Dedicated CRM roles, database and private environment files are ready. Passwords unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=["jardines", "jardines-ci", "jardines-release-check"],
                        default="jardines")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run through the authorized administrator session as root")
    os.umask(0o077)
    provision(args.project)
