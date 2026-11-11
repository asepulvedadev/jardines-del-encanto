"""Private server credentials, never exposed through an HTTP response or database."""

import fcntl
import json
import os
import secrets
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException


def directory():
    configured = os.getenv("ZERNIO_CONFIG_DIR")
    if not configured or not Path(configured).is_absolute():
        raise HTTPException(503, "zernio_not_configured")
    return Path(configured)


def load():
    try:
        folder = directory()
        if folder.is_symlink():
            raise ValueError
        if not folder.exists():
            return None
        if stat.S_IMODE(folder.stat().st_mode) != 0o700:
            raise ValueError
        fd = os.open(folder / "credentials.json", os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as file:
            if stat.S_IMODE(os.fstat(file.fileno()).st_mode) != 0o600:
                raise ValueError
            data = json.loads(file.read(16385))
        if not isinstance(data, dict) or not all(
            isinstance(data.get(key), str) and data[key]
            for key in ("api_key", "profile_id", "profile_name", "webhook_secret")
        ):
            raise ValueError
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "zernio_configuration_unavailable") from None


def required():
    credentials = load()
    if not credentials:
        raise HTTPException(503, "zernio_not_configured")
    return credentials


@contextmanager
def locked():
    """Serialize credential rotation with provider/state mutations across workers."""
    folder = directory()
    try:
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        if folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode) != 0o700:
            raise OSError
        fd = os.open(folder / "settings.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as lock:
            if stat.S_IMODE(os.fstat(lock.fileno()).st_mode) != 0o600:
                raise OSError
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    except OSError:
        raise HTTPException(503, "zernio_configuration_unavailable") from None


def store(data):
    folder = directory()
    path = None
    try:
        fd, path = tempfile.mkstemp(prefix=".credentials-", dir=folder)
        with os.fdopen(fd, "w") as file:
            json.dump(data, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(path, folder / "credentials.json")
        path = None
        directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        raise HTTPException(503, "zernio_configuration_unavailable") from None
    finally:
        if path:
            os.unlink(path)


def new_secret():
    return secrets.token_urlsafe(48)
