"""Isolated fake-provider tests; never contact a vendor or access a real credential."""
import base64
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

ROOT = Path(__file__).parents[1]


def load_gateway():
    spec = importlib.util.spec_from_file_location('elevenlabs_gateway', ROOT / 'ops/elevenlabs/gateway.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.g = load_gateway()
        self.tmp = tempfile.TemporaryDirectory(prefix='jardines-voice-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = 'fixture_vendor_key_12345678901234567890'
        self.calls = []
        self.replies = {}
        self.gateway = self.g.Gateway(self.root / 'private', transport=self.vendor)
        self.addCleanup(self.gateway.close)

    def vendor(self, method, path, key, body=None, content_type='application/json', binary=False):
        self.calls.append((method, path, key, body, content_type, binary))
        value = self.replies.get(path)
        if isinstance(value, BaseException):
            raise value
        if value is not None:
            return value
        if path == '/v1/user':
            return {'user_id': 'fixture-user'}
        if path.startswith('/v2/voices'):
            return {'voices': [{'voice_id': 'voice_1', 'name': 'Voice', 'preview_url': 'https://not-forwarded'}], 'has_more': False}
        if path == '/v1/models':
            return [{'model_id': 'model_1', 'name': 'Model', 'can_do_text_to_speech': True}]
        if path.startswith('/v1/convai/agents?'):
            return {'agents': [{'agent_id': 'agent_1', 'name': 'Agent'}], 'has_more': False}
        if path.startswith('/v1/convai/phone-numbers'):
            return [{'phone_number_id': 'phone_1', 'label': 'Office', 'provider': 'twilio'}]
        if path.startswith('/v1/text-to-speech/'):
            return b'ID3fixture_audio'
        if path == '/v1/speech-to-text':
            return {'text': 'Texto transcrito.'}
        if path.startswith('/v1/convai/conversation/token?'):
            return {'token': 'private_ephemeral_fixture_token', 'conversation_id': 'conversation_1'}
        if path == '/v1/convai/twilio/outbound-call':
            return {'success': True, 'conversation_id': 'conversation_1', 'callSid': 'call_1', 'message': 'ignored'}
        raise AssertionError('Unexpected vendor route')

    def configure(self):
        return self.gateway.configure({'revision': 0, 'api_key': self.key})

    def execute(self, operation, arguments, identifier=None, revision=1):
        return self.gateway.execute({'id': identifier or str(uuid4()), 'revision': revision,
                                     'operation': operation, 'arguments': arguments})

    def test_configuration_is_private_atomic_versioned_and_disconnect_revokes(self):
        self.assertEqual(self.gateway.state()['revision'], 0)
        result = self.configure()
        self.assertEqual(result['revision'], 1)
        self.assertTrue(result['configured'] and result['verified'])
        self.assertNotIn(self.key, json.dumps(result))
        self.assertEqual(result['key_suffix'], self.key[-4:])
        self.assertEqual(os.stat(self.root / 'private/state.json').st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.root / 'private').st_mode & 0o777, 0o700)
        with self.assertRaises(self.g.GatewayError):
            self.gateway.configure({'revision': 0, 'api_key': self.key})
        self.assertEqual(len(self.calls), 1)
        result = self.gateway.disconnect({'revision': 1})
        self.assertEqual(result['revision'], 2)
        self.assertFalse(result['configured'])
        self.assertNotIn(self.key, (self.root / 'private/state.json').read_text())

    def test_failed_key_verification_preserves_previous_key(self):
        self.configure()
        before = (self.root / 'private/state.json').read_bytes()
        self.replies['/v1/user'] = self.g.GatewayError(502, 'provider_unavailable')
        with self.assertRaises(self.g.GatewayError):
            self.gateway.configure({'revision': 1, 'api_key': 'another_fixture_key_1234567890123456'})
        self.assertEqual((self.root / 'private/state.json').read_bytes(), before)

    def test_partial_catalog_is_bounded_and_sanitized(self):
        self.configure()
        self.replies['/v1/convai/agents?page_size=50'] = self.g.GatewayError(502, 'provider_unavailable')
        result = self.gateway.catalog({'revision': 1})
        self.assertEqual(result['errors'], ['agents'])
        self.assertEqual(result['agents'], [])
        self.assertEqual(result['voices'], [{'id': 'voice_1', 'name': 'Voice'}])
        self.assertNotIn('preview_url', json.dumps(result))
        self.assertNotIn(self.key, json.dumps(result))

    def test_catalog_labels_fit_the_shared_api_boundary(self):
        self.configure()
        for length in (120, 121, 200):
            with self.subTest(length=length):
                self.replies['/v2/voices?page_size=50'] = {
                    'voices': [{'voice_id': 'voice_1', 'name': 'V' * length}]
                }
                result = self.gateway.catalog({'revision': 1})
                self.assertEqual(result['errors'], [])
                self.assertEqual(result['voices'], [{'id': 'voice_1', 'name': 'V' * 120}])

    def test_all_operations_have_fixed_payloads_and_no_token_in_results_or_disk(self):
        self.configure()
        tts = self.execute('tts', {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1'})
        self.assertEqual(base64.b64decode(tts['data_base64']), b'ID3fixture_audio')
        self.assertEqual(self.calls[-1][1], '/v1/text-to-speech/voice_1?output_format=mp3_22050_32')
        audio = base64.b64encode(b'RIFF' + b'\x00' * 4 + b'WAVEdata').decode()
        stt = self.execute('stt', {'data_base64': audio, 'mime_type': 'audio/wav'})
        self.assertEqual(stt['text'], 'Texto transcrito.')
        self.assertIn(b'scribe_v2', self.calls[-1][3])
        self.assertNotIn(b'cloud_storage_url', self.calls[-1][3])
        identifier = str(uuid4())
        self.assertEqual(self.execute('agent_session', {'agent_id': 'agent_1'}, identifier), {'status': 'ready'})
        disk = (self.root / 'private/state.json').read_text()
        self.assertNotIn('private_ephemeral', disk)
        material = self.gateway.claim(identifier, {'revision': 1})
        self.assertEqual(material['token'], 'private_ephemeral_fixture_token')
        with self.assertRaises(self.g.GatewayError):
            self.gateway.claim(identifier, {'revision': 1})
        call = self.execute('outbound_call', {'agent_id': 'agent_1', 'phone_number_id': 'phone_1', 'to_number': '+573001234567'})
        self.assertEqual(call, {'status': 'completed', 'conversation_id': 'conversation_1', 'call_id': 'call_1'})
        payload = json.loads(self.calls[-1][3])
        self.assertFalse(payload['call_recording_enabled'])
        self.assertEqual(payload['agent_phone_number_id'], 'phone_1')

    def test_uncertain_execution_is_durably_consumed_even_after_restart(self):
        self.configure()
        identifier = str(uuid4())
        path = '/v1/text-to-speech/voice_1?output_format=mp3_22050_32'
        self.replies[path] = TimeoutError('private error with secret')
        with self.assertRaises(self.g.GatewayError):
            self.execute('tts', {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1'}, identifier)
        count = len(self.calls)
        restarted = self.g.Gateway(self.root / 'private', transport=self.vendor)
        with self.assertRaises(self.g.GatewayError) as context:
            restarted.execute({'id': identifier, 'revision': 1, 'operation': 'tts',
                               'arguments': {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1'}})
        self.assertEqual(context.exception.code, 'dispatch_already_reserved')
        self.assertEqual(len(self.calls), count)

    def test_strict_invalid_inputs_and_stale_revision_never_dispatch(self):
        self.configure()
        count = len(self.calls)
        cases = [
            ('tts', {'text': ' ' * 1501 + 'x', 'voice_id': 'voice_1', 'model_id': 'model_1'}),
            ('tts', {'text': 'x' * 1501, 'voice_id': 'voice_1', 'model_id': 'model_1'}),
            ('tts', {'text': 'Hola', 'voice_id': '../bad', 'model_id': 'model_1'}),
            ('tts', {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1', 'url': 'https://other'}),
            ('stt', {'data_base64': '!', 'mime_type': 'audio/wav'}),
            ('outbound_call', {'agent_id': 'agent_1', 'phone_number_id': 'phone_1', 'to_number': '3001234567'}),
            ('shell', {}),
        ]
        for operation, arguments in cases:
            with self.subTest(operation=operation), self.assertRaises(self.g.GatewayError):
                self.execute(operation, arguments)
        with self.assertRaises(self.g.GatewayError):
            self.execute('agent_session', {'agent_id': 'agent_1'}, revision=0)
        self.assertEqual(len(self.calls), count)

    def test_false_call_success_and_oversized_media_fail_consumed(self):
        self.configure()
        self.replies['/v1/convai/twilio/outbound-call'] = {'success': False, 'message': self.key}
        with self.assertRaises(self.g.GatewayError):
            self.execute('outbound_call', {'agent_id': 'agent_1', 'phone_number_id': 'phone_1', 'to_number': '+573001234567'})
        self.replies['/v1/text-to-speech/voice_1?output_format=mp3_22050_32'] = b'x' * (2 * 1024 * 1024 + 1)
        with self.assertRaises(self.g.GatewayError):
            self.execute('tts', {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1'})

    def test_session_expiry_rotation_and_unknown_state_symlink_fail_closed(self):
        self.configure()
        identifier = str(uuid4())
        self.execute('agent_session', {'agent_id': 'agent_1'}, identifier)
        with patch.object(self.g.time, 'monotonic', return_value=10**12), self.assertRaises(self.g.GatewayError):
            self.gateway.claim(identifier, {'revision': 1})
        path = self.root / 'private/state.json'
        path.unlink()
        path.symlink_to(self.root / 'other')
        with self.assertRaises(self.g.GatewayError):
            self.gateway.state()


    def test_defaults_can_be_cleared_and_dispatch_journal_never_silently_evicts(self):
        self.configure()
        result = self.gateway.configure({'revision': 1, 'defaults': {'agent_id': 'agent_1'}})
        self.assertEqual(result['defaults']['agent_id'], 'agent_1')
        result = self.gateway.configure({'revision': 2, 'defaults': {'agent_id': ''}})
        self.assertEqual(result['defaults']['agent_id'], '')
        self.assertEqual(set(result['defaults']), self.g.DEFAULT_KEYS)
        with patch.object(self.g, 'MAX_RESERVATIONS', 1):
            self.execute('agent_session', {'agent_id': 'agent_1'}, revision=3)
            with self.assertRaises(self.g.GatewayError) as context:
                self.execute('agent_session', {'agent_id': 'agent_1'}, revision=3)
            self.assertEqual(context.exception.code, 'dispatch_capacity_exceeded')

    def test_concurrent_key_rotation_has_one_cas_winner(self):
        self.configure()
        barrier = threading.Barrier(2)
        def verification(*_args, **_kwargs):
            barrier.wait(timeout=2)
            return {'user_id': 'fixture-user'}
        first = self.g.Gateway(self.root / 'private', transport=verification)
        second = self.g.Gateway(self.root / 'private', transport=verification)
        def rotate(pair):
            gateway, number = pair
            try:
                gateway.configure({'revision': 1, 'api_key': 'replacement_fixture_key_1234567890' + str(number)})
                return 200
            except self.g.GatewayError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(rotate, [(first, 1), (second, 2)]))
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(self.gateway.state()['revision'], 2)

    def test_concurrent_duplicate_is_reserved_before_vendor_returns(self):
        self.configure()
        started, release = threading.Event(), threading.Event()
        count = []
        def blocked(*_args, **_kwargs):
            count.append(1)
            started.set()
            self.assertTrue(release.wait(2))
            return b'ID3audio'
        self.gateway.transport = blocked
        identifier = str(uuid4())
        arguments = {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1'}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.execute, 'tts', arguments, identifier)
            try:
                self.assertTrue(started.wait(2))
                with self.assertRaises(self.g.GatewayError) as context:
                    self.execute('tts', arguments, identifier)
                self.assertEqual(context.exception.code, 'dispatch_already_reserved')
            finally:
                release.set()
            self.assertEqual(future.result(timeout=2)['status'], 'completed')
        self.assertEqual(count, [1])

    def test_catalog_network_does_not_lock_state_and_detects_rotation(self):
        self.configure()
        started, release = threading.Event(), threading.Event()
        vendor = self.vendor
        def blocked(method, path, *args, **kwargs):
            if path.startswith('/v2/voices'):
                started.set()
                self.assertTrue(release.wait(2))
            return vendor(method, path, *args, **kwargs)
        self.gateway.transport = blocked
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.gateway.catalog, {'revision': 1})
            try:
                self.assertTrue(started.wait(2))
                self.assertEqual(self.gateway.state()['revision'], 1)
                self.gateway.disconnect({'revision': 1})
            finally:
                release.set()
            with self.assertRaises(self.g.GatewayError) as context:
                future.result(timeout=2)
            self.assertEqual(context.exception.code, 'configuration_changed')

    def test_transport_is_fixed_no_redirect_no_proxy_and_bounded(self):
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default=None: {
            'Content-Type': 'application/json', 'Content-Length': '18',
        }.get(name, default)
        source = io.BytesIO(b'{"user_id":"user"}')
        response.read1.side_effect = source.read
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://not-used:8888'}), patch.object(self.g, 'HTTPSConnection', return_value=connection) as factory:
            self.assertEqual(self.g.vendor_request('GET', '/v1/user', self.key), {'user_id': 'user'})
            factory.assert_called_once_with('api.elevenlabs.io', port=443, timeout=5)
            self.assertEqual(connection.request.call_args.args[:2], ('GET', '/v1/user'))
            response.status = 302
            with self.assertRaises(self.g.GatewayError):
                self.g.vendor_request('GET', '/v1/user', self.key)
            self.assertEqual(factory.call_count, 2)
            with self.assertRaises(self.g.GatewayError):
                self.g.vendor_request('GET', 'https://other.example/v1/user', self.key)
            self.assertEqual(factory.call_count, 2)
            response.status = 200
            response.getheader.side_effect = lambda name, default=None: str(self.g.MAX_JSON + 1) if name == 'Content-Length' else default
            with self.assertRaises(self.g.GatewayError):
                self.g.vendor_request('GET', '/v1/user', self.key)

    def test_absolute_deadlines_stop_provider_and_ingress_drips(self):
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default=None: 'application/json' if name == 'Content-Type' else default
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(self.g, 'HTTPSConnection', return_value=connection), patch.object(self.g.time, 'monotonic', side_effect=[0, 6]), self.assertRaises(self.g.GatewayError):
            self.g.vendor_request('GET', '/v1/user', self.key)
        sock = Mock()
        with patch.object(self.g.time, 'monotonic', side_effect=[0, 41]):
            reader = self.g.DeadlineReader(sock)
            with self.assertRaises(TimeoutError):
                reader.readinto(bytearray(10))
        sock.recv_into.assert_not_called()

    def test_private_fifo_and_wrong_mode_are_rejected_without_blocking(self):
        self.configure()
        state = self.root / 'private/state.json'
        state.chmod(0o644)
        with self.assertRaises(self.g.GatewayError):
            self.gateway.state()
        state.unlink()
        os.mkfifo(state, 0o600)
        with self.assertRaises(self.g.GatewayError):
            self.gateway.state()

    def test_http_service_auth_no_store_and_state_stays_available_during_paid_io(self):
        token = self.root / 'service.token'
        token.write_text('fixture_internal_service_token_1234567890')
        token.chmod(0o600)
        self.g.Handler.gateway, self.g.Handler.token_file = self.gateway, str(token)
        server = self.g.GatewayServer(('127.0.0.1', 0), self.g.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def request(method, path, body=None, auth=True):
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            headers = {'Content-Type': 'application/json'}
            if auth:
                headers['Authorization'] = 'Bearer ' + token.read_text()
            try:
                conn.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
                response = conn.getresponse()
                return response.status, response.read(), dict(response.getheaders())
            finally:
                conn.close()
        self.assertEqual(request('GET', '/health/live', auth=False)[0], 200)
        self.assertEqual(request('GET', '/state', auth=False)[0], 401)
        status, raw, headers = request('POST', '/configure', {'revision': 0, 'api_key': self.key})
        self.assertEqual(status, 200)
        self.assertNotIn(self.key.encode(), raw)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        started, release = threading.Event(), threading.Event()
        def blocked(*_args, **_kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return b'ID3audio'
        self.gateway.transport = blocked
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(request, 'POST', '/execute', {
                'id': str(uuid4()), 'revision': 1, 'operation': 'tts',
                'arguments': {'text': 'Hola', 'voice_id': 'voice_1', 'model_id': 'model_1'},
            })
            try:
                self.assertTrue(started.wait(2))
                self.assertEqual(request('GET', '/state')[0], 200)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=2)[0], 200)
        token.unlink()
        self.assertEqual(request('GET', '/state', auth=False)[0], 503)



    def test_dns_is_bounded_vetted_and_tls_uses_literal_vendor_sni(self):
        future = Mock()
        slots = Mock()
        slots.acquire.return_value = True
        pool = Mock()
        pool.submit.return_value = future
        future.result.return_value = [(self.g.socket.AF_INET, self.g.socket.SOCK_STREAM,
                                       self.g.socket.IPPROTO_TCP, '', ('127.0.0.1', 443))]
        with patch.object(self.g, 'DNS_POOL', pool), patch.object(self.g, 'DNS_SLOTS', slots), patch.object(self.g.socket, 'socket') as factory:
            with self.assertRaises(self.g.GatewayError):
                self.g.vendor_socket(self.g.time.monotonic() + 5)
            factory.assert_not_called()
            self.assertLessEqual(future.result.call_args.kwargs['timeout'], 2)
            self.assertEqual(pool.submit.call_args.args[1], 'api.elevenlabs.io')
        future.result.return_value = [(self.g.socket.AF_INET, self.g.socket.SOCK_STREAM,
                                       self.g.socket.IPPROTO_TCP, '', ('1.1.1.1', 443))]
        raw, secured, context = Mock(), Mock(), Mock()
        context.wrap_socket.return_value = secured
        with patch.object(self.g, 'DNS_POOL', pool), patch.object(self.g, 'DNS_SLOTS', slots), patch.object(self.g.socket, 'socket', return_value=raw), patch.object(self.g.ssl, 'create_default_context', return_value=context):
            wrapper = self.g.vendor_socket(self.g.time.monotonic() + 5)
            self.assertIs(wrapper.sock, secured)
            raw.connect.assert_called_once_with(('1.1.1.1', 443))
            context.wrap_socket.assert_called_once_with(raw, server_hostname='api.elevenlabs.io')
        slots.acquire.return_value = False
        with patch.object(self.g, 'DNS_SLOTS', slots), patch.object(self.g, 'DNS_POOL', pool):
            before = pool.submit.call_count
            with self.assertRaises(self.g.GatewayError):
                self.g.vendor_socket(self.g.time.monotonic() + 5)
            self.assertEqual(pool.submit.call_count, before)

    def test_session_tokens_are_actively_erased_and_service_token_files_fail_closed(self):
        self.configure()
        identifier = str(uuid4())
        timer = Mock()
        with patch.object(self.g.threading, 'Timer', return_value=timer) as factory:
            self.execute('agent_session', {'agent_id': 'agent_1'}, identifier)
            self.assertEqual(factory.call_args.args[:2], (60, self.gateway.expire_one))
            self.assertTrue(timer.daemon)
            timer.start.assert_called_once()
            self.gateway.expire_one(identifier)
        self.assertNotIn(identifier, self.gateway.sessions)
        token = self.root / 'service.token'
        token.write_text('x' * 32)
        token.chmod(0o600)
        self.assertEqual(self.g.service_token(str(token)), 'x' * 32)
        token.write_text('x' * 129)
        with self.assertRaises(self.g.GatewayError):
            self.g.service_token(str(token))
        token.write_text('x' * 32)
        token.chmod(0o644)
        with self.assertRaises(self.g.GatewayError):
            self.g.service_token(str(token))
        link = self.root / 'service.link'
        link.symlink_to(token)
        with self.assertRaises(self.g.GatewayError):
            self.g.service_token(str(link))

    def test_catalog_more_than_fifty_and_permission_failures_are_explicit(self):
        self.configure()
        self.replies['/v2/voices?page_size=50'] = {
            'voices': [{'voice_id': 'voice_' + str(number), 'name': 'Voice'} for number in range(60)],
            'has_more': True,
        }
        self.replies['/v1/models'] = [{'model_id': 'not_tts', 'name': 'No speech', 'can_do_text_to_speech': False}]
        result = self.gateway.catalog({'revision': 1})
        self.assertEqual(len(result['voices']), 50)
        self.assertTrue(result['limited'])
        self.assertEqual(result['models'], [])
        self.assertEqual(result['errors'], [])
        self.replies['/v1/models'] = {'detail': {'message': self.key}}
        result = self.gateway.catalog({'revision': 1})
        self.assertEqual(result['errors'], ['models'])
        self.assertNotIn(self.key, json.dumps(result))



    def test_real_http_parser_preserves_close_delimited_fake_vendor_body(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class FakeVendor(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"user_id":"fixture"}')
        server = HTTPServer(('127.0.0.1', 0), FakeVendor)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def local_fake(deadline):
            sock = self.g.socket.create_connection(('127.0.0.1', server.server_port), timeout=2)
            return self.g.DeadlineSocket(sock, deadline)
        with patch.object(self.g, 'vendor_socket', side_effect=local_fake):
            self.assertEqual(self.g.vendor_request('GET', '/v1/user', self.key), {'user_id': 'fixture'})



if __name__ == '__main__':
    unittest.main()
