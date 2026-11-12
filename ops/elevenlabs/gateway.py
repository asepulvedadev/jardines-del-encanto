"""Private finite ElevenLabs adapter. No generic proxy or vendor credential readback."""
import base64
import binascii
import fcntl
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import stat
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from uuid import UUID

HOST = 'api.elevenlabs.io'
DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='voice-dns')
DNS_SLOTS = threading.BoundedSemaphore(4)
MAX_AUDIO = 2 * 1024 * 1024
MAX_INPUT_AUDIO = 512 * 1024
MAX_BODY = 720 * 1024
MAX_JSON = 1024 * 1024
MAX_RESERVATIONS = 10000
ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
DEFAULT_KEYS = {'voice_id', 'model_id', 'agent_id', 'phone_number_id'}
CATALOGS = {
    'voices': ('/v2/voices?page_size=50', 'voices', 'voice_id'),
    'models': ('/v1/models', None, 'model_id'),
    'agents': ('/v1/convai/agents?page_size=50', 'agents', 'agent_id'),
    'phone_numbers': ('/v1/convai/phone-numbers?provider=twilio', None, 'phone_number_id'),
}


class GatewayError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def require(condition, code='invalid_input', status=422):
    if not condition:
        raise GatewayError(status, code)


def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= set(value)
            and not set(value) - set(required) - set(optional))
    return value


def identifier(value):
    require(isinstance(value, str) and bool(ID.fullmatch(value)))
    return value


def revision(value):
    require(type(value) is int and 0 <= value <= 2**53 - 1)
    return value


def request_id(value):
    require(isinstance(value, str))
    try:
        require(str(UUID(value)) == value)
    except ValueError:
        raise GatewayError(422, 'invalid_input') from None
    return value


def json_load(raw):
    def unique(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError('duplicate field')
            output[key] = value
        return output
    def reject(_value):
        raise ValueError('nonfinite value')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def key_text(value):
    require(isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{20,256}', value)))
    return value


def vendor_route(method, path):
    return (
        method == 'GET' and (path in {entry[0] for entry in CATALOGS.values()} | {'/v1/user'}
            or re.fullmatch(r'/v1/convai/conversation/token\?agent_id=[A-Za-z0-9_-]{1,128}', path))
        or method == 'POST' and (path in {'/v1/speech-to-text', '/v1/convai/twilio/outbound-call'}
            or re.fullmatch(r'/v1/text-to-speech/[A-Za-z0-9_-]{1,128}\?output_format=mp3_22050_32', path))
    )


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError('Provider deadline')
    return seconds


def vendor_socket(deadline):
    """Bound libc DNS workers and pin vetted public addresses under vendor TLS SNI."""
    require(DNS_SLOTS.acquire(blocking=False), 'provider_unavailable', 502)
    try:
        future = DNS_POOL.submit(socket.getaddrinfo, HOST, 443, socket.AF_UNSPEC,
                                 socket.SOCK_STREAM, socket.IPPROTO_TCP)
    except BaseException:
        DNS_SLOTS.release()
        raise
    future.add_done_callback(lambda _future: DNS_SLOTS.release())
    answers = future.result(timeout=min(2, remaining(deadline)))
    require(isinstance(answers, list) and 1 <= len(answers) <= 16, 'provider_unavailable', 502)
    for family, kind, proto, _canonical, address in answers:
        require(family in {socket.AF_INET, socket.AF_INET6} and kind == socket.SOCK_STREAM
                and proto == socket.IPPROTO_TCP and address[1] == 443 and '%' not in address[0],
                'provider_unavailable', 502)
        ip = ipaddress.ip_address(address[0])
        require(ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
                and not (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)
                and (family != socket.AF_INET6 or len(address) == 4 and address[3] == 0),
                'provider_unavailable', 502)
    family, kind, proto, _canonical, address = answers[0]
    sock = socket.socket(family, kind, proto)
    try:
        sock.settimeout(remaining(deadline))
        sock.connect(address)
        sock.settimeout(remaining(deadline))
        secured = ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)
        return DeadlineSocket(secured, deadline)
    except BaseException:
        sock.close()
        raise


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def sendall(self, data):
        self.sock.settimeout(remaining(self.deadline))
        self.sock.sendall(data)

    def makefile(self, mode):
        require(mode == 'rb', 'provider_unavailable', 502)
        # Retain a proper socket-file reference for HTTP/1.0 close-delimited replies.
        raw = self.sock.makefile('rb', buffering=0)
        return io.BufferedReader(DeadlineReader(self.sock, self.deadline, raw))


def vendor_request(method, path, key, body=None, content_type='application/json', binary=False):
    """One HTTPS dispatch to a literal vendor host; no proxies, redirects or retries."""
    require(vendor_route(method, path), 'provider_route_denied', 422)
    key_text(key)
    maximum = MAX_AUDIO if binary else MAX_JSON
    seconds = 25 if method == 'POST' else 5
    deadline = time.monotonic() + seconds
    connection = HTTPSConnection(HOST, port=443, timeout=seconds)
    try:
        def connect_fixed():
            connection.sock = vendor_socket(deadline)
        connection.connect = connect_fixed
        connection.request(method, path, body=body, headers={
            'xi-api-key': key, 'Content-Type': content_type,
            'Accept': 'audio/mpeg' if binary else 'application/json',
            'Accept-Encoding': 'identity',
        })
        response = connection.getresponse()
        if response.status != 200:
            raise GatewayError(502, 'provider_unavailable')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > maximum):
            raise GatewayError(502, 'provider_response_invalid')
        mime = response.getheader('Content-Type', '').split(';')[0].strip().lower()
        if mime not in ({'audio/mpeg', 'audio/mp3', 'application/octet-stream'} if binary else {'application/json'}):
            raise GatewayError(502, 'provider_response_invalid')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise GatewayError(502, 'provider_response_invalid')
        chunks, total = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GatewayError(502, 'provider_unavailable')
            # HTTP/1.1 usually retains the socket; close-delimited replies retain it on fp.
            sock = connection.sock or getattr(getattr(response.fp, 'raw', None), '_sock', None)
            if sock:
                sock.settimeout(remaining)
            chunk = response.read1(min(16384, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise GatewayError(502, 'provider_response_invalid')
        raw = b''.join(chunks)
        if not raw:
            raise GatewayError(502, 'provider_response_invalid')
        return raw if binary else json_load(raw)
    except GatewayError:
        raise
    except Exception:  # noqa: BLE001 - sanitize every transport failure at the credential boundary
        raise GatewayError(502, 'provider_unavailable') from None
    finally:
        connection.close()


class PrivateStore:
    """A bounded fsync/rename journal keeps credentials and dispatch tombstones private."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.thread_lock = threading.Lock()

    @contextmanager
    def locked(self):
        with self.thread_lock:
            try:
                self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
                info = self.directory.lstat()
                require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                        and info.st_uid == os.geteuid(), 'configuration_unavailable', 503)
                fd = os.open(self.directory / 'settings.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
                with os.fdopen(fd, 'w') as lock:
                    info = os.fstat(lock.fileno())
                    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                            and info.st_uid == os.geteuid(), 'configuration_unavailable', 503)
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    yield self.read()
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                raise GatewayError(503, 'configuration_unavailable') from None

    def read(self):
        try:
            fd = os.open(self.directory / 'state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {'revision': 0, 'api_key': None, 'verified': False, 'defaults': {}, 'reserved': []}
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid == os.geteuid(), 'configuration_unavailable', 503)
            raw = file.read(MAX_JSON + 1)
        require(len(raw) <= MAX_JSON, 'configuration_unavailable', 503)
        data = fields(json_load(raw), {'revision', 'api_key', 'verified', 'defaults', 'reserved'})
        revision(data['revision'])
        if data['api_key'] is not None:
            key_text(data['api_key'])
        require(type(data['verified']) is bool and (data['api_key'] is not None) == data['verified'])
        fields(data['defaults'], set(), DEFAULT_KEYS)
        for value in data['defaults'].values():
            require(value == '' or isinstance(value, str) and bool(ID.fullmatch(value)))
        require(isinstance(data['reserved'], list) and len(data['reserved']) <= MAX_RESERVATIONS)
        for value in data['reserved']:
            request_id(value)
        require(len(set(data['reserved'])) == len(data['reserved']))
        return data

    def write(self, data):
        path = None
        try:
            fd, path = tempfile.mkstemp(prefix='.state-', dir=self.directory)
            with os.fdopen(fd, 'w') as file:
                json.dump(data, file, separators=(',', ':'), allow_nan=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(path, self.directory / 'state.json')
            path = None
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if path:
                os.unlink(path)


def public_state(data):
    return {'configured': bool(data['api_key']), 'verified': data['verified'],
            'revision': data['revision'], 'key_suffix': (data['api_key'] or '')[-4:],
            'defaults': {key: data['defaults'].get(key, '') for key in sorted(DEFAULT_KEYS)}}


class Gateway:
    def __init__(self, directory, transport=vendor_request):
        self.store, self.transport = PrivateStore(directory), transport
        self.sessions = {}
        self.session_timers = {}
        self.session_lock = threading.Lock()

    def state(self):
        with self.store.locked() as data:
            return public_state(data)

    @staticmethod
    def current(data, expected, configured=True):
        require(data['revision'] == revision(expected), 'configuration_changed', 409)
        if configured:
            require(data['api_key'] and data['verified'], 'provider_not_configured', 503)

    def configure(self, body):
        fields(body, {'revision'}, {'api_key', 'defaults'})
        defaults = body.get('defaults', {})
        fields(defaults, set(), DEFAULT_KEYS)
        for value in defaults.values():
            require(value == '' or isinstance(value, str) and bool(ID.fullmatch(value)))
        with self.store.locked() as data:
            self.current(data, body['revision'], configured=False)
            key = key_text(body['api_key']) if 'api_key' in body else data['api_key']
            require(key, 'provider_not_configured', 503)
        if 'api_key' in body:
            response = self.transport('GET', '/v1/user', key)
            require(isinstance(response, dict) and isinstance(response.get('user_id'), str)
                    and 1 <= len(response['user_id']) <= 128, 'provider_verification_failed', 502)
        with self.store.locked() as data:
            self.current(data, body['revision'], configured=False)
            data.update(api_key=key, verified=True, defaults={**data['defaults'], **defaults},
                        revision=data['revision'] + 1)
            self.store.write(data)
            with self.session_lock:
                self.clear_sessions()
            return public_state(data)

    def disconnect(self, body):
        fields(body, {'revision'})
        with self.store.locked() as data:
            self.current(data, body['revision'], configured=False)
            data.update(api_key=None, verified=False, defaults={}, revision=data['revision'] + 1)
            self.store.write(data)
            with self.session_lock:
                self.clear_sessions()
            return public_state(data)

    def catalog(self, body):
        fields(body, {'revision'})
        with self.store.locked() as data:
            self.current(data, body['revision'])
        key, expected = data['api_key'], data['revision']
        result = {'revision': data['revision'], 'limited': False, 'errors': []}
        for name, (path, collection, id_key) in CATALOGS.items():
            result[name] = []
            try:
                response = self.transport('GET', path, key)
                entries = response.get(collection) if collection and isinstance(response, dict) else response
                require(isinstance(entries, list), 'provider_response_invalid', 502)
                if len(entries) > 50 or (isinstance(response, dict) and response.get('has_more') is True):
                    result['limited'] = True
                seen = set()
                for row in entries[:50]:
                    require(isinstance(row, dict), 'provider_response_invalid', 502)
                    if name == 'models' and row.get('can_do_text_to_speech') is not True:
                        continue
                    if name == 'phone_numbers' and row.get('provider') != 'twilio':
                        continue
                    value = identifier(row.get(id_key))
                    label = row.get('name') if name != 'phone_numbers' else row.get('label')
                    require(isinstance(label, str) and 1 <= len(label) <= 200 and bool(label.strip()) and '\x00' not in label,
                            'provider_response_invalid', 502)
                    if value not in seen:
                        # Match the shared API's bounded display label without dropping a valid ID.
                        result[name].append({'id': value, 'name': label.strip()[:120]})
                        seen.add(value)
            except Exception:  # noqa: BLE001 - a failed catalog is explicitly partial, never raw
                result[name] = []
                result['errors'].append(name)
        with self.store.locked() as latest:
            self.current(latest, expected)
        return result

    def execute(self, body):
        fields(body, {'id', 'revision', 'operation', 'arguments'})
        identifier_ = request_id(body['id'])
        operation, args = body['operation'], body['arguments']
        # Validate everything before reserving or making a provider call.
        method, path, raw, content_type, binary = operation_request(operation, args)
        with self.store.locked() as data:
            self.current(data, body['revision'])
            require(identifier_ not in data['reserved'], 'dispatch_already_reserved', 409)
            require(len(data['reserved']) < MAX_RESERVATIONS, 'dispatch_capacity_exceeded', 409)
            with self.session_lock:
                self.expire_sessions()
                require(operation != 'agent_session' or len(self.sessions) < 16, 'session_capacity_exceeded', 409)
            data['reserved'].append(identifier_)
            self.store.write(data)
            key, config_revision = data['api_key'], data['revision']
        try:
            result = self.transport(method, path, key, raw, content_type, binary)
            if operation == 'tts':
                require(isinstance(result, bytes) and 0 < len(result) <= MAX_AUDIO
                        and (result.startswith(b'ID3') or result[:1] == b'\xff'), 'provider_response_invalid', 502)
                return {'status': 'completed', 'mime_type': 'audio/mpeg',
                        'data_base64': base64.b64encode(result).decode()}
            require(isinstance(result, dict), 'provider_response_invalid', 502)
            if operation == 'stt':
                value = result.get('text')
                require(isinstance(value, str) and value.strip() and len(value) <= 16000 and '\x00' not in value,
                        'provider_response_invalid', 502)
                return {'status': 'completed', 'text': value.strip()}
            if operation == 'agent_session':
                token = result.get('token')
                require(isinstance(token, str) and 1 <= len(token) <= 16000 and token.isascii()
                        and not any(ord(char) < 33 or ord(char) > 126 for char in token), 'provider_response_invalid', 502)
                material = {'token': token}
                if result.get('conversation_id') is not None:
                    material['conversation_id'] = identifier(result['conversation_id'])
                # A rotation during upstream I/O makes this token unavailable, never reusable.
                with self.store.locked() as latest:
                    self.current(latest, config_revision)
                    with self.session_lock:
                        self.expire_sessions()
                        require(len(self.sessions) < 16, 'session_capacity_exceeded', 409)
                        self.sessions[identifier_] = (config_revision, time.monotonic() + 60, material)
                        timer = threading.Timer(60, self.expire_one, args=(identifier_,))
                        timer.daemon = True
                        self.session_timers[identifier_] = timer
                        timer.start()
                return {'status': 'ready'}
            require(result.get('success') is True, 'provider_response_invalid', 502)
            output = {'status': 'completed'}
            for source, target in [('conversation_id', 'conversation_id'), ('callSid', 'call_id')]:
                if result.get(source) is not None:
                    output[target] = identifier(result[source])
            return output
        except Exception:  # noqa: BLE001 - reserved dispatches must never reopen or leak provider errors
            raise GatewayError(502, 'external_outcome_unconfirmed') from None

    def expire_one(self, identifier_):
        with self.session_lock:
            self.sessions.pop(identifier_, None)
            self.session_timers.pop(identifier_, None)

    def clear_sessions(self):
        for timer in self.session_timers.values():
            timer.cancel()
        self.session_timers.clear()
        self.sessions.clear()

    def close(self):
        with self.session_lock:
            self.clear_sessions()

    def expire_sessions(self):
        now = time.monotonic()
        expired = [key for key, value in self.sessions.items() if value[1] <= now]
        for key in expired:
            self.sessions.pop(key, None)
            timer = self.session_timers.pop(key, None)
            if timer:
                timer.cancel()

    def claim(self, identifier_, body):
        request_id(identifier_)
        fields(body, {'revision'})
        with self.store.locked() as data:
            self.current(data, body['revision'])
            with self.session_lock:
                self.expire_sessions()
                entry = self.sessions.pop(identifier_, None)
                timer = self.session_timers.pop(identifier_, None)
                if timer:
                    timer.cancel()
                require(entry and entry[0] == data['revision'], 'session_unavailable', 410)
                return entry[2]


def operation_request(operation, args):
    content_type = 'application/json'
    if operation == 'tts':
        fields(args, {'text', 'voice_id', 'model_id'})
        require(isinstance(args['text'], str) and args['text'].strip() and len(args['text']) <= 1500
                and '\x00' not in args['text'])
        path = '/v1/text-to-speech/' + identifier(args['voice_id']) + '?output_format=mp3_22050_32'
        body = {'text': args['text'], 'model_id': identifier(args['model_id'])}
        return 'POST', path, json.dumps(body).encode(), content_type, True
    if operation == 'stt':
        fields(args, {'data_base64', 'mime_type'})
        require(isinstance(args['data_base64'], str) and len(args['data_base64']) <= 4 * ((MAX_INPUT_AUDIO + 2) // 3))
        try:
            audio = base64.b64decode(args['data_base64'], validate=True)
        except (ValueError, binascii.Error):
            raise GatewayError(422, 'invalid_input') from None
        require(0 < len(audio) <= MAX_INPUT_AUDIO)
        mime = args['mime_type']
        require(isinstance(mime, str) and mime in {'audio/webm', 'audio/ogg', 'audio/mpeg', 'audio/wav', 'audio/mp4'})
        signatures = {'audio/webm': audio.startswith(b'\x1aE\xdf\xa3'), 'audio/ogg': audio.startswith(b'OggS'),
                      'audio/mpeg': audio.startswith(b'ID3') or audio[:1] == b'\xff',
                      'audio/wav': audio.startswith(b'RIFF') and audio[8:12] == b'WAVE',
                      'audio/mp4': audio[4:8] == b'ftyp'}
        require(signatures[mime])
        boundary = 'jardines-' + secrets.token_hex(24)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\nscribe_v2\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="timestamps_granularity"\r\n\r\nnone\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio"\r\nContent-Type: {mime}\r\n\r\n').encode()
        body += audio + f'\r\n--{boundary}--\r\n'.encode()
        return 'POST', '/v1/speech-to-text', body, 'multipart/form-data; boundary=' + boundary, False
    if operation == 'agent_session':
        fields(args, {'agent_id'})
        return 'GET', '/v1/convai/conversation/token?agent_id=' + identifier(args['agent_id']), None, content_type, False
    if operation == 'outbound_call':
        fields(args, {'agent_id', 'phone_number_id', 'to_number'})
        require(isinstance(args['to_number'], str) and bool(re.fullmatch(r'\+[1-9][0-9]{7,14}', args['to_number'])))
        body = {'agent_id': identifier(args['agent_id']), 'agent_phone_number_id': identifier(args['phone_number_id']),
                'to_number': args['to_number'], 'call_recording_enabled': False}
        return 'POST', '/v1/convai/twilio/outbound-call', json.dumps(body).encode(), content_type, False
    raise GatewayError(422, 'unsupported_operation')


def service_token(path):
    if not path or not Path(path).is_absolute():
        raise GatewayError(503, 'gateway_not_configured')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r') as file:
            info = os.fstat(file.fileno())
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) in {0o400, 0o600}, 'gateway_not_configured', 503)
            token = file.read(129).strip()
        require(bool(re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token)), 'gateway_not_configured', 503)
        return token
    except (OSError, UnicodeError):
        raise GatewayError(503, 'gateway_not_configured') from None


class DeadlineReader(io.RawIOBase):
    """Bound ingress wall time even if a peer trickles headers/body indefinitely."""
    def __init__(self, sock, deadline=None, raw=None):
        self.sock = sock
        self.deadline = time.monotonic() + 8 if deadline is None else deadline
        self.raw = raw

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Ingress deadline')
        self.sock.settimeout(min(8, remaining))
        return self.raw.readinto(buffer) if self.raw is not None else self.sock.recv_into(buffer)

    def close(self):
        if self.raw is not None:
            self.raw.close()
        super().close()


class GatewayServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, address):
        # Do not let transport exception tracebacks reach shared container logs.
        pass


class Handler(BaseHTTPRequestHandler):
    gateway = None
    token_file = None
    server_version = 'PrivateVoiceGateway'

    def setup(self):
        super().setup()
        self.connection.settimeout(8)
        self.rfile.close()
        self.rfile = io.BufferedReader(DeadlineReader(self.connection))

    def log_message(self, *_args):
        pass

    def reply(self, status, body):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        expected = 'Bearer ' + service_token(self.token_file)
        actual = self.headers.get_all('Authorization', [])
        require(len(actual) == 1 and isinstance(actual[0], str) and len(actual[0]) <= 300
                and hmac.compare_digest(actual[0].encode(), expected.encode()), 'service_authentication_required', 401)

    def do_GET(self):
        try:
            if self.path == '/health/live':
                return self.reply(200, {'live': True})
            self.authorized()
            require(self.path == '/state', 'not_found', 404)
            self.reply(200, self.gateway.state())
        except GatewayError as error:
            self.reply(error.status, {'detail': error.code})
        except Exception:  # noqa: BLE001 - private HTTP errors never expose implementation or secrets
            self.reply(503, {'detail': 'gateway_unavailable'})

    def do_POST(self):
        try:
            self.authorized()
            require(not self.headers.get_all('Transfer-Encoding'), 'invalid_input', 400)
            lengths = self.headers.get_all('Content-Length', [])
            require(len(lengths) == 1 and lengths[0].isdigit(), 'invalid_input', 400)
            length = int(lengths[0])
            require(0 < length <= MAX_BODY, 'body_too_large', 413)
            require(self.headers.get('Content-Type', '').split(';')[0].lower() == 'application/json', 'invalid_input', 415)
            raw = self.rfile.read(length)
            require(len(raw) == length, 'invalid_input', 400)
            body = json_load(raw)
            routes = {'/configure': self.gateway.configure, '/disconnect': self.gateway.disconnect,
                      '/catalog': self.gateway.catalog, '/execute': self.gateway.execute}
            if self.path in routes:
                return self.reply(200, routes[self.path](body))
            match = re.fullmatch(r'/sessions/([0-9a-f-]{36})/claim', self.path)
            require(match, 'not_found', 404)
            self.reply(200, self.gateway.claim(match[1], body))
        except GatewayError as error:
            self.reply(error.status, {'detail': error.code})
        except (ValueError, TypeError, RecursionError):
            self.reply(422, {'detail': 'invalid_input'})
        except Exception:  # noqa: BLE001 - private HTTP errors never expose implementation or secrets
            self.reply(503, {'detail': 'gateway_unavailable'})


def main():
    Handler.token_file = os.getenv('ELEVENLABS_GATEWAY_TOKEN_FILE')
    Handler.gateway = Gateway(os.getenv('ELEVENLABS_STATE_DIR', '/var/lib/jardines-elevenlabs'))
    GatewayServer(('0.0.0.0', 8092), Handler).serve_forever()


if __name__ == '__main__':
    main()
