"""Strict bounded audio payloads and fixed multipart transcription protocol."""
import base64
from contextlib import contextmanager
import signal
import threading
import time
import binascii
import secrets

from operator_protocol import bounded_json, text

AUDIO_MODEL = 'gpt-4o-mini-transcribe'
MAX_AUDIO = 512 * 1024
MAX_AUDIO_BODY = 768 * 1024
MAX_TRANSCRIPT = 16000
MAX_AUDIO_REPLY = 65536
MIME_EXTENSIONS = {'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mpeg': 'mp3',
                   'audio/wav': 'wav', 'audio/mp4': 'mp4'}
ALIASES = {'audio/mp3': 'audio/mpeg', 'audio/x-wav': 'audio/wav'}


def media_type(value):
    if not isinstance(value, str) or len(value) > 128 or '\r' in value or '\n' in value:
        raise ValueError('Audio type denied')
    parts = value.lower().split(';')
    mime = ALIASES.get(parts[0].strip(), parts[0].strip())
    if mime not in MIME_EXTENSIONS:
        raise ValueError('Audio type denied')
    if len(parts) > 1 and (len(parts) != 2 or mime not in {'audio/webm', 'audio/ogg'}
                          or parts[1].strip() not in {'codecs=opus', 'codecs="opus"'}):
        raise ValueError('Audio codec denied')
    return mime


def signature(audio, mime):
    """Container signatures, not a decoder or a claim that speech was recognized."""
    if len(audio) < 16:
        return False
    if mime == 'audio/wav':
        return audio.startswith(b'RIFF') and audio[8:12] == b'WAVE'
    if mime == 'audio/webm':
        return audio.startswith(b'\x1aE\xdf\xa3') and b'webm' in audio[:4096]
    if mime == 'audio/ogg':
        return audio.startswith(b'OggS\x00') and (b'OpusHead' in audio[:4096] or b'\x01vorbis' in audio[:4096])
    if mime == 'audio/mp4':
        box_size = int.from_bytes(audio[:4], 'big')
        return audio[4:8] == b'ftyp' and 16 <= box_size <= len(audio)
    if mime == 'audio/mpeg':
        start = 0
        if audio.startswith(b'ID3'):
            if audio[3] not in {2, 3, 4} or any(value >= 128 for value in audio[6:10]):
                return False
            size = 0
            for value in audio[6:10]:
                size = (size << 7) | value
            start = 10 + size + (10 if audio[3] == 4 and audio[5] & 0x10 else 0)
        frame = audio[start:start + 4]
        return (len(frame) == 4 and frame[0] == 0xff and frame[1] & 0xe0 == 0xe0
                and frame[1] & 0x18 != 0x08 and frame[1] & 0x06 != 0
                and frame[2] >> 4 not in {0, 15} and frame[2] & 0x0c != 0x0c)
    return False


def validate_audio(payload):
    if not isinstance(payload, dict) or set(payload) != {'audio_base64', 'mime_type'}:
        raise ValueError('Audio request denied')
    mime = media_type(payload['mime_type'])
    encoded = payload['audio_base64']
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 4 * ((MAX_AUDIO + 2) // 3):
        raise ValueError('Audio size denied')
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('Audio encoding denied') from error
    if (not 1 <= len(audio) <= MAX_AUDIO or base64.b64encode(audio).decode() != encoded
            or not signature(audio, mime)):
        raise ValueError('Audio signature or size denied')
    return audio, mime


def read_json(handler, limit, require_json=True, body_seconds=3):
    """Read exactly the declared, bounded frame; no chunked/compressed ambiguity."""
    values = handler.headers.get_all('Content-Length', [])
    if (len(values) != 1 or not values[0].isascii() or not values[0].isdecimal()
            or handler.headers.get_all('Transfer-Encoding') or handler.headers.get_all('Content-Encoding')):
        raise ValueError('Invalid body framing')
    size = int(values[0])
    if not 0 < size <= limit:
        raise ValueError('Body exceeds endpoint policy')
    if require_json and handler.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
        raise ValueError('JSON required')
    deadline = time.monotonic() + body_seconds
    raw = bytearray()
    while len(raw) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Body deadline')
        handler.connection.settimeout(remaining)
        chunk = handler.rfile.read1(min(16384, size - len(raw)))
        if not chunk:
            raise ValueError('Incomplete body')
        raw.extend(chunk)
    return bounded_json(raw, limit)


def multipart(audio, mime):
    if mime not in MIME_EXTENSIONS or not 1 <= len(audio) <= MAX_AUDIO or not signature(audio, mime):
        raise ValueError('Audio denied')
    boundary = 'jardines-' + secrets.token_hex(16)
    if boundary.encode() in audio:
        raise ValueError('Multipart collision')
    chunks = []
    for name, value in (('model', AUDIO_MODEL), ('language', 'es'), ('response_format', 'json')):
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice.{MIME_EXTENSIONS[mime]}"\r\nContent-Type: {mime}\r\n\r\n'.encode(),
                   audio, f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


def transcript(result):
    if not isinstance(result, dict) or set(result) - {'text', 'usage'}:
        raise ValueError('Invalid transcription reply')
    return {'text': text(result.get('text'), MAX_TRANSCRIPT, False)}


def read_reply(response):
    length = response.getheader('Content-Length')
    if length is not None and (not isinstance(length, str) or not length.isascii()
                               or not length.isdecimal() or not 0 < int(length) <= MAX_AUDIO_REPLY):
        raise ValueError('Invalid response framing')
    raw = response.read(MAX_AUDIO_REPLY + 1)
    if len(raw) > MAX_AUDIO_REPLY or (length is not None and len(raw) != int(length)):
        raise ValueError('Invalid response size')
    return transcript(bounded_json(raw, MAX_AUDIO_REPLY))


class AudioDeadline(BaseException):
    """Outer wall deadline cannot be swallowed by ordinary HTTP error handlers."""


@contextmanager
def request_deadline(seconds):
    """Production HTTPServer runs on the main thread: bound even DNS/slow drips.

    Loopback HTTP fixtures use worker threads and exercise protocol, not this
    signal path. The separate main-thread deadline regression covers wall time.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    def expired(_signum, _frame):
        raise AudioDeadline('Transcription deadline')
    previous_handler = signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)
