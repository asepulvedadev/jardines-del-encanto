"""Isolated Retell adapter regression tests; no live vendor calls."""
import importlib.util
import json
import socket
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('retell_gateway', ROOT / 'ops/retell/gateway.py')
gw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gw)


class FakeMCP:
    def __init__(self):
        self.calls = []
        self.drift = False
        self.fail = False
        self.output = {'agents': []}

    def __call__(self, key, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == 'get_api_endpoint_schema':
            schema = gw.input_schema(arguments['endpoint'], strict=False)
            if self.drift:
                schema['required'] = ['unexpected']
            return {'endpoint': arguments['endpoint'], 'input_schema': schema}
        if tool == 'list_api_endpoints':
            return {'endpoints': [{'endpoint': x} for x in gw.REGISTRY] + [{'endpoint': 'futurePaidTool'}]}
        if tool == 'invoke_api_endpoint':
            if self.fail:
                raise TimeoutError('secret_do_not_expose')
            if arguments['endpoint'] == 'getApiKeyInfo':
                return {'org_id': 'org_jardines', 'org_name': 'Jardines', 'api_key_name': 'Jardines', 'api_key': key}
            return self.output
        raise AssertionError(tool)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mcp = FakeMCP()
        self.gateway = gw.Gateway(Path(self.tmp.name) / 'state', self.mcp)
        self.key = 'key_' + 'k' * 36
        self.state = self.gateway.configure({'revision': 0, 'api_key': self.key})

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, endpoint='getAgent', arguments=None):
        args = {'agent_id': 'agent_123'} if arguments is None else arguments
        prepared = self.gateway.prepare({'revision': 1, 'endpoint': endpoint, 'arguments': args})
        return {'revision': 1, 'endpoint': endpoint, 'arguments': args, 'request_id': str(uuid4()),
                'expected_schema_hash': prepared['schema_hash'], 'consent_confirmed': True}

    def error(self, code, fn):
        with self.assertRaises(gw.GatewayError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def test_registry_exact_reviewed112_and_five_multipart_unavailable(self):
        self.assertEqual(len(gw.REGISTRY), 112)
        blocked = [x for x in gw.REGISTRY.values() if not x['available']]
        self.assertEqual(len(blocked), 5)
        for item in blocked:
            self.error('requires_file_adapter', lambda item=item: self.gateway.prepare({'revision': 1,
                'endpoint': item['endpoint'], 'arguments': {}}))

    def test_state_has_no_secret_and_revisions_guard_every_route(self):
        self.assertNotIn(self.key, json.dumps(self.gateway.state()))
        self.error('configuration_changed', lambda: self.gateway.prepare({'revision': 0, 'endpoint': 'getAgent', 'arguments': {'agent_id': 'a'}}))
        self.error('endpoint_unreviewed', lambda: self.gateway.prepare({'revision': 1, 'endpoint': 'futurePaidTool', 'arguments': {}}))

    def test_strict_schema_required_types_extra_and_credentials(self):
        for args in ({}, {'agent_id': 5}, {'agent_id': 'a', 'extra': 'x'}):
            self.error('arguments_invalid', lambda args=args: self.gateway.prepare({'revision': 1, 'endpoint': 'getAgent', 'arguments': args}))
        self.error('sensitive_arguments_denied', lambda: gw.validate_sensitive({'headers': {'Authorization': 'secret'}}))
        for value in ['http://example.com', 'https://user:pass@example.com/hook', 'https://127.0.0.1/hook', 'https://host.local/hook', 'file:///etc/passwd']:
            self.error('unsafe_url', lambda value=value: gw.validate_sensitive({'webhook_url': value}))
        gw.validate_sensitive({'webhook_url': 'https://hooks.example.com/events'})

    def test_composed_schema_accepts_siblings_but_rejects_unknown_fields(self):
        args = {'requestBody': {'response_engine': {'type': 'retell-llm', 'llm_id': 'llm_123'}, 'voice_id': '11labs-Adrian'}}
        self.gateway.prepare({'revision': 1, 'endpoint': 'createAgent', 'arguments': args})
        args['requestBody']['unexpected_field'] = True
        self.error('arguments_invalid', lambda: self.gateway.prepare({'revision': 1, 'endpoint': 'createAgent', 'arguments': args}))

    def test_callback_query_credentials_are_denied_before_proposal(self):
        for name in ['access_token', 'api%5fkey', '%61uth', 'credential', 'key', 'token']:
            args = {'phone_number': '+15551234567', 'requestBody': {'inbound_webhook_url': 'https://hooks.example.com/events?' + name + '=opaque'}}
            self.error('unsafe_url', lambda args=args: self.gateway.prepare({'revision': 1, 'endpoint': 'updatePhoneNumber', 'arguments': args}))
        gw.validate_url('https://hooks.example.com/events?campaign=spring')
        self.assertEqual(gw.safe_output('https://hooks.example.com/events?access_token=opaque'), '[private link redacted]')

    def test_schema_drift_and_frozen_schema_mismatch_do_not_dispatch(self):
        payload = self.payload()
        payload['expected_schema_hash'] = '0' * 64
        self.error('schema_changed', lambda: self.gateway.execute(payload))
        payload = self.payload()
        self.mcp.drift = True
        self.error('schema_changed', lambda: self.gateway.execute(payload))
        self.assertFalse(any(name == 'invoke_api_endpoint' and args['endpoint'] == 'getAgent' for name, args in self.mcp.calls))

    def test_duplicate_reservation_survives_restart_and_uncertain_outcome(self):
        payload = self.payload()
        self.mcp.fail = True
        result = self.gateway.execute(payload)
        self.assertEqual(result['status'], 'external_outcome_unconfirmed')
        self.assertFalse(result['retryable'])
        restarted = gw.Gateway(Path(self.tmp.name) / 'state', self.mcp)
        self.error('request_already_reserved', lambda: restarted.execute(payload))
        count = sum(name == 'invoke_api_endpoint' and args['endpoint'] == 'getAgent' for name, args in self.mcp.calls)
        self.assertEqual(count, 1)
        self.assertNotIn('secret_do_not_expose', json.dumps(result))

    def test_output_redacts_nested_secrets_token_values_and_links(self):
        self.mcp.output = {'agent_id': 'a', 'nested': {'headers': {'Auth': 'SECRET'}, 'access_token': 'TOK',
            'api_key': self.key, 'text': 'hello ' + self.key, 'ice_servers': [{'credential': 'ICE'}]},
            'recording_url': 'https://example.com/audio?token=SECRET'}
        output = json.dumps(self.gateway.execute(self.payload()))
        for secret in ['SECRET', 'TOK', 'ICE', self.key]:
            self.assertNotIn(secret, output)
        self.assertIn('agent_id', output)

    def test_web_session_claim_once_expires_and_never_persists_token(self):
        self.mcp.output = {'call_id': 'call_123', 'access_token': 'web_token_ABC'}
        payload = self.payload('createWebCall', {'requestBody': {'agent_id': 'agent_123'}})
        output = self.gateway.execute(payload)
        self.assertEqual(output['status'], 'ready')
        self.assertNotIn('web_token_ABC', json.dumps(output))
        self.assertNotIn('web_token_ABC', (Path(self.tmp.name) / 'state/state.json').read_text())
        self.assertEqual(self.gateway.claim(payload['request_id'], {'revision': 1}), {'access_token': 'web_token_ABC'})
        self.error('session_unavailable', lambda: self.gateway.claim(payload['request_id'], {'revision': 1}))
        payload = self.payload('createWebCall', {'requestBody': {'agent_id': 'agent_123'}})
        self.gateway.execute(payload)
        with patch.object(gw.time, 'monotonic', return_value=10**20):
            self.error('session_unavailable', lambda: self.gateway.claim(payload['request_id'], {'revision': 1}))

    def test_paid_consent_and_disconnect_clear_ephemeral_tokens(self):
        payload = self.payload('createWebCall', {'requestBody': {'agent_id': 'agent_123'}})
        payload['consent_confirmed'] = False
        self.error('consent_required', lambda: self.gateway.execute(payload))
        self.mcp.output = {'call_id': 'c', 'access_token': 'token_123'}
        payload['consent_confirmed'] = True
        self.gateway.execute(payload)
        self.gateway.disconnect({'revision': 1})
        self.error('configuration_changed', lambda: self.gateway.claim(payload['request_id'], {'revision': 1}))

    def test_catalog_new_tools_metadata_only(self):
        value = self.gateway.catalog({'revision': 1})
        self.assertEqual(value['new_operations'][0]['endpoint'], 'futurePaidTool')
        self.assertFalse(value['new_operations'][0]['available'])


    def test_schema_pin_valid_and_actual_get_agent_required(self):
        for schema in gw.SCHEMAS.values():
            gw.Draft202012Validator.check_schema(schema)
        self.assertEqual(gw.SCHEMAS['getAgent']['required'], ['agent_id'])
        self.assertIn('requestBody', gw.SCHEMAS['createWebCall']['properties'])

    def test_schema_field_named_description_still_detects_drift(self):
        pinned = {'type': 'object', 'properties': {'description': {'type': 'string'}}}
        drifted = {'type': 'object', 'properties': {'description': {'type': 'integer'}}}
        self.assertNotEqual(gw.semantic_schema(pinned), gw.semantic_schema(drifted))
        self.assertEqual(gw.semantic_schema({'type': 'string', 'description': 'old'}),
                         gw.semantic_schema({'type': 'string', 'description': 'new'}))

    def test_configure_rejects_fake_error_dictionary_and_saves_no_key(self):
        fresh = gw.Gateway(Path(self.tmp.name) / 'invalid', lambda *_args: {'status': 401})
        self.error('provider_verification_failed', lambda: fresh.configure({'revision': 0, 'api_key': self.key}))
        self.assertFalse(fresh.state()['configured'])

    def test_revision_change_rejects_old_schema_and_session_payload(self):
        payload = self.payload()
        self.gateway.configure({'revision': 1, 'defaults': {'agent_id': 'another'}})
        self.error('configuration_changed', lambda: self.gateway.execute(payload))
        self.error('configuration_changed', lambda: self.gateway.schema({'revision': 1, 'endpoint': 'getAgent'}))

    def test_all_reads_reserve_and_duplicate_success_does_not_invoke(self):
        payload = self.payload()
        self.assertEqual(self.gateway.execute(payload)['status'], 'completed')
        self.error('request_already_reserved', lambda: self.gateway.execute(payload))
        self.gateway.disconnect({'revision': 1})
        self.gateway.configure({'revision': 2, 'api_key': self.key})
        payload['revision'] = 3
        self.error('request_already_reserved', lambda: self.gateway.execute(payload))

    def test_concurrent_same_uuid_dispatches_only_once(self):
        payload = self.payload()
        results = []
        def run():
            try:
                results.append(self.gateway.execute(payload)['status'])
            except gw.GatewayError as exc:
                results.append(exc.code)
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertCountEqual(results, ['completed', 'request_already_reserved'])

    def test_input_tokens_and_arbitrary_key_output_redacted(self):
        self.error('sensitive_arguments_denied', lambda: gw.validate_sensitive({'token': 'x'}))
        self.error('sensitive_arguments_denied', lambda: gw.validate_sensitive({'auth_config': {'type': 'oauth'}}))
        output = gw.safe_output({self.key: 'x', 'url': 'wss://user:secret@example.com/path'}, secrets=(self.key,))
        self.assertNotIn(self.key, json.dumps(output))
        self.assertNotIn('user:secret', json.dumps(output))

    def test_private_file_modes_and_reservation_capacity_fail_closed(self):
        path = Path(self.tmp.name) / 'state/state.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        with patch.object(gw, 'MAX_RESERVATIONS', 0):
            self.error('reservation_capacity_reached', lambda: self.gateway.execute(self.payload()))
        path.chmod(0o644)
        self.error('configuration_unavailable', lambda: self.gateway.state())

    def test_response_truncation_and_null_delete_are_safe(self):
        self.mcp.output = {'text': 'z' * 100000, 'rows': list(range(500))}
        out = self.gateway.execute(self.payload())
        self.assertLess(len(json.dumps(out)), 20000)
        self.mcp.output = None
        out = self.gateway.execute(self.payload('deleteAgent', {'agent_id': 'a'}))
        self.assertEqual(out, {'status': 'completed', 'endpoint': 'deleteAgent', 'data': None})


class TransportTests(unittest.TestCase):
    def test_json_and_sse_parse_limits_wrong_ids_error_duplicate_fields(self):
        good = {'jsonrpc': '2.0', 'id': 7, 'result': {'ok': True}}
        self.assertEqual(gw.parse_rpc(json.dumps(good).encode(), 'application/json', 7), {'ok': True})
        wire = ('event: message\ndata: ' + json.dumps(good) + '\n\n').encode()
        self.assertEqual(gw.parse_rpc(wire, 'text/event-stream', 7), {'ok': True})
        for raw in [b'{"jsonrpc":"2.0","id":7,"id":7,"result":{}}', b'{}', b'[]', b'data: {}\n\n']:
            with self.assertRaises((gw.GatewayError, ValueError)):
                gw.parse_rpc(raw, 'application/json', 7)
        with self.assertRaises(gw.GatewayError):
            gw.parse_rpc(json.dumps(good).encode(), 'application/json', 6)

    def test_tool_error_wrapper_and_plain_null(self):
        with self.assertRaises(gw.GatewayError):
            gw.tool_value({'isError': True, 'content': [{'type': 'text', 'text': 'vendor_secret'}]})
        self.assertIsNone(gw.tool_value({'content': [{'type': 'text', 'text': 'null'}]}))
        self.assertEqual(gw.tool_value({'structuredContent': {'ok': True}}), {'ok': True})

    def test_duplicate_sse_result_and_secret_session_header_rejected(self):
        rpc = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {}})
        with self.assertRaises(gw.GatewayError):
            gw.parse_rpc(('data: ' + rpc + '\n\ndata: ' + rpc + '\n\n').encode(), 'text/event-stream', 1)
        with self.assertRaises(gw.GatewayError):
            gw.checked_response(200, 'text/plain', 'identity', None)
        with self.assertRaises(gw.GatewayError):
            gw.checked_response(200, 'application/json', 'gzip', None)
        with self.assertRaises(gw.GatewayError):
            gw.checked_response(200, 'application/json', 'identity', str(gw.MAX_JSON + 1))

    def test_private_dns_and_redirects_rejected(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 443))]
        with patch.object(gw.socket, 'getaddrinfo', return_value=answers), self.assertRaises(gw.GatewayError):
            gw.vendor_socket(gw.time.monotonic() + 3)
        class Reply:
            status = 302
            def getheader(self, name, default=None): return default
        class Conn:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Reply()
            def close(self): pass
        with patch.object(gw, 'HTTPSConnection', Conn), self.assertRaises(gw.GatewayError):
            gw.https_rpc('k'*30, {'id': 1})

    def test_http_wrong_auth_no_routes_reached(self):
        tmp = tempfile.TemporaryDirectory()
        token = Path(tmp.name) / 'token'
        token.write_text('a' * 48)
        token.chmod(0o600)
        handler = type('TestHandler', (gw.Handler,), {'token_file': str(token), 'gateway': None})
        server = gw.GatewayServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            conn.request('GET', '/state', headers={'Authorization': 'Bearer wrong'})
            result = conn.getresponse()
            self.assertEqual(result.status, 401)
            self.assertNotIn('a' * 48, result.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
