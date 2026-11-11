"""Bounded operator policy, isolated from the legacy text-only fallback."""
import importlib.util
import json
import os
import threading
import subprocess
import urllib.request
import urllib.error
from unittest.mock import patch, Mock
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'ops/hermes'))

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ops/hermes' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperatorPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = load('operator_protocol')
        cls.provider = load('operator_provider')

    def test_production_api_uses_only_the_private_operator_bridge(self):
        policy = (ROOT / 'ops/crm.compose.yaml').read_text()
        api = policy.split('\n  api:\n', 1)[1].split('\n  migrate:\n', 1)[0]
        self.assertIn('HERMES_BRIDGE_URL: http://hermes-bridge:8081', api)
        self.assertIn('networks: [app, data]', api)
        self.assertNotIn('ports:', api)
        self.assertNotIn('hermes-openai.key', api)

    def schema(self):
        return {'type': 'function', 'function': {'name': 'jardines_app', 'description': 'Operate app',
                'parameters': {'type': 'object', 'properties': {'action': {'type': 'string',
                'enum': ['crm.workspace']}, 'arguments': {'type': 'object'}},
                'required': ['action', 'arguments'], 'additionalProperties': False}}}

    def payload(self, **extra):
        return json.dumps({'model': 'gpt-6-luna', 'messages': [{'role': 'user', 'content': 'Read workspace'}],
                           'tools': [self.schema()], 'max_tokens': 1024, **extra}).encode()

    def test_canonical_tool_and_tool_result_are_accepted(self):
        result = self.provider.validate(self.payload(messages=[
            {'role': 'user', 'content': 'Read workspace'},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function',
             'function': {'name': 'jardines_app', 'arguments': '{"action":"crm.workspace","arguments":{}}'}}]},
            {'role': 'tool', 'tool_call_id': 'call_1', 'content': '{"result":{"contacts":[]}}'}]))
        self.assertEqual(result['max_completion_tokens'], 1024)
        self.assertEqual(result['reasoning_effort'], 'none')
        self.assertEqual(result['tools'][0]['function']['name'], 'jardines_app')

    def test_rejects_noncanonical_tools_roles_and_unbounded_requests(self):
        wrong = self.schema()
        wrong['function']['name'] = 'terminal'
        cases = [{'tools': [wrong]}, {'tools': []}, {'model': 'other'}, {'max_tokens': 1025},
                 {'stream': True}, {'messages': [{'role': 'tool', 'tool_call_id': 'missing', 'content': '{}'}]},
                 {'messages': [{'role': 'user', 'content': 'x' * 20001}]},
                 {'messages': [{'role': 'user', 'content': 'ok', 'secret': 'no'}]}]
        for case in cases:
            with self.subTest(case=str(case)[:80]), self.assertRaises(ValueError):
                self.provider.validate(self.payload(**case))

    def test_claim_schema_rejects_extra_tools_and_arbitrary_endpoints(self):
        claim = {'run_id': 'run', 'prompt': 'Read workspace', 'skills': [], 'tools': [self.schema()]}
        self.assertEqual(self.protocol.validate_claim(claim)['run_id'], 'run')
        self.assertEqual(self.protocol.validate_claim({**claim, 'skills': [{'name': 'lectura', 'content': 'ó' * 16000}]})['skills'][0]['content'], 'ó' * 16000)
        for key, value in [('tools', [self.schema(), self.schema()]), ('prompt', 'x' * 4097),
                           ('skills', [{'name': 'bad', 'content': 'x' * 16001}])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.protocol.validate_claim({**claim, key: value})
        for url in ['https://evil.example', 'http://api:8000/path', 'http://user@api:8000',
                    'http://169.254.169.254', 'http://localhost:8000?x=1']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.protocol.internal_endpoint(url, 'api', 8000)

    def test_token_is_opaque_256_bit_and_not_prompt_text(self):
        self.assertTrue(self.protocol.valid_token('a' * 43))
        self.assertTrue(self.protocol.valid_token('f' * 64))
        for token in ['', 'a' * 32, 'x' * 1000, 'a b' * 22, {'token': 'abc'}]:
            self.assertFalse(self.protocol.valid_token(token))


class OperatorBoundaryTests(unittest.TestCase):
    def test_broker_budget_and_action_scope(self):
        operator = load('operator')
        broker = Mock()
        broker.request.return_value = {'result': {'ok': True}}
        run = operator.BrokerRun(broker, 'f' * 64, {'tools': [OperatorPolicyTests().schema()]})
        self.assertIn('error', json.loads(run.dispatch({'action': 'terminal', 'arguments': {}})))
        self.assertEqual(broker.request.call_count, 0)
        threads = [threading.Thread(target=run.dispatch, args=({'action': 'crm.workspace', 'arguments': {}},)) for _ in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(broker.request.call_count, 12)
        self.assertEqual(len({call.args[1]['call_id'] for call in broker.request.call_args_list}), 12)

    def test_runtime_guard_denies_process_and_other_network(self):
        path = str(ROOT / 'ops/hermes/operator.py')
        code = f"""
import importlib.util, sys, socket, subprocess
sys.path.insert(0, {str(ROOT / 'ops/hermes')!r})
spec = importlib.util.spec_from_file_location('hermes_operator', {path!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.guarded_runtime({{('192.0.2.1', 8080)}})
for action in [lambda: subprocess.run(['true']),
               lambda: socket.create_connection(('127.0.0.1', 5432)),
               lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'no', ('127.0.0.1', 9))]:
    try:
        action()
    except PermissionError:
        continue
    raise AssertionError('Guard failed')
print('guard_ok')
"""
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'guard_ok')

    def test_bridge_health_checks_readiness_and_rejects_caller_urls(self):
        operator = load('operator')
        operator.Handler.provider = Mock()
        operator.Handler.provider.request.return_value = {'available': False, 'configured': False, 'model': 'gpt-6-luna'}
        operator.Handler.runtime = (object(), object())
        server = operator.HTTPServer(('127.0.0.1', 0), operator.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:' + str(server.server_port)
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(url + '/health')
        self.assertEqual(context.exception.code, 503)
        self.assertFalse(json.loads(context.exception.read())['available'])
        context.exception.close()
        operator.Handler.provider.request.return_value = {'available': True, 'configured': True, 'model': 'gpt-6-luna'}
        with urllib.request.urlopen(url + '/health') as response:
            self.assertTrue(json.loads(response.read())['available'])
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(urllib.request.Request(url + '/run', data=json.dumps({'token': 'f' * 64, 'url': 'https://evil.example'}).encode()))
        self.assertEqual(context.exception.code, 400)
        context.exception.close()


class OperatorHTTPTests(unittest.TestCase):
    def setUp(self):
        self.provider = load('operator_provider')
        self.provider.Handler.requests.clear()
        self.provider.Handler.runs.clear()
        self.server = self.provider.HTTPServer(('127.0.0.1', 0), self.provider.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, data):
        request = urllib.request.Request(self.url + '/v1/chat/completions', data=data,
            headers={'Authorization': 'Bearer ' + 'a' * 32, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            body = error.read()
            error.close()
            return error.code, body

    def test_missing_credential_is_unavailable_without_upstream(self):
        with patch.object(self.provider, 'ready', return_value=False), patch.object(self.provider, 'HTTPSConnection') as upstream:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(self.url + '/health')
            self.assertEqual(context.exception.code, 503)
            self.assertFalse(json.loads(context.exception.read())['available'])
            context.exception.close()
            status, _ = self.post(OperatorPolicyTests().payload())
            self.assertEqual(status, 503)
            upstream.assert_not_called()

    def test_budget_fixed_upstream_and_secret_redaction(self):
        reply = Mock(status=401)
        reply.read.return_value = b'{"error":"sensitive"}'
        connection = Mock()
        connection.getresponse.return_value = reply
        with patch.object(self.provider, 'ready', return_value=True), patch.object(self.provider, 'HTTPSConnection', return_value=connection) as factory, patch.object(self.provider.Path, 'read_text', return_value='fixture-private-key'):
            for _ in range(4):
                status, body = self.post(OperatorPolicyTests().payload())
                self.assertEqual(status, 502)
                self.assertNotIn(b'sensitive', body)
                self.assertNotIn(b'fixture-private-key', body)
            status, _ = self.post(OperatorPolicyTests().payload())
            self.assertEqual(status, 429)
        self.assertEqual(factory.call_count, 4)
        factory.assert_called_with('api.openai.com', timeout=30)
        self.assertEqual(connection.request.call_args.args, ('POST', '/v1/chat/completions'))
        self.assertEqual(connection.request.call_args.kwargs['headers']['Authorization'], 'Bearer fixture-private-key')

    def test_invalid_tools_never_reach_upstream(self):
        with patch.object(self.provider, 'HTTPSConnection') as upstream:
            status, _ = self.post(OperatorPolicyTests().payload(tools=[]))
            self.assertEqual(status, 400)
            upstream.assert_not_called()


@unittest.skipUnless(os.environ.get('HERMES_REAL_INTEGRATION') == '1', 'Requires explicitly pinned Hermes container fixture')
class RealPinnedHermesTests(unittest.TestCase):
    def test_real_agent_tool_dispatch_broker_result_and_final_answer(self):
        import contextlib
        import io
        from http.server import BaseHTTPRequestHandler, HTTPServer
        operator = load('operator')
        provider = load('operator_provider')
        token = 'f' * 64
        events, upstream_payloads, denials = [], [], []
        validate = provider.validate
        def observed_validate(raw):
            try:
                return validate(raw)
            except Exception as error:
                denials.append((str(error), json.loads(raw)))
                raise
        provider.validate = observed_validate
        schema = OperatorPolicyTests().schema()

        class Broker(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                self.server.testcase.assertEqual(self.headers.get('Authorization'), 'Bearer ' + token)
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                events.append((self.path, body))
                if self.path.endswith('/claim'):
                    result = {'run_id': 'fixture-run', 'prompt': 'Consulta el espacio de trabajo con la herramienta.',
                              'tools': [schema], 'skills': [{'name': 'fixture', 'content': 'Use crm.workspace to read.'}]}
                elif self.path.endswith('/call'):
                    self.server.testcase.assertEqual(body['action'], 'crm.workspace')
                    result = {'result': {'fixture_marker': 'verified-broker-result'}}
                elif self.path.endswith('/finish'):
                    result = {'run_id': 'fixture-run', 'reply': body['reply'], 'results': [{'fixture_marker': 'verified-broker-result'}], 'proposals': []}
                else:
                    raise AssertionError('Unexpected broker route')
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        class Upstream:
            def __init__(self, host, timeout):
                self_host = host
                assert self_host == 'api.openai.com' and timeout == 30
            def request(self, method, path, body, headers):
                assert method == 'POST' and path == '/v1/chat/completions'
                assert headers['Authorization'] == 'Bearer fixture-not-a-real-key'
                upstream_payloads.append(json.loads(body))
            def getresponse(self):
                if len(upstream_payloads) == 1:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'fixture_call', 'type': 'function',
                        'function': {'name': 'jardines_app', 'arguments': '{"action":"crm.workspace","arguments":{}}'}}]}
                    reason = 'tool_calls'
                else:
                    assert any('verified-broker-result' in msg.get('content', '') for msg in upstream_payloads[-1]['messages'] if msg['role'] == 'tool')
                    message = {'role': 'assistant', 'content': 'Consulta verificada mediante la herramienta de la aplicación.'}
                    reason = 'stop'
                return Mock(status=200, read=lambda *_: json.dumps({'choices': [{'message': message, 'finish_reason': reason}]}).encode())
            def close(self):
                pass

        servers = [HTTPServer(('127.0.0.1', 0), Broker), provider.HTTPServer(('127.0.0.1', 0), provider.Handler)]
        servers[0].testcase = self
        provider.Handler.runs.clear()
        provider.Handler.requests.clear()
        for server in servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        broker = operator.PrivateHTTP('http://127.0.0.1:' + str(servers[0].server_port), 'api', 8000)
        proxy = operator.PrivateHTTP('http://127.0.0.1:' + str(servers[1].server_port), 'operator-provider', 8080)
        with patch.object(provider, 'ready', return_value=True), patch.object(provider, 'HTTPSConnection', Upstream), patch.object(provider, 'SECRET', Mock(read_text=lambda: 'fixture-not-a-real-key')):
            # Restrict read_text patch to provider secret; Hermes must read actual config/source.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                operator.guarded_runtime({(broker.ip, broker.port), (proxy.ip, proxy.port)})
                runtime = operator.prepare_runtime()
                try:
                    result = operator.run_operator(token, broker, proxy, runtime)
                except Exception as error:
                    raise AssertionError('Fixture diagnostics: ' + repr(([reason for reason, _ in denials], len(upstream_payloads), [route for route, _ in events]))) from error
        self.assertEqual([path for path, _ in events], ['/internal/hermes/claim', '/internal/hermes/call', '/internal/hermes/finish'])
        self.assertEqual(len(upstream_payloads), 2)
        self.assertEqual(result['results'][0]['fixture_marker'], 'verified-broker-result')
        self.assertIn('verificada', result['reply'])
        self.assertNotIn(token, json.dumps(upstream_payloads))
        self.assertNotIn('fixture-not-a-real-key', json.dumps(upstream_payloads))
        for path in Path(os.environ['HERMES_HOME']).rglob('*'):
            if path.is_file():
                raw = path.read_bytes()
                self.assertNotIn(b'verified-broker-result', raw, str(path))
                self.assertNotIn(token.encode(), raw, str(path))
                self.assertNotIn('Consulta el espacio'.encode(), raw, str(path))


if __name__ == '__main__':
    unittest.main()
