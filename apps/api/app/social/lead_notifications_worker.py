"""Small durable scheduler: Colombian clock, independent of LLM availability."""

import os
import threading
from time import monotonic

from . import lead_notifications

_stop = threading.Event()
_thread = None
_heartbeat = 0.0
_error = None


def _loop():
    global _heartbeat, _error
    while not _stop.is_set():
        try:
            lead_notifications.tick()
            _heartbeat, _error = monotonic(), None
        except Exception:  # noqa: BLE001 - no sensitive provider/body logging
            _error = "notice_worker_unavailable"
        _stop.wait(5)


def start():
    global _thread
    # Persisted opt-in is still required. Local/preview never sends by default.
    if (
        os.getenv("CRM_ORIGIN") != "https://jardinesdelencanto.site"
        or os.getenv("CRM_INTERNAL_NOTICES_DISABLED") == "1"
    ):
        return
    if _thread is None or not _thread.is_alive():
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="crm-internal-notices", daemon=True)
        _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
