#!/usr/bin/env python3
"""Explicit fresh-instance Umami setup. No SSH, Docker execution or ambient credentials."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Umami request failed (HTTP {status}); inspect private checkpoint, not response bodies.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Umami redirect refused.')


class Api:
    def __init__(self, base_url):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                or parsed.port != 14320):
            raise ValueError('Use the explicit loopback maintenance endpoint http://127.0.0.1:14320 only.')
        self.base_url = base_url
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, method, path, payload=None, token=None, allow_status=()):
        if not path.startswith('/api/') or '://' in path:
            raise ValueError('Invalid API path.')
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        request = urllib.request.Request(self.base_url + path, method=method, headers=headers,
                                         data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with self.opener.open(request, timeout=15) as response:
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise RuntimeError('Oversized Umami response refused.')
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            if error.code in allow_status:
                return {'_status': error.code}
            raise ApiError(error.code) from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Umami connection failed; retain checkpoint before retry.') from None


def private_directory(directory):
    directory = Path(directory)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError('Secret directory must be an absolute, non-symlink path.')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode) != 0o700 or directory.stat().st_uid != os.geteuid():
        raise ValueError('Secret directory must be owner-controlled with mode 0700.')
    for item in directory.iterdir():
        if item.is_symlink() or not item.is_file() or stat.S_IMODE(item.stat().st_mode) != 0o600 or item.stat().st_uid != os.geteuid():
            raise ValueError('Every secret file must be owner-controlled, regular and mode 0600.')
    return directory


def write_private(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def checkpoint(directory, state):
    write_private(directory / 'state.json', json.dumps(state, indent=2) + '\n')


def prepare(directory):
    directory = private_directory(directory)
    state_path = directory / 'state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get('version') != 1:
            raise ValueError('Unknown checkpoint format.')
        if not (directory / 'db.env').exists() and (directory / 'db_password').is_file():
            # Compatibility with the initial local-only file-secret policy: Docker
            # reads env_file itself; do not weaken host 0600 to serve UID 70.
            password = (directory / 'db_password').read_text().strip()
            if not password or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for char in password):
                raise ValueError('Invalid saved analytics database password.')
            write_private(directory / 'db.env', 'POSTGRES_PASSWORD=' + password + '\n')
        return state
    if any(item.name != '.setup.lock' for item in directory.iterdir()):
        raise ValueError('Nonempty secret directory without checkpoint: recover manually, do not overwrite.')
    state = {'version': 1, 'website_id': str(uuid.uuid4()), 'reader_id': str(uuid.uuid4()),
             'admin_password': secrets.token_urlsafe(36), 'reader_password': secrets.token_urlsafe(36),
             'done': [], 'pending': None, 'complete': False}
    # The checkpoint is written first: never silently replace keys after a partial prepare.
    checkpoint(directory, state)
    db_password = secrets.token_urlsafe(36)
    write_private(directory / 'db_password', db_password + '\n')
    write_private(directory / 'db.env', 'POSTGRES_PASSWORD=' + db_password + '\n')
    write_private(directory / 'server.env', '\n'.join([
        'DATABASE_URL=postgresql://jardines_analytics:' + db_password + '@analytics-db:5432/jardines_analytics',
        'APP_SECRET=' + secrets.token_hex(32), 'TWO_FACTOR_ENCRYPTION_KEY=' + secrets.token_hex(32), '']))
    common = ('UMAMI_ENABLED=1\nUMAMI_BASE_URL=http://umami:3000\n'
              f'UMAMI_WEBSITE_ID={state["website_id"]}\nUMAMI_TRUST_PROXY=1\n')
    write_private(directory / 'collector.env', common)
    # Not activated in the CRM until the separate installed-policy rollout.
    write_private(directory / 'client.env', common)
    return state


def bootstrap(directory, api):
    directory = private_directory(directory)
    state = json.loads((directory / 'state.json').read_text())
    required = ['server.env', 'db_password', 'db.env', 'collector.env', 'client.env']
    if not all((directory / name).is_file() for name in required):
        raise RuntimeError('Incomplete preparation: recover original checkpoint/files, do not reset database or secrets.')
    if state['complete']:
        return
    # An uncertain write is never replayed. The operator must inspect it and reconcile
    # the exact checkpoint; in particular, API keys are only returned once.
    if state['pending']:
        raise RuntimeError('An operation has an uncertain outcome: ' + state['pending']
                           + '. Follow docs/ANALYTICS.md checkpoint recovery; do not repeat creation.')
    try:
        login = api.call('POST', '/api/auth/login', {'username': 'admin', 'password': state['admin_password']})
    except ApiError as error:
        if error.status != 401 or 'password' in state['done']:
            raise
        login = api.call('POST', '/api/auth/login', {'username': 'admin', 'password': 'umami'})
        state['pending'] = 'password'
        checkpoint(directory, state)
        login = api.call('POST', '/api/me/password', {'currentPassword': 'umami', 'newPassword': state['admin_password']}, token=login['token'])
        state['done'].append('password')
        state['pending'] = None
        checkpoint(directory, state)
    admin_token = login['token']

    def step(name, method, path, payload, token=admin_token):
        if name in state['done']:
            return None
        state['pending'] = name
        checkpoint(directory, state)
        result = api.call(method, path, payload, token=token)
        if name == 'team':
            # v3.5.0 createTeam returns the Prisma transaction [Team, TeamUser],
            # and the route serializes that array without an envelope.
            if (not isinstance(result, list) or len(result) != 2
                    or not all(isinstance(item, dict) for item in result)
                    or result[0].get('name') != 'Jardines landing analytics'
                    or not isinstance(result[0].get('id'), str)
                    or result[1].get('teamId') != result[0]['id']
                    or result[1].get('role') != 'team-owner'):
                raise RuntimeError('Unexpected team response; preserve pending checkpoint and reconcile the existing team.')
            state['team_id'] = result[0]['id']
        if name == 'key':
            if not isinstance(result, dict) or not isinstance(result.get('key'), str) or not result['key'].startswith('umami_'):
                raise RuntimeError('Unexpected API key response; preserve pending checkpoint and revoke the uncertain key.')
            state['api_key'] = result['key']
        state['done'].append(name)
        state['pending'] = None
        checkpoint(directory, state)
        return result

    step('reader', 'POST', '/api/users', {'id': state['reader_id'], 'username': 'jardines-analytics-reader',
                                         'password': state['reader_password'], 'role': 'view-only'})
    step('team', 'POST', '/api/teams', {'name': 'Jardines landing analytics'})
    step('membership', 'POST', f'/api/teams/{state["team_id"]}/users',
         {'userId': state['reader_id'], 'role': 'team-view-only'})
    step('website', 'POST', '/api/websites', {'id': state['website_id'], 'name': 'Jardines del Encanto',
                                            'domain': 'jardinesdelencanto.site', 'teamId': state['team_id']})
    step('privacy', 'POST', f'/api/websites/{state["website_id"]}',
         {'replayConfig': {'replayEnabled': False, 'heatmapEnabled': False, 'sampleRate': 0, 'heatmapSampleRate': 0}})
    reader = api.call('POST', '/api/auth/login', {'username': 'jardines-analytics-reader', 'password': state['reader_password']})
    if reader['user']['role'] != 'view-only':
        raise RuntimeError('Reader role verification failed.')
    step('key', 'POST', '/api/me/api-keys', {'name': 'Jardines CRM aggregate reader'}, token=reader['token'])
    # Verify the API key actually reads this website and cannot update it. No-op
    # update of the same name is non-destructive even if upstream permissions drift.
    api.call('GET', f'/api/websites/{state["website_id"]}', token=state['api_key'])
    denied = api.call('POST', f'/api/websites/{state["website_id"]}', {'name': 'Jardines del Encanto'},
                      token=state['api_key'], allow_status=(401, 403))
    if denied.get('_status') not in (401, 403):
        raise RuntimeError('Reader is not read-only; client key was not activated.')
    client = (directory / 'collector.env').read_text() + 'UMAMI_API_KEY=' + state['api_key'] + '\n'
    write_private(directory / 'client.env', client)
    state['complete'] = True
    checkpoint(directory, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'bootstrap'])
    parser.add_argument('--secrets-dir', required=True, type=Path)
    parser.add_argument('--fresh-instance', action='store_true', help='Attest this is a new isolated Umami instance, not existing data.')
    parser.add_argument('--base-url', help='Explicit maintenance destination: http://127.0.0.1:14320')
    args = parser.parse_args()
    if not args.fresh_instance:
        parser.error('--fresh-instance is required; never bootstrap an existing installation')
    directory = private_directory(args.secrets_dir)
    # A private advisory lock also prevents two operator bootstrap processes racing.
    lock_path = directory / '.setup.lock'
    with open(lock_path, 'a', opener=lambda path, flags: os.open(path, flags | os.O_NOFOLLOW, 0o600)) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.operation == 'prepare':
            prepare(directory)
        else:
            if not args.base_url:
                parser.error('--base-url is required for bootstrap')
            bootstrap(directory, Api(args.base_url))
    print('Analytics ' + args.operation + ' completed. Credentials remain in the private directory; no service was deployed.')


def run():
    try:
        main()
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, IndexError) as error:
        # Never print request bodies, environment values, tokens or secrets.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print('Analytics setup stopped: ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(run())
