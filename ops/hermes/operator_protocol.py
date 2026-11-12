"""Strict private protocol shared by the operator and its credential boundary."""
import json
import re
from urllib.parse import urlsplit

MODEL = 'gpt-6-luna'
MAX_BODY = 131072
MAX_RESULT = 65536
MAX_TEXT = 20000
MAX_CALLS = 12
MAX_ITERATIONS = 4
ACTIONS = frozenset({'crm.workspace', 'crm.activities', 'crm.contact.create', 'crm.contact.update',
    'crm.deal.update', 'crm.note.create', 'crm.task.create', 'crm.task.update', 'control.catalog',
    'control.item.create', 'control.item.update', 'control.connection.update', 'social.status',
    'social.sync', 'social.connect', 'control.extension.create', 'control.extension.update',
    'control.extension.install', 'control.extension.test', 'voice.catalog', 'voice.execute'})


def valid_token(token):
    return isinstance(token, str) and bool(re.fullmatch(r'(?:[A-Za-z0-9_-]{43}|[0-9a-f]{64})', token))


def bounded_json(raw, limit=MAX_BODY):
    if len(raw) > limit:
        raise ValueError('Body exceeds policy')
    def reject(_):
        raise ValueError('Nonfinite JSON denied')
    data = json.loads(raw, parse_constant=reject)
    return data


def text(value, limit=MAX_TEXT, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError('Text exceeds policy')
    return value


def tool_schema(schema):
    if not isinstance(schema, dict) or set(schema) != {'type', 'function'} or schema['type'] != 'function':
        raise ValueError('Invalid tool')
    fn = schema['function']
    if not isinstance(fn, dict) or set(fn) - {'name', 'description', 'parameters', 'strict'}:
        raise ValueError('Invalid function')
    if fn.get('name') != 'jardines_app':
        raise ValueError('Tool denied')
    description = text(fn.get('description', ''), 16384)
    if len(description.encode()) > 16384:
        raise ValueError('Tool manifest exceeds policy')
    if 'strict' in fn and type(fn['strict']) is not bool:
        raise ValueError('Invalid strict flag')
    params = fn.get('parameters')
    if not isinstance(params, dict) or set(params) != {'type', 'properties', 'required', 'additionalProperties'}:
        raise ValueError('Invalid parameters')
    if params['type'] != 'object' or params['additionalProperties'] is not False or not isinstance(params['required'], list) or params['required'] != ['action', 'arguments']:
        raise ValueError('Invalid parameters')
    properties = params['properties']
    if not isinstance(properties, dict) or set(properties) != {'action', 'arguments'}:
        raise ValueError('Invalid properties')
    action = properties['action']
    args = properties['arguments']
    if (not isinstance(action, dict) or set(action) - {'type', 'enum', 'description'} or action.get('type') != 'string'
            or not isinstance(args, dict) or set(args) - {'type', 'description', 'properties', 'required'} or args.get('type') != 'object'
            or args.get('properties', {}) != {} or args.get('required', []) != []):
        raise ValueError('Invalid action schema')
    allowed = action.get('enum')
    if not isinstance(allowed, list) or not 1 <= len(allowed) <= 256 or any(not isinstance(item, str) for item in allowed) or len(set(allowed)) != len(allowed):
        raise ValueError('Invalid actions')
    for item in allowed:
        if not isinstance(item, str) or (item not in ACTIONS and not re.fullmatch(r'custom\.[0-9a-f-]{36}', item)):
            raise ValueError('Action denied')
    return schema


def call_arguments(value, allowed):
    if not isinstance(value, dict) or set(value) != {'action', 'arguments'}:
        raise ValueError('Invalid tool arguments')
    if not isinstance(value['action'], str) or value['action'] not in allowed or not isinstance(value['arguments'], dict):
        raise ValueError('Action denied')
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT:
        raise ValueError('Arguments exceed policy')
    return value


def validate_history(history):
    if not isinstance(history, list) or len(history) > 8:
        raise ValueError('History exceeds policy')
    total = 0
    for message in history:
        if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                or not isinstance(message['role'], str) or message['role'] not in {'user', 'assistant'}):
            raise ValueError('Historical authority denied')
        total += len(text(message['content'], 4096, False))
    if total > 16000:
        raise ValueError('History exceeds context policy')
    return history


def validate_claim(claim):
    required = {'run_id', 'prompt', 'skills', 'tools'}
    if not isinstance(claim, dict) or not required <= set(claim) or set(claim) - required - {'history'}:
        raise ValueError('Invalid claim')
    text(claim['run_id'], 128, False)
    text(claim['prompt'], 8000, False)
    if 'history' in claim:
        validate_history(claim['history'])
    skills = claim['skills']
    if not isinstance(skills, list) or len(skills) > 64:
        raise ValueError('Invalid skills')
    for skill in skills:
        if not isinstance(skill, dict) or set(skill) != {'name', 'content'}:
            raise ValueError('Invalid skill')
        text(skill['name'], 128, False)
        text(skill['content'], 16000)
    if len(json.dumps(skills, ensure_ascii=False).encode()) > MAX_RESULT:
        raise ValueError('Skills exceed context policy')
    tools = claim['tools']
    if not isinstance(tools, list) or len(tools) != 1:
        raise ValueError('Exactly one application tool required')
    tool_schema(tools[0])
    return claim


def internal_endpoint(url, service, port):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment or parsed.hostname not in {service, '127.0.0.1'}
            or (parsed.hostname == service and parsed.port != port) or not parsed.port):
        raise ValueError('Internal endpoint denied')
    return parsed.hostname, parsed.port
