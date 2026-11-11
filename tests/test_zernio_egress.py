"""Local-only regression tests for the fixed-target TLS CONNECT boundary."""
import importlib.util
import os
from pathlib import Path
import socket
import socketserver
import ssl
import time
import contextlib
import io
import tempfile
import subprocess
import shutil
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transport = load('zernio_transport', 'apps/api/app/social/transport.py')

    def test_direct_https_preserves_fixed_target_and_timeout(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(self.transport.http.client, 'HTTPSConnection') as factory:
            for host in ('zernio.com', 'mcp.zernio.com'):
                connection = self.transport.https_connection(host, timeout=3)
                factory.assert_called_with(host, timeout=3)
                connection.set_tunnel.assert_not_called()

    def test_exact_proxy_uses_https_target_tunnel_not_plaintext(self):
        with patch.dict(os.environ, {'ZERNIO_HTTPS_PROXY': 'http://zernio-egress:8080'}, clear=True), patch.object(self.transport.http.client, 'HTTPSConnection') as factory:
            connection = self.transport.https_connection('mcp.zernio.com', timeout=4)
            factory.assert_called_once_with('zernio-egress', 8080, timeout=4)
            connection.set_tunnel.assert_called_once_with('mcp.zernio.com', 443)

    def test_real_https_defaults_verify_target_certificate(self):
        with patch.dict(os.environ, {'ZERNIO_HTTPS_PROXY': 'http://zernio-egress:8080'}, clear=True):
            connection = self.transport.https_connection('zernio.com', timeout=3)
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(connection._tunnel_host, 'zernio.com')
        self.assertEqual(connection._tunnel_port, 443)
        connection.close()

    def test_wrong_hosts_or_proxy_configuration_fail_before_connection(self):
        invalid = ('', 'https://zernio-egress:8080', 'http://127.0.0.1:8080',
                   'http://zernio-egress:8080/', 'http://user@zernio-egress:8080',
                   'http://zernio-egress:8080?x=1')
        with patch.object(self.transport.http.client, 'HTTPSConnection') as factory:
            for value in invalid:
                with self.subTest(proxy=value), patch.dict(os.environ, {'ZERNIO_HTTPS_PROXY': value}, clear=True), self.assertRaises(ValueError):
                    self.transport.https_connection('zernio.com', timeout=3)
            for host in ('example.com', 'zernio.com.evil', 'https://zernio.com', '127.0.0.1', 'zernio.com:443'):
                with self.subTest(host=host), patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                    self.transport.https_connection(host, timeout=3)
            factory.assert_not_called()


class RelayPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relay = load('zernio_egress', 'ops/zernio/egress.py')

    def test_exact_connect_targets_only(self):
        for host in ('zernio.com', 'mcp.zernio.com'):
            self.assertEqual(self.relay.parse_connect(f'CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n'.encode()), host)
            self.assertEqual(self.relay.parse_connect(f'CONNECT {host}:443 HTTP/1.0\r\n\r\n'.encode()), host)
        denied = [b'GET / HTTP/1.1\r\n\r\n', b'CONNECT evil.example:443 HTTP/1.0\r\n\r\n',
                  b'CONNECT zernio.com:80 HTTP/1.0\r\n\r\n', b'CONNECT 127.0.0.1:443 HTTP/1.0\r\n\r\n',
                  b'CONNECT zernio.com:443/path HTTP/1.0\r\n\r\n', b'CONNECT https://zernio.com:443 HTTP/1.0\r\n\r\n',
                  b'CONNECT zernio.com:443 HTTP/1.1\r\nHost: evil.example:443\r\n\r\n',
                  b'CONNECT zernio.com:443 HTTP/1.1\r\nHost: zernio.com:443\r\nHost: zernio.com:443\r\n\r\n',
                  b'CONNECT zernio.com:443 HTTP/1.0\r\nContent-Length: 1\r\n\r\nx',
                  b'CONNECT zernio.com:443 HTTP/1.0\r\nAuthorization: secret\r\n\r\n',
                  b'CONNECT zernio.com:443 HTTP/1.0\n\n']
        for raw in denied:
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                self.relay.parse_connect(raw)

    def test_private_reserved_or_mixed_dns_answers_fail_closed(self):
        for address in ('127.0.0.1', '10.0.0.1', '172.16.0.1', '192.168.1.1',
                        '169.254.169.254', '0.0.0.0', '224.0.0.1', '192.0.2.1',
                        '100.64.0.1', '::1', 'fc00::1', 'fe80::1', '::ffff:127.0.0.1', '2001:db8::1'):
            family = socket.AF_INET6 if ':' in address else socket.AF_INET
            answer = (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
                      (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443))
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.relay.validate_addresses([answer])
        public = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('8.8.8.8', 443))
        private = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('10.0.0.1', 443))
        self.assertEqual(self.relay.validate_addresses([public]), [public])
        with self.assertRaises(ValueError):
            self.relay.validate_addresses([public, private])

    def test_header_overflow_rejected_without_dns(self):
        with self.assertRaises(ValueError):
            self.relay.parse_connect(b'CONNECT zernio.com:443 HTTP/1.0\r\nX: ' + b'x' * 4096 + b'\r\n\r\n')


class RelayFixtureTests(unittest.TestCase):
    def setUp(self):
        self.relay = load('zernio_egress_fixture', 'ops/zernio/egress.py')
        self.server = self.relay.Server(('127.0.0.1', 0))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def exchange(self, raw):
        with socket.create_connection(self.server.server_address, timeout=1) as connection:
            connection.sendall(raw)
            return connection.recv(4096)

    def test_invalid_requests_and_oversized_headers_never_resolve_or_log(self):
        output = io.StringIO()
        with patch.object(self.relay, 'connect_public') as connect, contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            for raw in (b'GET /secret-path HTTP/1.1\r\n\r\n',
                        b'CONNECT zernio.com:443 HTTP/1.0\r\nProxy-Authorization: fixture-secret\r\n\r\n',
                        b'CONNECT zernio.com:443 HTTP/1.0\r\nHost: ' + b'x' * 4096):
                self.assertIn(b'403 Forbidden', self.exchange(raw))
            connect.assert_not_called()
        self.assertEqual(output.getvalue(), '')

    def test_saturated_server_fails_closed_before_thread_or_dns(self):
        for _ in range(self.relay.MAX_CONNECTIONS):
            self.assertTrue(self.server.slots.acquire(blocking=False))
        try:
            with patch.object(self.relay, 'connect_public') as connect:
                self.assertIn(b'503 Service Unavailable', self.exchange(b'CONNECT zernio.com:443 HTTP/1.0\r\n\r\n'))
                connect.assert_not_called()
        finally:
            for _ in range(self.relay.MAX_CONNECTIONS):
                self.server.slots.release()

    def test_private_dns_failure_never_opens_peer_or_echoes_errors(self):
        sockets = SimpleNamespace(**{name: getattr(socket, name) for name in dir(socket)})
        sockets.getaddrinfo = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM,
            socket.IPPROTO_TCP, '', ('127.0.0.1', 443))])
        sockets.socket = Mock()
        with patch.object(self.relay, 'socket', sockets):
            response = self.exchange(b'CONNECT zernio.com:443 HTTP/1.0\r\n\r\n')
            self.assertIn(b'403 Forbidden', response)
            sockets.socket.assert_not_called()
        self.assertNotIn(b'127.0.0.1', response)

    def test_connection_uses_validated_numeric_address_without_reresolution(self):
        answer = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('8.8.8.8', 443))
        peer = Mock()
        with patch.object(self.relay, 'resolve_public', return_value=[answer]) as resolve, patch.object(self.relay.socket, 'socket', return_value=peer):
            self.assertIs(self.relay.connect_public('zernio.com', time.monotonic() + 1), peer)
        resolve.assert_called_once()
        peer.connect.assert_called_once_with(('8.8.8.8', 443))

    def test_aggregate_byte_and_wall_time_limits(self):
        client, app = socket.socketpair()
        peer, vendor = socket.socketpair()
        for connection in (client, app, peer, vendor):
            self.addCleanup(connection.close)
        errors = []
        def forward():
            try:
                self.relay.relay(client, peer, time.monotonic() + 1)
            except TimeoutError:
                errors.append('deadline')
        with patch.object(self.relay, 'MAX_TUNNEL_BYTES', 64):
            worker = threading.Thread(target=forward)
            worker.start()
            app.sendall(b'a' * 20)
            vendor.settimeout(1)
            self.assertEqual(vendor.recv(20), b'a' * 20)
            vendor.sendall(b'b' * 50)
            worker.join(1)
            self.assertFalse(worker.is_alive())
            app.settimeout(0.05)
            with self.assertRaises(TimeoutError):
                app.recv(1)
        with self.assertRaises(TimeoutError):
            self.relay.relay(client, peer, time.monotonic() - 1)

    def test_stuck_dns_keeps_bounded_capacity_until_completion(self):
        module = load('zernio_dns_capacity', 'ops/zernio/egress.py')
        release = threading.Event()
        def dns(*_args):
            release.wait(2)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('8.8.8.8', 443))]
        try:
            with patch.object(module.socket, 'getaddrinfo', side_effect=dns) as resolver, patch.object(module, 'DNS_TIMEOUT', 0.01):
                for _ in range(module.MAX_DNS_WORKERS):
                    with self.assertRaises(TimeoutError):
                        module.resolve_public('zernio.com', time.monotonic() + 1)
                with self.assertRaises(ValueError):
                    module.resolve_public('zernio.com', time.monotonic() + 1)
                self.assertEqual(resolver.call_count, module.MAX_DNS_WORKERS)
        finally:
            release.set()
            module._DNS_POOL.shutdown(wait=True)


@unittest.skipUnless(shutil.which('openssl'), 'Local self-signed TLS fixture requires openssl')
class EndToEndTLSFixtureTests(unittest.TestCase):
    def test_verified_target_tls_survives_connect_and_hostname_mismatch_is_denied(self):
        relay = load('zernio_tls_relay', 'ops/zernio/egress.py')
        transport = load('zernio_tls_transport', 'apps/api/app/social/transport.py')
        scratch = Path(tempfile.mkdtemp(prefix='jardines-zernio-tls-'))
        cert, key = scratch / 'fixture.crt', scratch / 'fixture.key'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=zernio.com', '-addext', 'subjectAltName=DNS:zernio.com',
            '-keyout', str(key), '-out', str(cert)], check=True, timeout=10, capture_output=True)
        key.chmod(0o600)
        print('TLS fixture scratch retained:', scratch)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert, key)
        client_context = ssl.create_default_context(cafile=str(cert))

        class Response(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                raw = self.rfile.readline(1024)
                if not raw.startswith(b'GET /fixture '):
                    return
                for _ in range(16):
                    if self.rfile.readline(1024) == b'\r\n':
                        break
                self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\nverified-tunnel')

        class TLS(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(2)
                return server_context.wrap_socket(connection, server_side=True), address
            def handle_error(self, *_args):
                pass

        vendor = TLS(('127.0.0.1', 0), Response)
        proxy = relay.Server(('127.0.0.1', 0))
        for server in (vendor, proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        original_connect = socket.create_connection
        original_https = transport.http.client.HTTPSConnection
        def local_proxy(address, *args, **kwargs):
            if address == ('zernio-egress', 8080):
                address = proxy.server_address
            return original_connect(address, *args, **kwargs)
        def tls_connection(*args, **kwargs):
            return original_https(*args, **kwargs, context=client_context)
        with patch.dict(os.environ, {'ZERNIO_HTTPS_PROXY': transport.PROXY}, clear=True), patch.object(transport, 'http', SimpleNamespace(client=SimpleNamespace(HTTPSConnection=tls_connection))), patch.object(socket, 'create_connection', side_effect=local_proxy), patch.object(relay, 'connect_public', side_effect=lambda _host, _deadline: original_connect(vendor.server_address, timeout=1)):
            connection = transport.https_connection('zernio.com', timeout=2)
            try:
                connection.request('GET', '/fixture')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'verified-tunnel')
            finally:
                connection.close()
            wrong = transport.https_connection('mcp.zernio.com', timeout=2)
            try:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    wrong.request('GET', '/fixture')
            finally:
                wrong.close()


if __name__ == '__main__':
    unittest.main()
