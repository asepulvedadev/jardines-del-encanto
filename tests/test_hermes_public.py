"""Public Hermes has an independent, bounded, tool-free customer boundary."""
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'ops/hermes'))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ops/hermes' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(**extra):
    return {'messages': [{'role': 'user', 'content': '¿Dónde queda el proyecto?'}],
            'instructions': 'Contesta brevemente.', 'knowledge': 'Proyecto en Acacías.', **extra}


def completion(**extra):
    return {'model': 'gpt-6-luna', 'messages': [
        {'role': 'system', 'content': 'SDK context MUST NOT reach upstream'},
        {'role': 'user', 'content': json.dumps(payload(), ensure_ascii=False)}],
        'max_tokens': 512, **extra}


class PublicPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load('operator_public')
        cls.provider = load('operator_provider')

    def test_history_and_server_selected_reference_bounds(self):
        self.assertEqual(self.policy.validate_public(payload()), payload())
        invalid = [payload(messages=[]), payload(messages=[{'role': 'assistant', 'content': 'no'}]),
                   payload(messages=[{'role': 'system', 'content': 'control'}]),
                   payload(messages=[{'role': 'user', 'content': 'x', 'tools': []}]),
                   payload(messages=[{'role': 'user', 'content': 'x' * 2001}]),
                   payload(messages=[{'role': 'user', 'content': 'x'}] * 9),
                   payload(instructions='x' * 2001), payload(knowledge='x' * 4001),
                   payload(unknown=True), payload(messages=[{'role': 'user', 'content': ''}]),
                   payload(messages=[{'role': 'user', 'content': '😀' * 2000}] * 4)]
        for item in invalid:
            with self.subTest(item=str(item)[:100]), self.assertRaises(ValueError):
                self.policy.validate_public(item)

    def test_provider_replaces_system_and_accepts_only_one_json_customer_prompt(self):
        value = self.policy.validate_completion(json.dumps(completion()).encode())
        self.assertEqual(value['messages'][0], {'role': 'system', 'content': self.policy.PUBLIC_SYSTEM})
        self.assertEqual(json.loads(value['messages'][1]['content']), payload())
        self.assertEqual(value['max_completion_tokens'], 512)
        self.assertNotIn('SDK context', json.dumps(value))
        self.assertNotIn('tools', value)
        invalid = [{'tools': []}, {'tools': [{'type': 'function'}]}, {'tool_choice': 'none'},
                   {'functions': []}, {'function_call': 'none'}, {'stream': True},
                   {'model': 'other'}, {'max_tokens': 513}, {'max_tokens': True},
                   {'response_format': {}}, {'n': 2}, {'reasoning_effort': 'high'},
                   {'parallel_tool_calls': True}, {'max_completion_tokens': 512},
                   {'messages': [{'role': 'user', 'content': 'not JSON'}]},
                   {'messages': [{'role': 'user', 'content': json.dumps(payload())},
                                 {'role': 'assistant', 'content': 'untrusted'}]}]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.policy.validate_completion(json.dumps(completion(**item)).encode())

    def test_old_operator_still_rejects_empty_tools(self):
        with self.assertRaises(ValueError):
            self.provider.validate(json.dumps(completion(tools=[])).encode())

    def test_upstream_text_only_and_bounded(self):
        base = {'choices': [{'message': {'role': 'assistant', 'content': 'Hola.'}, 'finish_reason': 'stop'}]}
        self.assertEqual(self.policy.public_model_reply(base), 'Hola.')
        for extra in ({'tool_calls': [{'id': 'x'}]}, {'refusal': 'denied'}, {'audio': {}},
                      {'content': 'x' * 1501}, {'content': ''}):
            bad = {'choices': [{'message': {**base['choices'][0]['message'], **extra}, 'finish_reason': 'stop'}]}
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.policy.public_model_reply(bad)
        for bad in ({**base, 'private': 'secret'}, {**base, 'choices': base['choices'] * 2},
                    {'choices': [{**base['choices'][0], 'finish_reason': 'tool_calls'}]}):
            with self.assertRaises(ValueError):
                self.policy.public_model_reply(bad)

    def test_public_deadline_escapes_sdk_errors_and_bounds_cleanup(self):
        source = """
import sys, time
from unittest.mock import Mock, patch
sys.path.insert(0, {path!r})
from operator_public import public_deadline
from operator_audio import AudioDeadline
try:
    with public_deadline(0.03):
        try:
            time.sleep(1)
        except Exception:
            raise AssertionError('SDK swallowed deadline')
except AudioDeadline:
    print('bounded')
with patch('operator_public.os._exit', side_effect=SystemExit(124)) as terminate:
    try:
        with public_deadline(0.03):
            try:
                time.sleep(1)
            finally:
                # Simulate stalled SDK cleanup: observe the armed five-second failsafe
                # without making the regression test sleep for five seconds.
                import signal
                remaining, _ = signal.getitimer(signal.ITIMER_REAL)
                assert 0 < remaining <= 5
                signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
    except SystemExit as error:
        assert error.code == 124
    terminate.assert_called_once_with(124)
""".format(path=str(ROOT / 'ops/hermes'))
        result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'bounded')

    def test_compose_mounts_policy_without_new_credential_boundary(self):
        policy = (ROOT / 'ops/hermes/operator.compose.yaml').read_text()
        self.assertEqual(policy.count('./operator_public.py:/policy/operator_public.py:ro'), 2)
        bridge = policy.split('\n  hermes-bridge:\n')[1].split('\nnetworks:')[0]
        self.assertNotIn('secrets:', bridge)
        self.assertIn('networks: [operator, application]', bridge)


class PublicRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.operator = load('operator')

    def test_runtime_is_tool_free_single_attempt_and_registry_untouched(self):
        previous_client = Mock()
        agent = Mock(tools=[], client=previous_client)
        agent.run_conversation.return_value = {'final_response': 'Soy Sara, asistente virtual.'}
        runtime = (Mock(return_value=agent), Mock())
        provider = Mock(ip='192.0.2.2', port=8080)
        fake_httpx = Mock()
        with patch.dict(sys.modules, {'httpx': fake_httpx}):
            result = self.operator.run_public_reply(payload(), provider, runtime)
        self.assertEqual(result, {'ok': True, 'response': 'Soy Sara, asistente virtual.',
                                  'tools': 0, 'model': 'gpt-6-luna'})
        kwargs = runtime[0].call_args.kwargs
        self.assertEqual(kwargs['base_url'], 'http://192.0.2.2:8080/public/v1')
        self.assertEqual(kwargs['enabled_toolsets'], [])
        self.assertEqual(kwargs['max_iterations'], 1)
        self.assertEqual(kwargs['max_tokens'], 512)
        for key in ('skip_memory', 'skip_context_files', 'skip_background_review'):
            self.assertIs(kwargs[key], True)
        self.assertEqual(kwargs['fallback_model'], {})
        self.assertIs(kwargs['save_trajectories'], False)
        runtime[1].register.assert_not_called()
        runtime[1].deregister.assert_not_called()
        self.assertEqual(json.loads(agent.run_conversation.call_args.args[0]), payload())
        self.assertEqual(set(agent.run_conversation.call_args.kwargs), {'system_message'})
        self.assertEqual(agent._api_max_retries, 1)
        self.assertEqual(agent._auto_recovery_cycles, 0)
        self.assertTrue(agent._persist_disabled)
        previous_client.with_options.assert_called_once()
        self.assertEqual(previous_client.with_options.call_args.kwargs['max_retries'], 0)
        agent.close.assert_called_once()

    def test_contaminated_tools_and_invalid_results_fail_closed(self):
        for tools, result in [([{'function': {'name': 'jardines_app'}}], {'final_response': 'No'}),
                              ([], {'failed': True, 'final_response': 'No'}),
                              ([], {'final_response': 'x' * 1501}), ([], {'final_response': ''})]:
            agent = Mock(tools=tools)
            agent.run_conversation.return_value = result
            with self.subTest(tools=tools, result=str(result)[:60]), patch.dict(sys.modules, {'httpx': Mock()}), self.assertRaises((ValueError, RuntimeError)):
                self.operator.run_public_reply(payload(), Mock(ip='192.0.2.2', port=8080), (Mock(return_value=agent), Mock()))
            agent.close.assert_called_once()
            if tools:
                agent.run_conversation.assert_not_called()

    def test_private_http_remains_fixed_path_only(self):
        with patch.object(self.operator.socket, 'gethostbyname', return_value='192.0.2.2'), patch.object(self.operator, 'HTTPConnection') as connection:
            client = self.operator.PrivateHTTP('http://operator-provider:8080', 'operator-provider', 8080)
            for path in ['/public/v1/chat/completions', '/public-reply', '/v1/chat/completions', '/admin']:
                with self.assertRaises(ValueError):
                    client.request(path, payload())
            connection.assert_not_called()


class PublicHTTPTests(unittest.TestCase):
    def start(self, module):
        server = module.HTTPServer(('127.0.0.1', 0), module.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:' + str(server.server_port)

    def post(self, url, body, token='a' * 32):
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            raw = json.loads(error.read())
            error.close()
            return error.code, raw

    def test_bridge_public_route_bounds_readiness_and_sanitized_failure(self):
        operator = load('operator')
        operator.Handler.provider = Mock()
        operator.Handler.provider.request.return_value = {'available': True, 'configured': True,
            'public_reply_available': True, 'model': 'gpt-6-luna'}
        operator.Handler.runtime = (Mock(), Mock())
        operator.Handler.broker = Mock()
        url = self.start(operator)
        with patch.object(operator, 'run_public_reply', return_value={'ok': True, 'response': 'Hola.', 'tools': 0, 'model': 'gpt-6-luna'}) as run:
            self.assertEqual(self.post(url + '/public-reply', payload())[0], 200)
            self.assertEqual(self.post(url + '/public-reply', payload(tools=[]))[0], 400)
            self.assertEqual(run.call_count, 1)
            with urllib.request.urlopen(url + '/health') as response:
                self.assertTrue(json.loads(response.read())['public_reply_available'])
            operator.Handler.provider.request.return_value['public_reply_available'] = False
            self.assertEqual(self.post(url + '/public-reply', payload())[0], 503)
        operator.Handler.broker.request.assert_not_called()
        operator.Handler.provider.request.return_value['public_reply_available'] = True
        with patch.object(operator, 'run_public_reply', side_effect=RuntimeError('PRIVATE KEY')):
            status, body = self.post(url + '/public-reply', payload())
        self.assertEqual(status, 502)
        self.assertNotIn('PRIVATE KEY', json.dumps(body))

    def test_provider_fixed_upstream_single_invocation_and_separate_rate_budget(self):
        provider = load('operator_provider')
        provider.Handler.public_requests.clear()
        provider.Handler.public_runs.clear()
        url = self.start(provider) + '/public/v1/chat/completions'
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200, read=lambda *_: json.dumps({'choices': [
            {'message': {'role': 'assistant', 'content': 'Hola.', 'refusal': None, 'annotations': []}, 'finish_reason': 'stop'}]}).encode())
        with patch.object(provider, 'ready', return_value=True), patch.object(provider, 'HTTPSConnection', return_value=connection) as upstream, patch.object(provider, 'SECRET', Mock(read_text=lambda: 'fixture-secret')):
            self.assertEqual(self.post(url, completion(tools=[]))[0], 400)
            upstream.assert_not_called()
            for index in range(6):
                self.assertEqual(self.post(url, completion(), token=f'{index:032x}')[0], 200)
            self.assertEqual(self.post(url, completion(), token='0' * 32)[0], 429)
            self.assertEqual(self.post(url, completion(), token='f' * 32)[0], 429)
            self.assertEqual(upstream.call_count, 6)
            upstream.assert_called_with('api.openai.com', timeout=30)
            args = connection.request.call_args
            self.assertEqual(args.args, ('POST', '/v1/chat/completions'))
            forwarded = json.loads(args.kwargs['body'])
            self.assertNotIn('SDK context', json.dumps(forwarded))
            self.assertNotIn('tools', forwarded)

    def test_provider_rejects_upstream_tools_without_leaking_or_retrying(self):
        provider = load('operator_provider')
        provider.Handler.public_requests.clear()
        provider.Handler.public_runs.clear()
        url = self.start(provider) + '/public/v1/chat/completions'
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200, read=lambda *_: json.dumps({'choices': [{
            'message': {'role': 'assistant', 'content': 'PRIVATE', 'tool_calls': [{'id': 'x'}]},
            'finish_reason': 'tool_calls'}]}).encode())
        with patch.object(provider, 'ready', return_value=True), patch.object(provider, 'HTTPSConnection', return_value=connection) as upstream, patch.object(provider, 'SECRET', Mock(read_text=lambda: 'fixture-secret')):
            status, body = self.post(url, completion())
            self.assertEqual(status, 502)
            self.assertNotIn('PRIVATE', json.dumps(body))
            self.assertEqual(self.post(url, completion())[0], 429)
            upstream.assert_called_once()


if __name__ == '__main__':
    unittest.main()
