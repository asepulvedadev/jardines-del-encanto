"""Full editor snapshots through a fake MCP transport; no provider calls."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('retell_editor_gateway', ROOT / 'ops/retell/gateway.py')
gw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gw)


class EditorGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = {'llm_id': 'llm_fixture', 'version': 7, 'general_prompt': 'Complete prompt. ' * 400, 'begin_message': None}
        self.calls = []
        self.key = 'key_' + 'k' * 36
        def transport(key, tool, args):
            self.calls.append((tool, args))
            if tool == 'get_api_endpoint_schema':
                return {'endpoint': args['endpoint'], 'input_schema': gw.input_schema(args['endpoint'], strict=False)}
            if args['endpoint'] == 'getApiKeyInfo':
                return {'org_id': 'org_fixture', 'org_name': 'Fixture'}
            return self.output
        self.gateway = gw.Gateway(Path(self.tmp.name) / 'state', transport)
        self.gateway.configure({'revision': 0, 'api_key': self.key})

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, endpoint='getRetellLLM', args=None):
        arguments = args if args is not None else {'llm_id': 'llm_fixture', 'version': 7}
        value = self.gateway.prepare({'revision': 1, 'endpoint': endpoint, 'arguments': arguments})
        return {'revision': 1, 'endpoint': endpoint, 'arguments': arguments, 'request_id': str(uuid4()), 'expected_schema_hash': value['schema_hash'], 'consent_confirmed': False}

    def test_full_prompt_exact_and_null_absent_fields_are_explicitly_complete(self):
        result = self.gateway.editor_read(self.payload())
        self.assertEqual(result['data']['general_prompt'], self.output['general_prompt'])
        self.assertIsNone(result['data']['begin_message'])
        self.assertIn('general_prompt', result['editor']['complete_fields'])
        self.assertIn('general_tools', result['editor']['complete_fields'])
        self.assertNotIn('general_tools', result['data'])

    def test_private_root_is_blocked_entirely_without_partial_redaction(self):
        self.output['general_tools'] = [{'type': 'custom', 'name': 'private', 'url': 'https://example.com/hook', 'headers': {'Authorization': 'private'}}]
        self.output['default_dynamic_variables'] = {'api_key': 'private'}
        result = self.gateway.editor_read(self.payload())
        for key in ('general_tools', 'default_dynamic_variables'):
            self.assertNotIn(key, result['data'])
            self.assertNotIn(key, result['editor']['complete_fields'])
            self.assertIn(key, result['editor']['blocked_fields'])
        self.assertNotIn('private', json.dumps(result['data']))

    def test_actual_provider_key_and_credential_urls_block_the_whole_field(self):
        for value in (self.key, ' https://user:password@example.com/hook', chr(10) + 'https://example.com/hook?api_key=opaque', chr(9) + 'https://user:password@example.com/hook', '//user:password@example.com/hook', 'https:user:password@example.com/hook', 'https://example.com/hook?X-Amz-Signature=opaque', 'URL in prompt: https://user:password@example.com/hook', 'https://example.com/hook?authorization=opaque', 'key_' + 's' * 25, 'bad' + chr(0) + 'text'):
            self.output['general_prompt'] = value
            result = self.gateway.editor_read(self.payload())
            self.assertNotIn('general_prompt', result['data'])
            self.assertIn('general_prompt', result['editor']['blocked_fields'])
            self.assertNotIn(value, json.dumps(result))

    def test_prototype_sensitive_keys_block_complete_dictionary_root(self):
        for key in ('__proto__', 'constructor', 'prototype', 'Constructor', '__Proto__'):
            self.output['default_dynamic_variables'] = {key: 'unsafe'}
            result = self.gateway.editor_read(self.payload())
            self.assertNotIn('default_dynamic_variables', result['data'])
            self.assertEqual(result['editor']['blocked_fields']['default_dynamic_variables'], 'editor_field_private')

    def test_editor_protocol_disallows_extra_mode_flags_and_unreviewed_endpoints(self):
        payload = self.payload()
        with self.assertRaises(gw.GatewayError):
            self.gateway.editor_read({**payload, 'projection': 'arbitrary'})
        for endpoint in ('listAgents', 'createAgent', 'getCall'):
            with self.assertRaises(gw.GatewayError):
                self.gateway.editor_read({**payload, 'endpoint': endpoint})

    def test_public_urls_with_nonprivate_queries_are_preserved_exactly(self):
        value = 'Read https://example.com/hook?campaign=jardines for context.'
        self.output['general_prompt'] = value
        result = self.gateway.editor_read(self.payload())
        self.assertEqual(result['data']['general_prompt'], value)

    def test_unknown_nested_shape_and_oversized_values_are_never_prefilled(self):
        self.output = {'agent_id': 'agent_fixture', 'version': 2, 'response_engine': {'type': 'retell-llm', 'llm_id': 'llm_fixture', 'unreviewed': True}, 'agent_name': 'Safe', 'boosted_keywords': ['x'] * 101, 'unknown_provider_private': 'hidden'}
        result = self.gateway.editor_read(self.payload('getAgent', {'agent_id': 'agent_fixture'}))
        self.assertEqual(result['data']['agent_name'], 'Safe')
        for key in ('response_engine', 'boosted_keywords'):
            self.assertIn(key, result['editor']['blocked_fields'])
            self.assertNotIn(key, result['data'])
        self.assertNotIn('unknown_provider_private', json.dumps(result))
        self.output = {'llm_id': 'llm_fixture', 'version': 7, 'general_prompt': 'x' * 16001}
        result = self.gateway.editor_read(self.payload())
        self.assertNotIn('general_prompt', result['data'])

    def test_wrong_identity_version_and_non_read_endpoints_fail_closed(self):
        for row in ({'llm_id': 'other', 'version': 7}, {'llm_id': 'llm_fixture', 'version': 8}):
            self.output = row
            with self.assertRaises(gw.GatewayError):
                self.gateway.editor_read(self.payload())
        with self.assertRaises(gw.GatewayError):
            self.gateway.editor_read({'endpoint': 'createAgent'})

    def test_normal_execute_remains_partial_and_editor_reservations_are_once_only(self):
        normal = self.gateway.execute(self.payload())
        self.assertLess(len(normal['data']['general_prompt']), len(self.output['general_prompt']))
        payload = self.payload()
        result = self.gateway.editor_read(payload)
        self.assertEqual(result['data']['general_prompt'], self.output['general_prompt'])
        with self.assertRaises(gw.GatewayError):
            self.gateway.editor_read(payload)

    def test_total_json_is_bounded_without_truncating_accepted_roots(self):
        self.output = {'llm_id': 'llm_fixture', 'version': 7, 'general_prompt': 'ñ' * 16000, 'begin_message': '漢' * 16000, 'voice_prompt': 'z' * 16000}
        result = self.gateway.editor_read(self.payload())
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 96 * 1024)
        for key, value in result['data'].items():
            self.assertEqual(value, self.output[key])
