"""Fixed internal media subprocess. Credentials travel through stdin, never argv/logs."""

import base64
import json
import sys

from ..crm.database import connect
from . import media, workflow


def execute(frame):
    from . import audio_media

    if frame.get("operation", "").startswith("welcome_") and set(frame) == {"operation", "id"}:
        from . import onboarding_transport

        return onboarding_transport.execute(frame["operation"], frame["id"])
    if frame.get("operation") == "prepare_audio" and set(frame) == {"operation", "source"}:
        source = frame["source"]
        if set(source) != {"id", "account_id", "conversation_id", "participant_id"}:
            raise ValueError
        with connect() as db:
            return workflow.prepare_literal_reply(db, source, audio_media.CAPTION)
    if frame.get("operation") == "submit_audio" and set(frame) == {
        "operation", "plan", "credentials", "data_base64", "request_id"
    }:
        data = base64.b64decode(frame["data_base64"], validate=True)
        return audio_media.transmit(frame["plan"], data, frame["credentials"], frame["request_id"])
    if frame.get("operation") == "prepare" and set(frame) == {"operation", "source"}:
        source = frame["source"]
        if set(source) != {"id", "account_id", "conversation_id", "participant_id"}:
            raise ValueError
        with connect() as db:
            return workflow.prepare_literal_reply(db, source, media.CAPTION)
    if frame.get("operation") == "submit" and set(frame) == {
        "operation",
        "plan",
        "credentials",
        "data_base64",
        "request_id",
    }:
        data = base64.b64decode(frame["data_base64"], validate=True)
        return media._transmit(frame["plan"], data, frame["credentials"], frame["request_id"])
    raise ValueError


def main():
    try:
        maximum = media.MAX_ATTACHMENT * 4 // 3 + 65536
        raw = sys.stdin.buffer.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError
        frame = json.loads(raw)
        if not isinstance(frame, dict):
            raise TypeError
        result = execute(frame)
        encoded = json.dumps({"ok": True, "result": result}, separators=(",", ":"))
        if len(encoded.encode()) > 65536:
            raise ValueError
        print(encoded)
    except Exception:  # noqa: BLE001 - No provider details, key, body or traceback is emitted.
        print('{"ok":false,"result":{}}')


if __name__ == "__main__":
    main()
