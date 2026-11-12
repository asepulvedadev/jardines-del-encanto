"""Isolated reviewed Retell MCP adapter. Never a generic HTTP proxy."""
import copy
import fcntl
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
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
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

HOST = 'mcp.retellai.com'
DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='retell-dns')
DNS_SLOTS = threading.BoundedSemaphore(4)
MAX_BODY = 128 * 1024
MAX_JSON = 4 * 1024 * 1024
MAX_RESERVATIONS = 10000
SESSION_SECONDS = 300
DEFAULT_KEYS = {'agent_id', 'chat_agent_id', 'from_number'}
ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
HERE = Path(__file__).resolve().parent
REGISTRY = json.loads((HERE / 'registry.json').read_text())
SCHEMAS = json.loads((HERE / 'schemas.json').read_text())
REGISTRY_REVISION = hashlib.sha256((HERE / 'registry.json').read_bytes() + (HERE / 'schemas.json').read_bytes()).hexdigest()


class GatewayError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)

def report_gateway_error(error):
    # Only controlled reason codes, never request bodies, keys or upstream messages.
    allowed = {'provider_unavailable', 'provider_response_invalid', 'provider_operation_failed',
               'provider_verification_failed', 'provider_protocol_changed', 'gateway_unavailable',
               'configuration_changed', 'service_authentication_required', 'schema_changed'}
    code = error.code if error.code in allowed else 'gateway_error'
    print(json.dumps({'event': 'retell_gateway_error', 'code': code, 'status': error.status}), flush=True)


def report_gateway_fault(error):
    kind = type(error).__name__
    # Exception class names are code metadata; never format the exception message.
    safe = kind if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', kind) else 'unexpected'
    print(json.dumps({'event': 'retell_gateway_fault', 'type': safe}), flush=True)


def require(condition, code='invalid_input', status=422):
    if not condition:
        raise GatewayError(status, code)

def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= set(value)
            and not set(value) - set(required) - set(optional))
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


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def bounded_tree(value, depth=0, budget=None):
    """Reject oversized or non-JSON input before recursive validation or persistence."""
    if budget is None:
        budget = [0]
    budget[0] += 1
    require(depth <= 24 and budget[0] <= 8000, 'arguments_too_complex')
    if isinstance(value, dict):
        require(len(value) <= 250 and all(isinstance(k, str) and len(k) <= 200 for k in value), 'arguments_too_complex')
        for child in value.values():
            bounded_tree(child, depth + 1, budget)
    elif isinstance(value, list):
        require(len(value) <= 500, 'arguments_too_complex')
        for child in value:
            bounded_tree(child, depth + 1, budget)
    elif isinstance(value, str):
        require(len(value) <= 32000 and '\x00' not in value, 'arguments_invalid')
    else:
        require(value is None or type(value) in {int, float, bool}, 'arguments_invalid')
    return value


def checked_response(status, mime, encoding, length, maximum=MAX_JSON):
    require(status in {200, 202}, 'provider_unavailable', 502)
    require(mime.split(';')[0].strip().lower() in {'application/json', 'text/event-stream'}, 'provider_response_invalid', 502)
    require(encoding.lower() == 'identity', 'provider_response_invalid', 502)
    require(length is None or length.isdigit() and int(length) <= maximum, 'provider_response_invalid', 502)


def parse_rpc(raw, mime, expected):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_JSON, 'provider_response_invalid', 502)
    if mime.split(';')[0].strip().lower() == 'text/event-stream':
        text = raw.decode('utf-8')
        events = []
        # SSE data fields join per event. Only one matching RPC result is accepted;
        # bounded notifications may appear but cannot replace a result.
        for event in text.replace('\r\n', '\n').split('\n\n'):
            if not event.strip():
                continue
            rows = [line[5:].lstrip(' ') for line in event.split('\n') if line.startswith('data:')]
            if rows:
                events.append(json_load('\n'.join(rows)))
        require(len(events) <= 64, 'provider_response_invalid', 502)
        matches = [event for event in events if isinstance(event, dict) and event.get('id') == expected]
        require(len(matches) == 1, 'provider_response_invalid', 502)
        value = matches[0]
    else:
        require(mime.split(';')[0].strip().lower() == 'application/json', 'provider_response_invalid', 502)
        value = json_load(raw)
    require(isinstance(value, dict) and value.get('jsonrpc') == '2.0'
            and type(value.get('id')) is type(expected) and value.get('id') == expected
            and 'result' in value and 'error' not in value, 'provider_response_invalid', 502)
    return value['result']


def https_rpc(key, payload, session=None, protocol=None, deadline=None):
    """Exactly one fixed-host TLS POST. No environment proxy, redirects or retry."""
    key_text(key)
    deadline = time.monotonic() + 25 if deadline is None else deadline
    connection = HTTPSConnection(HOST, port=443, timeout=remaining(deadline))
    try:
        def connect_fixed():
            connection.sock = vendor_socket(deadline)
        connection.connect = connect_fixed
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                   'Accept': 'application/json, text/event-stream', 'Accept-Encoding': 'identity'}
        if session:
            require(isinstance(session, str) and bool(re.fullmatch(r'[A-Za-z0-9._~-]{1,256}', session)), 'provider_response_invalid', 502)
            headers['Mcp-Session-Id'] = session
        if protocol:
            require(protocol in {'2025-03-26', '2025-06-18'}, 'provider_response_invalid', 502)
            headers['MCP-Protocol-Version'] = protocol
        connection.request('POST', '/', body=canonical(payload).encode(), headers=headers)
        response = connection.getresponse()
        # Initialized notifications have no response body in a compliant server.
        if 'id' not in payload:
            require(response.status in {200, 202, 204}, 'provider_unavailable', 502)
            return None, session
        checked_response(response.status, response.getheader('Content-Type', ''),
                         response.getheader('Content-Encoding', 'identity'), response.getheader('Content-Length'))
        chunks, total = [], 0
        while True:
            remaining(deadline)
            chunk = response.read1(min(16384, MAX_JSON + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            require(total <= MAX_JSON, 'provider_response_invalid', 502)
            chunks.append(chunk)
        next_session = response.getheader('Mcp-Session-Id') or session
        if next_session:
            require(bool(re.fullmatch(r'[A-Za-z0-9._~-]{1,256}', next_session)), 'provider_response_invalid', 502)
        return parse_rpc(b''.join(chunks), response.getheader('Content-Type', ''), payload['id']), next_session
    except GatewayError:
        raise
    except Exception:  # noqa: BLE001 - do not expose upstream credentials or raw failures
        raise GatewayError(502, 'provider_unavailable') from None
    finally:
        connection.close()


def tool_value(result):
    require(isinstance(result, dict) and result.get('isError') is not True, 'provider_operation_failed', 502)
    if 'structuredContent' in result:
        value = result['structuredContent']
    else:
        content = result.get('content')
        require(isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
                and content[0].get('type') == 'text' and isinstance(content[0].get('text'), str), 'provider_response_invalid', 502)
        raw = content[0]['text']
        # The authenticated hosted MCP wraps API results, unlike its discovery tools.
        # Accept only the observed status envelope; never extract arbitrary embedded JSON.
        if raw.startswith('API Response (Status: '):
            envelope = re.fullmatch(r'API Response \(Status: (2[0-9]{2})\):\r?\n([\s\S]+)', raw)
            require(envelope is not None, 'provider_response_invalid', 502)
            raw = envelope[2]
        try:
            value = json_load(raw)
        except (ValueError, TypeError):
            raise GatewayError(502, 'provider_response_invalid') from None

    require(value is None or isinstance(value, (dict, list, str, int, float, bool)), 'provider_response_invalid', 502)
    return value


def mcp_call(key, tool, arguments):
    require(tool in {'list_api_endpoints', 'get_api_endpoint_schema', 'invoke_api_endpoint'}, 'provider_tool_denied')
    deadline = time.monotonic() + 25
    initialized, session = https_rpc(key, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-03-26', 'capabilities': {},
        'clientInfo': {'name': 'jardines-retell-reviewed-gateway', 'version': '1.0'}}}, deadline=deadline)
    require(isinstance(initialized, dict) and initialized.get('protocolVersion') in {'2025-03-26', '2025-06-18'}, 'provider_protocol_changed', 502)
    protocol = initialized['protocolVersion']
    https_rpc(key, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, session, protocol, deadline)
    result, _session = https_rpc(key, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
        'params': {'name': tool, 'arguments': arguments}}, session, protocol, deadline)
    return tool_value(result)


def input_schema(endpoint, strict=True):
    require(isinstance(endpoint, str) and endpoint in REGISTRY, 'endpoint_unreviewed')
    value = copy.deepcopy(SCHEMAS[endpoint])
    if strict:
        def close(schema, composition_branch=False):
            if isinstance(schema, dict):
                # Close the composed object, not its sibling branches. Draft 2020-12
                # tracks properties evaluated by all successful composition branches.
                if not composition_branch and ('properties' in schema or any(k in schema for k in ('oneOf', 'anyOf', 'allOf'))):
                    schema.setdefault('unevaluatedProperties', False)
                for name, child in schema.items():
                    if name in {'oneOf', 'anyOf', 'allOf'} and isinstance(child, list):
                        for branch in child:
                            close(branch, composition_branch=True)
                    elif name in {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'} and isinstance(child, dict):
                        for field in child.values():
                            close(field)
                    elif name in {'items', 'additionalProperties', 'unevaluatedProperties', 'contains', 'not', 'if', 'then', 'else'}:
                        close(child)
            elif isinstance(schema, list):
                for child in schema:
                    close(child)
        close(value)
        value['additionalProperties'] = False
    return value


def schema_hash(endpoint):
    return hashlib.sha256((REGISTRY_REVISION + canonical(input_schema(endpoint))).encode()).hexdigest()


def semantic_schema(value, named_map=False):
    """Ignore documentation changes, never constraints or newly accepted fields."""
    if isinstance(value, dict):
        return {k: semantic_schema(v, k in {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'})
                for k, v in value.items() if named_map or k not in {'description', 'title', 'examples', 'example', '$schema'}}
    if isinstance(value, list):
        return [semantic_schema(x) for x in value]
    return value


SENSITIVE = re.compile(r'(?:api_?key|token|auth(?:orization|entication)?|auth_config|password|secret|credential|headers?|ice_?servers?|client_?secret|private_?key|bearer)', re.IGNORECASE)
SECRET_VALUE = re.compile(r'(?:\b(?:sk|key|rk|pk)_[A-Za-z0-9_-]{16,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)')


def validate_url(value):
    require(isinstance(value, str) and len(value) <= 2048, 'unsafe_url')
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        require(parsed.scheme in {'https', 'wss'} and host and parsed.username is None and parsed.password is None
                and parsed.port in {None, 443} and not parsed.fragment and '%' not in parsed.netloc
                and host.isascii() and '.' in host and not host.endswith(('.local', '.internal', '.localhost', '.test'))
                and not any(SECRET_VALUE.search(x) for x in [parsed.path, parsed.query]), 'unsafe_url')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            require(bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', host)), 'unsafe_url')
        else:
            require(address.is_global and not address.is_private and not address.is_reserved, 'unsafe_url')
        # Callback arguments are sent to Retell, never fetched by this gateway.
        # Block credential-bearing callback URLs even if the parameter is not named secret.
        require(all(not SENSITIVE.search(name) and name.casefold() != 'key' and '%' not in name
                    for name, _ in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100)), 'unsafe_url')
    except (ValueError, TypeError):
        raise GatewayError(422, 'unsafe_url') from None


def validate_sensitive(value, key=None, depth=0):
    require(depth <= 24, 'arguments_too_complex')
    if key is not None:
        require(not SENSITIVE.search(key), 'sensitive_arguments_denied')
    if isinstance(value, dict):
        for name, child in value.items():
            validate_sensitive(child, name, depth + 1)
    elif isinstance(value, list):
        for child in value:
            validate_sensitive(child, key, depth + 1)
    elif isinstance(value, str):
        require(not SECRET_VALUE.search(value), 'sensitive_arguments_denied')
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', value) or key and key.endswith(('_url', '_urls')):
            validate_url(value)


def safe_output(value, key=None, secrets=(), depth=0, budget=None):
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 10 or budget[0] > 3000:
        return '[truncated]'
    if key and SENSITIVE.search(key):
        return '[redacted]'
    if isinstance(value, dict):
        output = {}
        for name, child in list(value.items())[:80]:
            safe_name = str(name)
            for secret in secrets:
                if secret:
                    safe_name = safe_name.replace(secret, '[redacted]')
            safe_name = SECRET_VALUE.sub('[redacted]', safe_name)[:120]
            output[safe_name] = safe_output(child, str(name), secrets, depth + 1, budget)
        return output
    if isinstance(value, list):
        return [safe_output(v, key, secrets, depth + 1, budget) for v in value[:100]]
    if isinstance(value, str):
        value = value[:6000]
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[redacted]')
        value = SECRET_VALUE.sub('[redacted]', value)
        if re.match(r'^(?:https?|wss?)://', value):
            try:
                parts = urlsplit(value)
                # Signed recording/asset links must not survive in chat or audit.
                if parts.query or parts.username or parts.password:
                    return '[private link redacted]'
                return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
            except ValueError:
                return '[redacted]'
        return value
    if value is None or type(value) in {int, float, bool}:
        return value
    return '[unsupported]'


class PrivateStore:
    """Private fsynced state and tombstones; reservations survive key replacement."""
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
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.geteuid(), 'configuration_unavailable', 503)
            raw = file.read(MAX_JSON + 1)
        require(len(raw) <= MAX_JSON, 'configuration_unavailable', 503)
        data = fields(json_load(raw), {'revision', 'api_key', 'verified', 'defaults', 'reserved'})
        revision(data['revision'])
        if data['api_key'] is not None:
            key_text(data['api_key'])
        require(type(data['verified']) is bool and bool(data['api_key']) == data['verified'])
        self.defaults(data['defaults'])
        require(isinstance(data['reserved'], list) and len(data['reserved']) <= MAX_RESERVATIONS)
        for value in data['reserved']:
            request_id(value)
        require(len(set(data['reserved'])) == len(data['reserved']))
        return data

    @staticmethod
    def defaults(value):
        fields(value, set(), DEFAULT_KEYS)
        for key, item in value.items():
            require(isinstance(item, str) and (not item or bool(re.fullmatch(r'\+[1-9][0-9]{7,14}' if key == 'from_number' else ID.pattern, item))))

    def write(self, data):
        path = None
        try:
            fd, path = tempfile.mkstemp(prefix='.state-', dir=self.directory)
            with os.fdopen(fd, 'w') as file:
                file.write(canonical(data))
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
    return {'configured': bool(data['api_key']), 'verified': data['verified'], 'revision': data['revision'],
            'key_suffix': data['api_key'][-4:] if data['api_key'] else None,
            'defaults': {key: data['defaults'].get(key, '') for key in sorted(DEFAULT_KEYS)}}


class Gateway:
    def __init__(self, directory, transport=mcp_call):
        self.store, self.transport = PrivateStore(directory), transport
        self.sessions = {}
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
        PrivateStore.defaults(defaults)
        with self.store.locked() as data:
            self.current(data, body['revision'], configured=False)
            key = key_text(body['api_key']) if 'api_key' in body else data['api_key']
            require(key, 'provider_not_configured', 503)
        if 'api_key' in body:
            result = self.transport(key, 'invoke_api_endpoint', {'endpoint': 'getApiKeyInfo', 'arguments': {}})
            require(isinstance(result, dict) and all(isinstance(result.get(k), str) and 1 <= len(result[k]) <= 256
                    for k in ('org_id', 'org_name')), 'provider_verification_failed', 502)
        with self.store.locked() as data:
            self.current(data, body['revision'], configured=False)
            data.update(api_key=key, verified=True, defaults={**data['defaults'], **defaults}, revision=data['revision'] + 1)
            self.store.write(data)
            with self.session_lock:
                self.sessions.clear()
            return public_state(data)

    def disconnect(self, body):
        fields(body, {'revision'})
        with self.store.locked() as data:
            self.current(data, body['revision'], configured=False)
            data.update(api_key=None, verified=False, defaults={}, revision=data['revision'] + 1)
            self.store.write(data)
            with self.session_lock:
                self.sessions.clear()
            return public_state(data)

    def catalog(self, body):
        fields(body, {'revision'})
        with self.store.locked() as data:
            self.current(data, body['revision'])
        result = self.transport(data['api_key'], 'list_api_endpoints', {})
        require(isinstance(result, dict) and isinstance(result.get('endpoints'), list) and len(result['endpoints']) <= 500, 'provider_response_invalid', 502)
        known = set()
        new = []
        for row in result['endpoints']:
            require(isinstance(row, dict) and isinstance(row.get('endpoint'), str) and bool(ID.fullmatch(row['endpoint'])), 'provider_response_invalid', 502)
            known.add(row['endpoint'])
            if row['endpoint'] not in REGISTRY:
                new.append({'endpoint': row['endpoint'], 'available': False, 'blocked_reason': 'endpoint_unreviewed'})
        operations = []
        for endpoint, metadata in REGISTRY.items():
            row = dict(metadata)
            if endpoint not in known:
                row.update(available=False, blocked_reason='provider_endpoint_missing')
            operations.append(row)
        with self.store.locked() as latest:
            self.current(latest, data['revision'])
        return {'revision': data['revision'], 'registry_revision': REGISTRY_REVISION, 'operations': operations, 'new_operations': new}

    def schema(self, body):
        fields(body, {'revision', 'endpoint'})
        with self.store.locked() as data:
            self.current(data, body['revision'])
        endpoint = body['endpoint']
        value = input_schema(endpoint)
        return {'revision': data['revision'], 'endpoint': endpoint, 'input_schema': value,
                'schema_hash': schema_hash(endpoint), 'metadata': dict(REGISTRY[endpoint])}

    def prepare(self, body):
        fields(body, {'revision', 'endpoint', 'arguments'})
        endpoint, args = body['endpoint'], body['arguments']
        value = input_schema(endpoint)
        metadata = REGISTRY[endpoint]
        require(metadata['available'], metadata.get('blocked_reason', 'endpoint_unavailable'))
        require(isinstance(args, dict) and len(canonical(args).encode()) <= MAX_BODY, 'arguments_invalid')
        bounded_tree(args)
        validate_sensitive(args)
        # Never permit external schema resolution, even if a future pin is malformed.
        def refs(node):
            if isinstance(node, dict):
                require('$id' not in node and ('$ref' not in node or node['$ref'].startswith('#/')), 'registry_invalid', 503)
                for child in node.values(): refs(child)
            elif isinstance(node, list):
                for child in node: refs(child)
        refs(value)
        require(next(Draft202012Validator(value, format_checker=FormatChecker()).iter_errors(args), None) is None, 'arguments_invalid')
        with self.store.locked() as data:
            self.current(data, body['revision'])
            require(data['api_key'] not in canonical(args), 'sensitive_arguments_denied')
        return {'revision': data['revision'], 'endpoint': endpoint, 'schema_hash': schema_hash(endpoint),
                'requires_consent': metadata['risk'] != 'read', 'risk': metadata['risk']}

    def execute(self, body):
        fields(body, {'revision', 'endpoint', 'arguments', 'request_id', 'expected_schema_hash', 'consent_confirmed'})
        identifier = request_id(body['request_id'])
        require(type(body['consent_confirmed']) is bool)
        prepared = self.prepare({k: body[k] for k in ('revision', 'endpoint', 'arguments')})
        require(prepared['schema_hash'] == body['expected_schema_hash'], 'schema_changed', 409)
        require(not prepared['requires_consent'] or body['consent_confirmed'], 'consent_required', 409)
        endpoint = body['endpoint']
        with self.store.locked() as data:
            self.current(data, body['revision'])
            require(identifier not in data['reserved'], 'request_already_reserved', 409)
            key = data['api_key']
        # This check is read-only; reserve durably before any invocation side effect.
        remote = self.transport(key, 'get_api_endpoint_schema', {'endpoint': endpoint})
        require(isinstance(remote, dict) and remote.get('endpoint') == endpoint
                and semantic_schema(remote.get('input_schema')) == semantic_schema(input_schema(endpoint, strict=False)), 'schema_changed', 409)
        with self.store.locked() as data:
            self.current(data, body['revision'])
            require(identifier not in data['reserved'], 'request_already_reserved', 409)
            require(len(data['reserved']) < MAX_RESERVATIONS, 'reservation_capacity_reached', 503)
            data['reserved'].append(identifier)
            self.store.write(data)
            # Keep config lock through dispatch: a key rotation cannot race an
            # approved operation. All read invocations are reserved too.
            try:
                result = self.transport(key, 'invoke_api_endpoint', {'endpoint': endpoint, 'arguments': body['arguments']})
                if endpoint == 'createWebCall':
                    require(isinstance(result, dict) and isinstance(result.get('access_token'), str)
                            and 1 <= len(result['access_token']) <= 8192, 'provider_response_invalid', 502)
                    with self.session_lock:
                        self.prune_sessions()
                        require(len(self.sessions) < 100, 'session_capacity_reached', 503)
                        self.sessions[identifier] = (data['revision'], time.monotonic() + SESSION_SECONDS, result['access_token'])
                    call_id = result.get('call_id')
                    return {'status': 'ready', 'session_id': identifier,
                            **({'call_id': call_id} if isinstance(call_id, str) and bool(ID.fullmatch(call_id)) else {})}
                output = safe_output(result, secrets=(key,))
                if len(canonical(output).encode()) > 96 * 1024:
                    output = {'truncated': True, 'message': 'Provider result exceeded the safe response limit.'}
                return {'status': 'completed', 'endpoint': endpoint, 'data': output}
            except Exception:  # noqa: BLE001 - a reserved dispatch is never retried after an unknown outcome
                return {'status': 'external_outcome_unconfirmed', 'endpoint': endpoint, 'retryable': False}

    def prune_sessions(self):
        now = time.monotonic()
        for identifier in list(self.sessions):
            if self.sessions[identifier][1] <= now:
                del self.sessions[identifier]

    def claim(self, identifier, body):
        request_id(identifier)
        fields(body, {'revision'})
        with self.store.locked() as data:
            self.current(data, body['revision'])
            with self.session_lock:
                self.prune_sessions()
                value = self.sessions.pop(identifier, None)
                require(value is not None and value[0] == data['revision'], 'session_unavailable', 404)
                return {'access_token': value[2]}


class Handler(BaseHTTPRequestHandler):
    gateway = None
    token_file = None
    server_version = 'PrivateRetellGateway'

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
            report_gateway_error(error)
            self.reply(error.status, {'detail': error.code})
        except Exception as error:  # noqa: BLE001 - private HTTP errors never expose implementation or secrets
            report_gateway_fault(error)
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
                      '/catalog': self.gateway.catalog, '/schema': self.gateway.schema,
                      '/prepare': self.gateway.prepare, '/execute': self.gateway.execute}
            if self.path in routes:
                return self.reply(200, routes[self.path](body))
            match = re.fullmatch(r'/sessions/([0-9a-f-]{36})/claim', self.path)
            require(match, 'not_found', 404)
            self.reply(200, self.gateway.claim(match[1], body))
        except GatewayError as error:
            report_gateway_error(error)
            self.reply(error.status, {'detail': error.code})
        except (ValueError, TypeError, RecursionError) as error:
            report_gateway_fault(error)
            self.reply(422, {'detail': 'invalid_input'})
        except Exception as error:  # noqa: BLE001 - private HTTP errors never expose implementation or secrets
            report_gateway_fault(error)
            self.reply(503, {'detail': 'gateway_unavailable'})


def main():
    Handler.token_file = os.getenv('RETELL_GATEWAY_TOKEN_FILE')
    Handler.gateway = Gateway(os.getenv('RETELL_STATE_DIR', '/var/lib/jardines-retell'))
    GatewayServer(('0.0.0.0', 8093), Handler).serve_forever()


if __name__ == '__main__':
    main()
