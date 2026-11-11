"""Generate API-only configuration for the isolated local Docker preview."""
import os
from pathlib import Path

STATE = Path(__file__).resolve().parents[2] / ".local" / "crm"


def write_preview_configuration(config):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = (
        "CRM_DATABASE_URL=postgresql://jardines_crm_app:"
        + config["app"]
        + "@db:5432/jardines_crm\n"
        "CRM_ORIGIN=http://127.0.0.1:4321\n"
        "CRM_ALLOW_INSECURE_HTTP=1\n"
    )
    path = STATE / "app.env"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, value.encode())
    finally:
        os.close(fd)
