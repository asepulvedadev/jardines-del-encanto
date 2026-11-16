"""Offline policy and bootstrap tests: no real API or database mutations."""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('analytics_bootstrap', ROOT / 'ops/analytics/bootstrap.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnalyticsOpsTests(unittest.TestCase):
    def test_private_prepare_is_stable_and_rejects_unsafe_permissions(self):
        m = load()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'secrets'
            state = m.prepare(directory)
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            self.assertEqual(m.prepare(directory), state)
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for p in directory.iterdir():
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertNotIn('UMAMI_API_KEY', (directory / 'collector.env').read_text())
            os.chmod(directory / 'state.json', 0o644)
            with self.assertRaises(ValueError):
                m.prepare(directory)

    def test_db_env_recovery_keeps_existing_password_and_other_files(self):
        m = load()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'secrets'
            m.prepare(directory)
            (directory / 'db.env').unlink()
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            m.prepare(directory)
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir() if p.name != 'db.env'})
            self.assertEqual((directory / 'db.env').read_text(),
                             'POSTGRES_PASSWORD=' + (directory / 'db_password').read_text())
            self.assertEqual(stat.S_IMODE((directory / 'db.env').stat().st_mode), 0o600)

    def test_default_password_is_rotated_before_any_creation(self):
        m = load()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'secrets'
            state = m.prepare(directory)
            api = FakeApi(state)
            original = api.call
            attempts = []
            def initial_login(method, path, payload=None, **kwargs):
                attempts.append((method, path, payload))
                if len(attempts) == 1:
                    raise m.ApiError(401)
                if len(attempts) == 2:
                    return {'token': 'admin-token', 'user': {'id': 'admin-id', 'role': 'admin'}}
                return original(method, path, payload, **kwargs)
            api.call = initial_login
            m.bootstrap(directory, api)
            self.assertEqual([x[1] for x in attempts[:4]],
                             ['/api/auth/login', '/api/auth/login', '/api/me/password', '/api/users'])
            self.assertEqual(attempts[2][2]['newPassword'], state['admin_password'])
            self.assertIn('password', json.loads((directory / 'state.json').read_text())['done'])

    def test_bootstrap_checkpoint_and_minimal_privileges(self):
        m = load()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'secrets'
            state = m.prepare(directory)
            api = FakeApi(state)
            m.bootstrap(directory, api)
            result = json.loads((directory / 'state.json').read_text())
            self.assertTrue(result['complete'])
            self.assertIn(('POST', '/api/teams/team-id/users', 'team-view-only'), api.roles)
            self.assertIn(('POST', '/api/users', 'view-only'), api.roles)
            self.assertEqual(api.created['teamId'], 'team-id')
            self.assertIn('UMAMI_API_KEY=umami_private', (directory / 'client.env').read_text())
            call_count = len(api.calls)
            m.bootstrap(directory, api)
            self.assertEqual(len(api.calls), call_count)

    def test_lost_key_response_does_not_create_another_key(self):
        m = load()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'secrets'
            state = m.prepare(directory)
            api = FakeApi(state, lose_key=True)
            with self.assertRaises(RuntimeError):
                m.bootstrap(directory, api)
            before = len([c for c in api.calls if c[1] == '/api/me/api-keys'])
            with self.assertRaises(RuntimeError):
                m.bootstrap(directory, api)
            self.assertEqual(len([c for c in api.calls if c[1] == '/api/me/api-keys']), before)

    def test_unknown_team_shape_preserves_uncertain_checkpoint_without_replay(self):
        m = load()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'secrets'
            state = m.prepare(directory)
            api = FakeApi(state)
            original = api.call
            def wrong_shape(method, path, payload=None, **kwargs):
                if path == '/api/teams' and method == 'POST':
                    api.calls.append((method, path))
                    return {'id': 'wrong-shape'}
                return original(method, path, payload, **kwargs)
            api.call = wrong_shape
            with self.assertRaisesRegex(RuntimeError, 'Unexpected team response'):
                m.bootstrap(directory, api)
            self.assertEqual(json.loads((directory / 'state.json').read_text())['pending'], 'team')
            before = len(api.calls)
            with self.assertRaisesRegex(RuntimeError, 'uncertain outcome'):
                m.bootstrap(directory, api)
            self.assertEqual(len(api.calls), before)

    def test_cli_unexpected_shape_does_not_print_traceback_or_response(self):
        m = load()
        output = io.StringIO()
        with patch.object(m, 'main', side_effect=TypeError('sensitive response body')):
            with contextlib.redirect_stderr(output):
                self.assertEqual(m.run(), 1)
        self.assertEqual(output.getvalue(), 'Analytics setup stopped: TypeError\n')

    def test_destination_is_explicit_loopback_no_redirects_or_proxy(self):
        m = load()
        for target in ['http://example.com:14320', 'http://127.0.0.1@evil.test',
                       'http://127.0.0.1:14320/path', 'https://localhost:14320',
                       'http://localhost:14320', 'http://127.0.0.1:14320?x=1']:
            with self.assertRaises(ValueError):
                m.Api(target)
        self.assertEqual(m.Api('http://127.0.0.1:14320').base_url, 'http://127.0.0.1:14320')

    def test_compose_isolated_pinned_and_no_public_ports(self):
        text = (ROOT / 'ops/analytics/compose.yaml').read_text()
        self.assertIn('name: jardines-analytics', text)
        self.assertEqual(text.count('@sha256:'), 2)
        self.assertIn('read_only: true', text)
        self.assertIn('cap_drop: [ALL]', text)
        self.assertIn('no-new-privileges:true', text)
        self.assertIn('internal: true', text)
        self.assertIn('name: jardines_app', text)
        self.assertNotIn('ports:', text)
        self.assertIn('${ANALYTICS_SECRETS_DIR}/db.env', text)
        self.assertNotIn('POSTGRES_PASSWORD_FILE', text)
        self.assertNotIn('crm-runtime.env', text)
        self.assertIn('DISABLE_TELEMETRY: "1"', text)
        self.assertIn('UMAMI_ENABLED', (ROOT / 'ops/analytics/bootstrap.py').read_text())
        local = (ROOT / 'ops/analytics/local.compose.yaml').read_text()
        self.assertIn('127.0.0.1:14320:3000', local)
        self.assertIn('external: false', local)
        self.assertIn('jardines-analytics-local', local)
        self.assertIn('internal: false', local)
        admin = (ROOT / 'ops/analytics/admin.compose.yaml').read_text()
        self.assertIn('networks: [app, analytics_data, maintenance]', admin)
        self.assertIn('maintenance:', admin)
        self.assertIn('internal: false', admin)
        self.assertIn('127.0.0.1:14320:3000', admin)
        self.assertNotIn('0.0.0.0', local + admin)


class FakeApi:
    def __init__(self, state, lose_key=False):
        self.state, self.lose_key = state, lose_key
        self.calls, self.roles, self.created = [], [], {}
        self.token = None

    def call(self, method, path, payload=None, token=None, allow_status=()):
        self.calls.append((method, path))
        if path == '/api/auth/login':
            if payload['username'] == 'admin' and payload['password'] != self.state['admin_password']:
                raise RuntimeError('unauthorized')
            return {'token': 'admin-token' if payload['username'] == 'admin' else 'reader-token',
                    'user': {'id': 'admin-id', 'role': 'admin' if payload['username'] == 'admin' else 'view-only'}}
        if path == '/api/me/password':
            return {'token': 'admin-token'}
        if method == 'GET' and path.startswith('/api/teams'):
            return {'data': []}
        if path == '/api/teams':
            return [{'id': 'team-id', 'name': 'Jardines landing analytics'},
                    {'id': 'membership-id', 'teamId': 'team-id', 'userId': 'admin-id', 'role': 'team-owner'}]
        if path.endswith('/users') or path == '/api/users':
            self.roles.append((method, path, payload['role']))
            return {'id': self.state['reader_id']}
        if path == '/api/websites':
            self.created = payload
            return {'id': self.state['website_id']}
        if path == '/api/me/api-keys':
            if self.lose_key:
                raise RuntimeError('response lost')
            return {'key': 'umami_private'}
        if method == 'POST' and path.startswith('/api/websites/') and token == 'umami_private':
            return {'_status': 401}
        return {'id': self.state['website_id']}
