"""Credential-free CONNECT relay for exactly two verified public vendor hosts.

No TLS termination, HTTP application forwarding, arbitrary DNS names, or request logs.
The API keeps endpoint/method/scope policy; this relay only carries encrypted TLS.
"""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import select
import socket
import socketserver
import threading
import time

HOSTS = frozenset({'zernio.com', 'mcp.zernio.com'})
MAX_HEADER = 4096
MAX_CONNECTIONS = 8
MAX_DNS_WORKERS = 4
MAX_ADDRESSES = 16
MAX_TUNNEL_BYTES = 2 * 1024 * 1024
HEADER_TIMEOUT = 3
DNS_TIMEOUT = 2
CONNECT_TIMEOUT = 3
IDLE_TIMEOUT = 5
LIFETIME = 30
CHUNK = 16384
_DNS_POOL = ThreadPoolExecutor(max_workers=MAX_DNS_WORKERS, thread_name_prefix='vendor-dns')
_DNS_SLOTS = threading.BoundedSemaphore(MAX_DNS_WORKERS)


def parse_connect(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_HEADER or not raw.endswith(b'\r\n\r\n'):
        raise ValueError('CONNECT preface denied')
    if raw.find(b'\r\n\r\n') != len(raw) - 4:
        raise ValueError('CONNECT body denied')
    lines = raw[:-4].decode('ascii').split('\r\n')
    fields = lines[0].split(' ')
    if len(fields) != 3 or fields[0] != 'CONNECT' or fields[2] not in {'HTTP/1.0', 'HTTP/1.1'}:
        raise ValueError('Method denied')
    targets = {host + ':443': host for host in HOSTS}
    if fields[1] not in targets:
        raise ValueError('Target denied')
    host_header = None
    for line in lines[1:]:
        name, separator, value = line.partition(':')
        # The fixed stdlib client needs only Host (HTTP/1.1); no credentials,
        # request body, transfer framing, folded fields, or proxy options belong here.
        if not separator or name.lower() != 'host' or host_header is not None or value.strip() != fields[1]:
            raise ValueError('CONNECT header denied')
        host_header = value.strip()
    if fields[2] == 'HTTP/1.1' and host_header is None:
        raise ValueError('Host required')
    return targets[fields[1]]


def validate_addresses(answers):
    if not isinstance(answers, list) or not 1 <= len(answers) <= MAX_ADDRESSES:
        raise ValueError('Invalid DNS answer')
    vetted = []
    for family, kind, protocol, _canonical, address in answers:
        if family not in {socket.AF_INET, socket.AF_INET6} or kind != socket.SOCK_STREAM or protocol != socket.IPPROTO_TCP:
            raise ValueError('DNS family denied')
        if not isinstance(address, tuple) or address[1] != 443 or '%' in address[0]:
            raise ValueError('DNS address denied')
        ip = ipaddress.ip_address(address[0])
        if (not ip.is_global or ip.is_private or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or ip.is_loopback or ip.is_link_local
                or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)
                or (family == socket.AF_INET6 and (len(address) != 4 or address[3] != 0))):
            raise ValueError('Nonpublic DNS address denied')
        vetted.append((family, kind, protocol, '', address))
    return vetted


def remaining(deadline, ceiling):
    seconds = min(ceiling, deadline - time.monotonic())
    if seconds <= 0:
        raise TimeoutError('Relay deadline')
    return seconds


def resolve_public(host, deadline):
    if host not in HOSTS or not _DNS_SLOTS.acquire(blocking=False):
        raise ValueError('DNS unavailable')
    try:
        future = _DNS_POOL.submit(socket.getaddrinfo, host, 443, socket.AF_UNSPEC,
                                  socket.SOCK_STREAM, socket.IPPROTO_TCP)
    except Exception:
        _DNS_SLOTS.release()
        raise
    # A stuck libc resolver never creates an unbounded thread or task queue.
    # Timed-out in-flight work retains its slot until it actually completes.
    future.add_done_callback(lambda _future: _DNS_SLOTS.release())
    answers = future.result(timeout=remaining(deadline, DNS_TIMEOUT))
    return validate_addresses(answers)


def connect_public(host, deadline):
    for family, kind, protocol, _canonical, address in resolve_public(host, deadline):
        peer = socket.socket(family, kind, protocol)
        try:
            peer.settimeout(remaining(deadline, CONNECT_TIMEOUT))
            # Connect the vetted numeric sockaddr, never resolve the name again.
            peer.connect(address)
            return peer
        except OSError:
            peer.close()
    raise OSError('Vendor unavailable')


def read_preface(client, deadline):
    raw = bytearray()
    while True:
        client.settimeout(remaining(deadline, HEADER_TIMEOUT))
        chunk = client.recv(min(CHUNK, MAX_HEADER + 1 - len(raw)))
        if not chunk:
            raise ValueError('Incomplete CONNECT preface')
        raw.extend(chunk)
        if len(raw) > MAX_HEADER:
            raise ValueError('CONNECT header limit')
        if b'\r\n\r\n' in raw:
            return parse_connect(bytes(raw))


def relay(client, peer, deadline):
    """Forward opaque encrypted bytes with bounded aggregate traffic and wall time."""
    total = 0
    idle = time.monotonic() + IDLE_TIMEOUT
    while True:
        wait = remaining(min(deadline, idle), IDLE_TIMEOUT)
        readable, _, _ = select.select([client, peer], [], [], wait)
        if not readable:
            return
        for source in readable:
            target = peer if source is client else client
            source.settimeout(remaining(deadline, IDLE_TIMEOUT))
            chunk = source.recv(min(CHUNK, MAX_TUNNEL_BYTES - total + 1))
            if not chunk:
                return
            if total + len(chunk) > MAX_TUNNEL_BYTES:
                return
            target.settimeout(remaining(deadline, IDLE_TIMEOUT))
            target.sendall(chunk)
            total += len(chunk)
            idle = time.monotonic() + IDLE_TIMEOUT


def reject(client, status):
    try:
        client.settimeout(1)
        client.sendall(f'HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode('ascii'))
    except OSError:
        pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        peer = None
        established = False
        deadline = time.monotonic() + LIFETIME
        try:
            host = read_preface(self.request, min(deadline, time.monotonic() + HEADER_TIMEOUT))
            peer = connect_public(host, deadline)
            self.request.settimeout(remaining(deadline, HEADER_TIMEOUT))
            self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            established = True
            relay(self.request, peer, deadline)
        except ValueError:
            if not established:
                reject(self.request, '403 Forbidden')
        except (OSError, TimeoutError):
            if not established:
                reject(self.request, '502 Bad Gateway')
        finally:
            if peer is not None:
                peer.close()


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, address, handler=Handler):
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            reject(request, '503 Service Unavailable')
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # No request lines, headers, encrypted bodies, DNS answers, or traceback logs.
        pass


if __name__ == '__main__':
    with Server(('0.0.0.0', 8080)) as server:
        server.serve_forever(poll_interval=0.25)
