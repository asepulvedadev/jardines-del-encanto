"""Comment reconciliation is an app worker, not a desktop scheduled automation."""

import os
import threading

from ..crm.database import connect
from . import comment_moderation as moderation

_stop = threading.Event()
_thread = None


def loop():
    while not _stop.is_set():
        try:
            moderation.tick()
        except Exception:  # noqa: BLE001 - no secrets, commenter text or external bodies
            try:
                with connect() as db:
                    db.execute(
                        "UPDATE crm.comment_moderation_runtime SET last_error='moderation_unavailable' WHERE singleton"
                    )
            except Exception:  # noqa: BLE001
                _stop.wait(1)
        _stop.wait(10)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    if os.getenv("SARA_COMMENT_WORKER_ENABLED") != "1":
        return
    _stop.clear()
    _thread = threading.Thread(target=loop, name="sara-comment-review", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
