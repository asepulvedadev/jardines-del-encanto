"""Separate credential boundary permitting only the bounded Jardines broker tool."""
from collections import deque
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import time

from operator_protocol import (MODEL, MAX_BODY, MAX_RESULT, MAX_ITERATIONS, bounded_json,
                               call_arguments, text, tool_schema)

SECRET = Path('/run/secrets/openai_api_key')
MAX_REPLY = 65536


def validate(raw):
    data = bounded_json(raw)
    allowed = {'model', 'messages', 'max_tokens', 'max_completion_tokens', 'temperature', 'stream',
               'tools', 'tool_choice', 'reasoning_effort', 'parallel_tool_calls'}
    if not isinstance(data, dict) or set(data) - allowed or data.get('model') != MODEL or data.get('stream', False) is not False:
        raise ValueError('Request denied')
    tools = data.get('tools')
    if not isinstance(tools, list) or len(tools) != 1:
        raise ValueError('Tool denied')
    tool_schema(tools[0])
    actions = tools[0]['function']['parameters']['properties']['action']['enum']
    if data.get('tool_choice') not in (None, 'auto', 'none') or data.get('parallel_tool_calls', False) is not False:
        raise ValueError('Tool policy denied')
    messages = data.get('messages')
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise ValueError('Invalid messages')
    pending = set()
    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError('Invalid message')
        role = msg.get('role')
        if role in {'system', 'developer', 'user'}:
            if set(msg) != {'role', 'content'} or pending:
                raise ValueError('Invalid text message')
            text(msg['content'], 100000 if role in {'system', 'developer'} else 4096)
        elif role == 'assistant':
            if set(msg) - {'role', 'content', 'tool_calls'} or pending:
                raise ValueError('Invalid assistant message')
            if msg.get('content') is not None:
                text(msg['content'])
            calls = msg.get('tool_calls', [])
            if not isinstance(calls, list) or len(calls) > 12:
                raise ValueError('Invalid tool calls')
            for call in calls:
                if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'} or call['type'] != 'function':
                    raise ValueError('Invalid tool call')
                identifier = text(call['id'], 128, False)
                fn = call['function']
                if not isinstance(fn, dict) or set(fn) != {'name', 'arguments'} or fn['name'] != 'jardines_app' or identifier in pending:
                    raise ValueError('Tool denied')
                call_arguments(bounded_json(text(fn['arguments'], MAX_RESULT).encode(), MAX_RESULT), actions)
                pending.add(identifier)
        elif role == 'tool':
            if set(msg) != {'role', 'tool_call_id', 'content'} or msg['tool_call_id'] not in pending:
                raise ValueError('Invalid tool result')
            text(msg['content'], MAX_RESULT)
            if not isinstance(bounded_json(msg['content'].encode(), MAX_RESULT), dict):
                raise ValueError('Invalid tool result')
            pending.remove(msg['tool_call_id'])
        else:
            raise ValueError('Role denied')
    if pending:
        raise ValueError('Incomplete tool results')
    limit = data.get('max_completion_tokens', data.get('max_tokens', 1024))
    if type(limit) is not int or not 1 <= limit <= 1024:
        raise ValueError('Token budget denied')
    if data.get('reasoning_effort') not in (None, 'none', 'medium'):
        raise ValueError('Reasoning denied')
    temperature = data.get('temperature')
    if temperature is not None and (type(temperature) not in (int, float) or not 0 <= temperature <= 2):
        raise ValueError('Invalid temperature')
    data.pop('max_tokens', None)
    data['max_completion_tokens'] = limit
    data['reasoning_effort'] = 'none'
    data['parallel_tool_calls'] = False
    return data


def ready():
    try:
        return bool(SECRET.is_file() and SECRET.read_text().strip())
    except OSError:
        return False


def model_reply(message):
    """Normalize only observed inert Chat Completions metadata, never extra tools."""
    if (not isinstance(message, dict) or message.get('role') != 'assistant'
            or set(message) - {'role', 'content', 'tool_calls', 'refusal', 'annotations'}
            or message.get('refusal') not in (None, '')
            or message.get('annotations') not in (None, [])):
        raise ValueError('Unsupported provider reply')
    result = {'role': 'assistant', 'content': message.get('content')}
    calls = message.get('tool_calls')
    if calls is not None:
        if not isinstance(calls, list):
            raise ValueError('Invalid tool calls')
        if calls:
            result['tool_calls'] = calls
    return result


class Handler(BaseHTTPRequestHandler):
    """One upstream request at a time; no content or authorization logging."""
    requests = deque()
    runs = {}

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_args):
        pass

    def reply(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != '/health':
            return self.reply(404, {'error': 'Route denied'})
        available = ready()
        self.reply(200 if available else 503, {'available': available, 'configured': available, 'model': MODEL})

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            return self.reply(404, {'error': {'message': 'Route denied'}})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY or self.headers.get('Transfer-Encoding'):
                raise ValueError('Invalid body')
            data = validate(self.rfile.read(length))
        except (ValueError, TypeError, OSError, KeyError):
            return self.reply(400, {'error': {'message': 'Request denied by operator policy'}})
        run = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not re.fullmatch(r'[0-9a-f]{32}', run):
            return self.reply(401, {'error': {'message': 'Invocation denied'}})
        now = time.monotonic()
        type(self).runs = {key: value for key, value in self.runs.items() if now - value[0] < 300}
        started, calls = self.runs.get(run, (now, 0))
        while self.requests and now - self.requests[0] >= 60:
            self.requests.popleft()
        if calls >= MAX_ITERATIONS or now - started > 120 or len(self.requests) >= 24:
            return self.reply(429, {'error': {'message': 'Operator budget reached'}})
        if not ready():
            return self.reply(503, {'error': {'message': 'Provider not configured'}})
        self.runs[run] = (started, calls + 1)
        self.requests.append(now)
        connection = HTTPSConnection('api.openai.com', timeout=30)
        try:
            key = SECRET.read_text().strip()
            connection.request('POST', '/v1/chat/completions', body=json.dumps(data, ensure_ascii=False).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
            response = connection.getresponse()
            raw = response.read(MAX_REPLY + 1)
            if response.status != 200 or len(raw) > MAX_REPLY:
                return self.reply(502, {'error': {'message': 'Provider rejected request'}})
            result = bounded_json(raw, MAX_REPLY)
            # Do not permit upstream auxiliary fields or arbitrary tool names into Hermes.
            choice = result['choices'][0]
            message = model_reply(choice['message'])
            validate(json.dumps({**data, 'messages': [*data['messages'], message,
                *[{'role': 'tool', 'tool_call_id': call['id'], 'content': '{}'}
                  for call in message.get('tool_calls', [])]]}, ensure_ascii=False).encode())
            self.reply(200, {'id': 'operator-response', 'object': 'chat.completion', 'model': MODEL,
                'choices': [{'index': 0, 'message': message, 'finish_reason': choice.get('finish_reason', 'stop')}],
                'usage': result.get('usage', {})})
        except Exception:
            self.reply(502, {'error': {'message': 'Provider unavailable'}})
        finally:
            connection.close()


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
