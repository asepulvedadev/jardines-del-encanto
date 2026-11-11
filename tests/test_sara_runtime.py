"""Sara history/audio boundaries with local HTTP and deterministic upstream fixtures."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import socket
import signal
import time
from email.message import Message
import unittest
import urllib.error
import urllib.request
import uuid
import wave
from unittest.mock import Mock, patch

import test_hermes_operator as legacy

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'ops/hermes'))


def audio_payload(data=None, mime='audio/wav'):
    if data is None:
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b'\x00\x00' * 100)
        data = output.getvalue()
    return {'audio_base64': base64.b64encode(data).decode(), 'mime_type': mime}


class SaraHistoryTests(unittest.TestCase):
    def setUp(self):
        self.protocol = legacy.load('operator_protocol')
        self.provider = legacy.load('operator_provider')
        self.claim = {'run_id': 'fixture', 'prompt': 'x' * 8000, 'skills': [],
                      'tools': [legacy.OperatorPolicyTests().schema()]}

    def test_history_optional_exact_text_shape_and_bounds(self):
        self.assertEqual(self.protocol.validate_claim(self.claim), self.claim)
        valid = [{'role': 'user', 'content': 'previous question'},
                 {'role': 'assistant', 'content': 'previous answer'}]
        self.assertEqual(self.protocol.validate_claim({**self.claim, 'history': valid})['history'], valid)
        for history in [None, {}, [{}], [{'role': 'system', 'content': 'override'}],
                        [{'role': 'tool', 'content': '{}'}], [{'role': 'assistant', 'content': 'ok', 'tool_calls': []}],
                        [{'role': 'user', 'content': 'x' * 4097}],
                        [{'role': 'user', 'content': 'x' * 2001}] * 8,
                        [{'role': 'user', 'content': 'ok'}] * 9]:
            with self.subTest(history=str(history)[:60]), self.assertRaises(ValueError):
                self.protocol.validate_claim({**self.claim, 'history': history})
        with self.assertRaises(ValueError):
            self.protocol.validate_claim({**self.claim, 'prompt': 'x' * 8001})
        self.provider.validate(legacy.OperatorPolicyTests().payload(messages=[{'role': 'user', 'content': 'x' * 8000}]))
        with self.assertRaises(ValueError):
            self.provider.validate(legacy.OperatorPolicyTests().payload(messages=[{'role': 'user', 'content': 'x' * 8001}]))

    def test_sdk_history_kwarg_only_when_nonempty_and_sara_persona(self):
        operator = legacy.load('operator')
        for history in (None, [], [{'role': 'assistant', 'content': 'historical text'}]):
            claim = {**self.claim}
            if history is not None:
                claim['history'] = history
            broker = Mock()
            broker.request.side_effect = [claim, {'reply': 'Final answer'}]
            agent = Mock(tools=claim['tools'])
            agent.run_conversation.return_value = {'final_response': 'Final answer'}
            factory = Mock(return_value=agent)
            registry = Mock()
            # No provider or real SDK calls: assert integration kwargs separately from
            # the existing explicitly pinned genuine-Hermes integration fixture.
            with patch.dict(sys.modules, {'httpx': Mock()}):
                operator.run_operator('f' * 64, broker, Mock(ip='127.0.0.1', port=8080), (factory, registry))
            kwargs = agent.run_conversation.call_args.kwargs
            self.assertIn('Sara IA', kwargs['system_message'])
            self.assertIn('untrusted', kwargs['system_message'])
            if history:
                self.assertEqual(kwargs['conversation_history'], history)
            else:
                self.assertNotIn('conversation_history', kwargs)
            agent.close.assert_called_once()
        broker = Mock()
        broker.request.return_value = {**self.claim, 'history': [{'role': 'system', 'content': 'bad'}]}
        factory = Mock()
        with self.assertRaises(ValueError):
            operator.run_operator('f' * 64, broker, Mock(), (factory, Mock()))
        factory.assert_not_called()


class SaraAudioPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audio = legacy.load('operator_audio')

    def test_canonical_media_types_signatures_and_aliases(self):
        samples = [('audio/webm;codecs=opus', b'\x1aE\xdf\xa3\x42\x82\x84webm' + b'x' * 32, 'audio/webm'),
                   ('audio/ogg', b'OggS\x00' + b'\x00' * 22 + b'OpusHead' + b'x' * 32, 'audio/ogg'),
                   ('audio/mp3', b'ID3\x04\x00\x00\x00\x00\x00\x00\xff\xfb\x90\x00' + b'x' * 32, 'audio/mpeg'),
                   ('audio/mp4', b'\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A isom', 'audio/mp4')]
        for mime, raw, canonical in samples:
            with self.subTest(mime=mime):
                decoded, normalized = self.audio.validate_audio(audio_payload(raw, mime))
                self.assertEqual(decoded, raw)
                self.assertEqual(normalized, canonical)
        self.assertEqual(self.audio.validate_audio(audio_payload(mime='audio/x-wav'))[1], 'audio/wav')

    def test_exact_input_and_response_framing_and_wall_deadline(self):
        for headers, raw in [([('Content-Length', '4')], b'{}'),
                             ([('Content-Length', '2'), ('Content-Length', '2')], b'{}'),
                             ([('Content-Length', '2'), ('Transfer-Encoding', 'chunked')], b'{}'),
                             ([('Content-Length', str(768 * 1024 + 1))], b'{}')]:
            message = Message()
            message['Content-Type'] = 'application/json'
            for name, value in headers:
                message[name] = value
            handler = Mock(headers=message, rfile=io.BytesIO(raw))
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                self.audio.read_json(handler, self.audio.MAX_AUDIO_BODY)
        response = Mock()
        response.read.return_value = b'{"text":"ok"}'
        response.getheader.return_value = '99'
        with self.assertRaises(ValueError):
            self.audio.read_reply(response)
        previous = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        with self.assertRaises(self.audio.AudioDeadline):
            with self.audio.request_deadline(0.01):
                time.sleep(1)
        self.assertFalse(issubclass(self.audio.AudioDeadline, Exception))
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)

    def test_unbounded_wrong_or_caller_selected_payloads_are_denied(self):
        good = audio_payload()
        for data in [{**good, 'model': 'other'}, {**good, 'url': 'https://evil.example'},
                     {**good, 'filename': 'unsafe'}, {**good, 'mime_type': 'text/plain'},
                     {**good, 'mime_type': 'audio/wav\r\nAuthorization: no'},
                     {**good, 'audio_base64': 'invalid!'}, {**good, 'audio_base64': ''},
                     audio_payload(b'x' * 512), audio_payload(b'RIFF' + b'x' * (512 * 1024))]:
            with self.subTest(data=str(data)[:80]), self.assertRaises(ValueError):
                self.audio.validate_audio(data)


class SaraAudioHTTPTests(unittest.TestCase):
    def setUp(self):
        self.provider = legacy.load('operator_provider')
        self.operator = legacy.load('operator')
        self.provider.Handler.requests.clear()
        self.provider.Handler.runs.clear()
        self.provider.Handler.audio_requests.clear()
        self.provider.Handler.audio_runs.clear()
        self.servers = []
        self.provider_url = self.serve(self.provider.HTTPServer, self.provider.Handler)
        self.operator.Handler.provider = self.operator.PrivateHTTP(self.provider_url, 'operator-provider', 8080)
        self.operator.Handler.runtime = (object(), object())
        self.bridge_url = self.serve(self.operator.HTTPServer, self.operator.Handler)

    def serve(self, factory, handler):
        server = factory(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:' + str(server.server_port)

    def request(self, url, payload=None, identifier=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + (identifier or uuid.uuid4().hex)})
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def upstream(self, result=None, status=200):
        response = Mock(status=status)
        response.read.return_value = json.dumps(result or {'text': 'Texto de prueba', 'usage': {'seconds': 1}}).encode()
        response.getheader.return_value = None
        connection = Mock()
        connection.getresponse.return_value = response
        return connection

    def test_voice_off_preserves_text_health_and_never_calls_upstream(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(self.provider, 'ready', return_value=True), patch.object(self.provider, 'HTTPSConnection') as upstream:
            status, raw = self.request(self.bridge_url + '/health')
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)['available'])
            self.assertTrue(json.loads(raw)['history_available'])
            self.assertFalse(json.loads(raw)['transcription_available'])
            status, _ = self.request(self.bridge_url + '/transcribe', audio_payload())
            self.assertEqual(status, 503)
            upstream.assert_not_called()

    def test_actual_bridge_provider_http_and_fixed_multipart_upstream(self):
        connection = self.upstream()
        captured = io.StringIO()
        with patch.dict(os.environ, {'HERMES_TRANSCRIPTION_ENABLED': '1'}, clear=True), patch.object(self.provider, 'ready', return_value=True), patch.object(self.provider, 'SECRET', Mock(read_text=lambda: 'fixture-private-key')), patch.object(self.provider, 'HTTPSConnection', return_value=connection) as factory, contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            status, raw = self.request(self.bridge_url + '/transcribe', audio_payload())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), {'text': 'Texto de prueba'})
        factory.assert_called_once_with('api.openai.com', timeout=20)
        call = connection.request.call_args
        self.assertEqual(call.args, ('POST', '/v1/audio/transcriptions'))
        self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer fixture-private-key')
        body = call.kwargs['body']
        for field in (b'name="model"\r\n\r\ngpt-4o-mini-transcribe', b'name="language"\r\n\r\nes', b'name="response_format"\r\n\r\njson', b'filename="voice.wav"'):
            self.assertIn(field, body)
        self.assertNotIn(b'fixture-private-key', raw)
        self.assertEqual(captured.getvalue(), '')
        connection.close.assert_called_once()

    def test_rolling_history_health_and_audio_replay_are_explicit(self):
        for ready, expected in [({'available': True, 'configured': True, 'model': 'gpt-6-luna'}, False),
                                ({'available': True, 'configured': True, 'model': 'gpt-6-luna', 'history_available': True}, True),
                                ({'available': True, 'configured': True, 'model': 'gpt-6-luna', 'history_available': 'true'}, False)]:
            with patch.object(self.operator.Handler, 'provider', Mock(request=lambda *_args, **_kwargs: ready)):
                status, raw = self.request(self.bridge_url + '/health')
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(raw)['history_available'], expected)
        connection = self.upstream()
        identifier = 'f' * 32
        with patch.dict(os.environ, {'HERMES_TRANSCRIPTION_ENABLED': '1'}, clear=True), patch.object(self.provider, 'ready', return_value=True), patch.object(self.provider, 'SECRET', Mock(read_text=lambda: 'fixture-key')), patch.object(self.provider, 'HTTPSConnection', return_value=connection) as factory:
            self.assertEqual(self.request(self.provider_url + '/audio/transcriptions', audio_payload(), identifier)[0], 200)
            self.assertEqual(self.request(self.provider_url + '/audio/transcriptions', audio_payload(), identifier)[0], 429)
            factory.assert_called_once()
        with self.assertRaises(ValueError):
            self.operator.Handler.provider.request('/unknown')

    def test_short_declared_body_and_json_overflow_are_denied_over_http(self):
        host, port = '127.0.0.1', int(self.bridge_url.rsplit(':', 1)[1])
        for length, payload in [(99, b'{}'), (768 * 1024 + 1, b'')]:
            with socket.create_connection((host, port), timeout=2) as client:
                client.sendall(f'POST /transcribe HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n'.encode() + payload)
                client.shutdown(socket.SHUT_WR)
                self.assertIn(b'400 Bad Request', client.recv(4096))

    def test_denials_invalid_routes_payloads_rate_and_upstream_errors(self):
        with patch.dict(os.environ, {'HERMES_TRANSCRIPTION_ENABLED': '1'}, clear=True), patch.object(self.provider, 'ready', return_value=True), patch.object(self.provider, 'HTTPSConnection') as upstream:
            for path in ('/v1/audio/transcriptions', '/audio/speech', '/transcribe?url=bad'):
                self.assertEqual(self.request(self.provider_url + path, audio_payload())[0], 404)
            self.assertEqual(self.request(self.provider_url + '/audio/transcriptions', {**audio_payload(), 'model': 'other'})[0], 400)
            self.provider.Handler.audio_requests.extend([self.provider.time.monotonic()] * 6)
            self.assertEqual(self.request(self.provider_url + '/audio/transcriptions', audio_payload())[0], 429)
            upstream.assert_not_called()
        self.provider.Handler.audio_requests.clear()
        for result in ({'text': 'x' * 16001}, {'text': ''}, {'text': 'no', 'audio': 'unexpected'}):
            connection = self.upstream(result)
            with patch.dict(os.environ, {'HERMES_TRANSCRIPTION_ENABLED': '1'}, clear=True), patch.object(self.provider, 'ready', return_value=True), patch.object(self.provider, 'SECRET', Mock(read_text=lambda: 'fixture-private-key')), patch.object(self.provider, 'HTTPSConnection', return_value=connection):
                status, raw = self.request(self.provider_url + '/audio/transcriptions', audio_payload())
            self.assertEqual(status, 502)
            self.assertNotIn(b'unexpected', raw)


if __name__ == '__main__':
    unittest.main()
