"""Private bounded attachment ingestion; no user-selected paths, commands or URLs."""

import base64
import binascii
import json
import re
import subprocess
import sys
from pathlib import Path

from fastapi import HTTPException

from ..control import service as control
from ..crm.database import connect
from ..hermes import bridge

MAX_FILE = 512 * 1024
MAX_TEXT = 16000
MIME_TYPES = {
    "text/plain": {".txt"},
    "text/markdown": {".md"},
    "text/csv": {".csv"},
    "application/pdf": {".pdf"},
    "audio/webm": {".webm"},
    "audio/ogg": {".ogg"},
    "audio/mpeg": {".mp3"},
    "audio/wav": {".wav"},
    "audio/mp4": {".mp4", ".m4a"},
}
ALIASES = {"audio/mp3": "audio/mpeg", "audio/x-wav": "audio/wav"}
FIELDS = ("id", "filename", "mime_type", "size", "kind", "text", "created_at")


def metadata(row, excerpt=None):
    result = {key: row[key] for key in FIELDS}
    if excerpt is not None:
        result["text"] = result["text"][:excerpt]
    return result


def decode(data):
    if (
        any(ord(char) < 32 or ord(char) == 127 for char in data.filename)
        or "/" in data.filename
        or "\\" in data.filename
        or data.filename in (".", "..")
    ):
        raise HTTPException(422, "attachment_invalid_filename")
    mime = data.mime_type.lower()
    if ";" in mime:
        if mime not in ("audio/webm;codecs=opus", "audio/ogg;codecs=opus"):
            raise HTTPException(422, "attachment_invalid_type")
        mime = mime.split(";", 1)[0]
    mime = ALIASES.get(mime, mime)
    if mime not in MIME_TYPES or Path(data.filename).suffix.lower() not in MIME_TYPES[mime]:
        raise HTTPException(422, "attachment_invalid_type")
    try:
        raw = base64.b64decode(data.data_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "attachment_invalid_encoding") from None
    if not 1 <= len(raw) <= MAX_FILE:
        raise HTTPException(413, "attachment_too_large")
    if mime.startswith("audio/"):
        valid = (
            (
                mime == "audio/webm"
                and raw.startswith(b"\x1aE\xdf\xa3")
                and b"webm" in raw[:4096]
                and any(codec in raw for codec in (b"A_OPUS", b"A_VORBIS"))
            )
            or (
                mime == "audio/ogg"
                and raw.startswith(b"OggS")
                and any(codec in raw[:4096] for codec in (b"OpusHead", b"\x01vorbis"))
            )
            or (
                mime == "audio/mpeg"
                and (
                    raw.startswith(b"ID3")
                    or (len(raw) >= 4 and raw[0] == 255 and raw[1] & 224 == 224 and raw[1] & 6)
                )
            )
            or (mime == "audio/wav" and raw.startswith(b"RIFF") and raw[8:12] == b"WAVE")
            or (
                mime == "audio/mp4"
                and raw[4:8] == b"ftyp"
                and any(codec in raw for codec in (b"mp4a", b"Opus"))
            )
        )
        if not valid or len(raw) < 12:
            raise HTTPException(422, "attachment_invalid_content")
        return raw, mime, "audio"
    if mime == "application/pdf":
        if not re.match(rb"%PDF-[12]\.[0-9]", raw):
            raise HTTPException(422, "attachment_invalid_content")
    else:
        if (
            raw.lstrip()
            .lower()
            .startswith(
                (
                    b"<html",
                    b"<!doctype html",
                    b"<svg",
                    b"<?xml",
                    b"#!",
                    b"%pdf-",
                    b"pk\x03\x04",
                    b"mz",
                    b"\x7felf",
                )
            )
        ):
            raise HTTPException(422, "attachment_invalid_content")
    return raw, mime, "document"


def pdf_text(db, raw):
    # A PostgreSQL lock bounds parsing to one child across API workers/processes.
    if not db.execute("SELECT pg_try_advisory_xact_lock(2026111307) AS available").fetchone()[
        "available"
    ]:
        raise HTTPException(429, "attachment_parser_busy")
    try:
        child = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("pdf_worker.py"))],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if child.returncode == 3:
            raise HTTPException(422, "attachment_pdf_no_text")
        if child.returncode == 4:
            raise HTTPException(422, "attachment_text_too_large")
        if child.returncode or len(child.stdout) > 100000:
            raise HTTPException(422, "attachment_invalid_pdf")
        text = json.loads(child.stdout)["text"]
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError):
        raise HTTPException(422, "attachment_invalid_pdf") from None
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\x00" in text:
        raise HTTPException(422, "attachment_invalid_pdf")
    return text


def create(data, admin):
    raw, mime, kind = decode(data)
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(20261113,hashtext(%s))", (str(admin["id"]),))
        quota = db.execute(
            "SELECT count(*) AS files,COALESCE(sum(size),0) AS bytes "
            "FROM crm.sara_attachments WHERE owner_id=%s",
            (admin["id"],),
        ).fetchone()
        if quota["files"] >= 100 or quota["bytes"] + len(raw) > 25 * 1024 * 1024:
            raise HTTPException(409, "attachment_quota_exceeded")
        if kind == "audio":
            control.require_connections(db, "hermes")
            health = bridge.health()
            if not all(
                health.get(key) is True
                for key in ("available", "history_available", "transcription_available")
            ):
                raise HTTPException(503, "sara_voice_unavailable")
            try:
                response = bridge.request(
                    "/transcribe",
                    {"audio_base64": base64.b64encode(raw).decode(), "mime_type": mime},
                    timeout=30,
                )
            except HTTPException:
                raise HTTPException(503, "sara_voice_unavailable") from None
            text = response.get("text")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > MAX_TEXT
                or "\x00" in text
            ):
                raise HTTPException(502, "sara_transcription_failed")
            text = text.strip()
        elif mime == "application/pdf":
            text = pdf_text(db, raw)
        else:
            try:
                text = raw.decode("utf-8-sig").strip()
            except UnicodeError:
                raise HTTPException(422, "attachment_invalid_content") from None
            if not text or "\x00" in text:
                raise HTTPException(422, "attachment_invalid_content")
            if len(text) > MAX_TEXT:
                raise HTTPException(422, "attachment_text_too_large")
        row = db.execute(
            """INSERT INTO crm.sara_attachments
            (owner_id,filename,mime_type,size,kind,data,text) VALUES (%s,%s,%s,%s,%s,%s,%s)
            RETURNING id,filename,mime_type,size,kind,text,created_at""",
            (admin["id"], data.filename, mime, len(raw), kind, raw, text),
        ).fetchone()
    return metadata(row)
