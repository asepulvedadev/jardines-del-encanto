"""Explicit, privileged maintenance CLI; never exposed over HTTP."""

import argparse
import getpass
import hashlib
import os
from pathlib import Path

import psycopg

from .security import password_hash

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def migrate(url):
    with psycopg.connect(url) as db:
        db.execute("SELECT pg_advisory_xact_lock(9142026)")
        db.execute("CREATE SCHEMA IF NOT EXISTS crm")
        db.execute("REVOKE ALL ON SCHEMA crm FROM PUBLIC")
        db.execute("""CREATE TABLE IF NOT EXISTS crm.schema_migrations (
            version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz DEFAULT now())""")
        for file in sorted(MIGRATIONS.glob("*.sql")):
            content = file.read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()
            old = db.execute(
                "SELECT checksum FROM crm.schema_migrations WHERE version=%s", (file.name,)
            ).fetchone()
            if old:
                if old[0] != checksum:
                    raise ValueError("An applied migration changed; create a new migration instead")
                continue
            db.execute(content)
            db.execute(
                "INSERT INTO crm.schema_migrations(version, checksum) VALUES (%s,%s)",
                (file.name, checksum),
            )


def create_admin(url, username, password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Use a password between 12 and 256 characters")
    with psycopg.connect(url) as db:
        # Never silently reset an existing administrator's password.
        db.execute(
            "INSERT INTO crm.users(username, password_hash) VALUES (%s,%s)",
            (username.lower(), password_hash.hash(password)),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["migrate", "create-admin"])
    parser.add_argument("--username", default="adminjardines")
    args = parser.parse_args()
    url = os.environ["CRM_MIGRATION_DATABASE_URL"]
    if args.command == "migrate":
        migrate(url)
        print("CRM migrations applied.")
    else:
        password = getpass.getpass("Administrator password (not stored in source): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise ValueError("Passwords do not match")
        create_admin(url, args.username, password)
        print("Administrator created. Existing passwords are never overwritten.")


if __name__ == "__main__":
    main()
