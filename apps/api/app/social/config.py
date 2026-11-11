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


def read_private(name, maximum=16384):
    if name not in {"credentials.json", "mcp.json"}:
        raise ValueError("Unsupported private configuration")
    try:
        folder = directory()
        if folder.is_symlink():
            raise ValueError
        if not folder.exists():
            return None
        if stat.S_IMODE(folder.stat().st_mode) != 0o700:
            raise ValueError
        fd = os.open(folder / name, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError
            raw = file.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError
            data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "zernio_configuration_unavailable") from None


def load():
    data = read_private("credentials.json")
    if data is not None and not all(
        isinstance(data.get(key), str) and data[key]
        for key in ("api_key", "profile_id", "profile_name", "webhook_secret")
    ):
        raise HTTPException(503, "zernio_configuration_unavailable")
    return data


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


def store_private(name, data):
    if name not in {"credentials.json", "mcp.json"}:
        raise ValueError("Unsupported private configuration")
    folder = directory()
    path = None
    try:
        fd, path = tempfile.mkstemp(prefix=".credentials-", dir=folder)
        with os.fdopen(fd, "w") as file:
            json.dump(data, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(path, folder / name)
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


def store(data):
    store_private("credentials.json", data)


def new_secret():
    return secrets.token_urlsafe(48)
