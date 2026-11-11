"""The credential boundary must reject tools and unbounded provider requests."""
import importlib.util
import json
from pathlib import Path
import unittest
import threading
import subprocess
import sys
import urllib.request
import urllib.error
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location(
    "provider", Path(__file__).parents[1] / "ops/hermes/provider.py"
)
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)


class ProviderPolicyTests(unittest.TestCase):
    def request(self, **extra):
        return json.dumps({"model": "gpt-6-luna", "messages": [
            {"role": "user", "content": "Hello"}], **extra}).encode()

    def test_bounded_text_and_streaming_are_accepted(self):
        result = provider.validate(self.request(stream=True, max_tokens=32))
        self.assertEqual(result["model"], "gpt-6-luna")
        self.assertTrue(result["stream"])
        self.assertEqual(result["max_completion_tokens"], 32)
        self.assertNotIn("tools", result)

    def test_omitted_token_limit_is_capped(self):
        self.assertEqual(provider.validate(self.request())["max_completion_tokens"], 512)

    def test_rejects_tool_calls_models_and_unbounded_inputs(self):
        for extra in [
            {"tools": [{"type": "function"}]}, {"functions": [{}]},
            {"model": "other"}, {"model": "gpt-4.1-mini"}, {"max_tokens": 513}, {"max_tokens": 0},
            {"max_tokens": True}, {"messages": []},
            {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]},
            {"messages": [{"role": "tool", "content": "secret"}]},
            {"metadata": {"unexpected": "field"}},
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                provider.validate(self.request(**extra))
        for raw in [b"[]", b"null", b"invalid", b" " * 65537]:
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                provider.validate(raw)

    def test_hermes_reasoning_default_preserves_non_reasoning_workload(self):
        result = provider.validate(self.request(reasoning_effort="medium"))
        self.assertEqual(result["reasoning_effort"], "none")
        self.assertNotIn("max_tokens", result)
        with self.assertRaises(ValueError):
            provider.validate(self.request(reasoning_effort="high"))

    def test_empty_tool_list_is_removed(self):
        self.assertNotIn("tools", provider.validate(self.request(tools=[])))


class ProviderHTTPTests(unittest.TestCase):
    def setUp(self):
        provider.Handler.requests.clear()
        provider.Handler.runs.clear()
        self.server = provider.HTTPServer(("127.0.0.1", 0), provider.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, payload):
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + "a" * 32})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_denials_never_read_key_or_call_upstream(self):
        with patch.object(provider, "HTTPSConnection") as connection:
            status, _ = self.post("/v1/responses", {})
            self.assertEqual(status, 404)
            status, _ = self.post("/v1/chat/completions", {"model": "other"})
            self.assertEqual(status, 400)
            connection.assert_not_called()

    def test_fixed_upstream_secret_injection_and_sanitized_error(self):
        response = Mock(status=401)
        response.read.return_value = json.dumps({"error": {
            "code": "invalid_api_key", "message": "Never echo sensitive content"}}).encode()
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(provider, "HTTPSConnection", return_value=connection) as factory, \
                patch.object(provider.Path, "read_text", return_value="test-private-token"):
            status, body = self.post("/v1/chat/completions", {
                "model": provider.MODEL, "messages": [{"role": "user", "content": "Hello"}]})
        self.assertEqual(status, 401)
        self.assertIn(b"invalid_api_key", body)
        self.assertNotIn(b"sensitive", body)
        self.assertNotIn(b"test-private", body)
        factory.assert_called_once_with("api.openai.com", timeout=60)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", "/v1/chat/completions"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-private-token")

    def test_second_request_in_invocation_never_reaches_upstream(self):
        provider.Handler.runs["a" * 32] = provider.time.monotonic()
        with patch.object(provider, "HTTPSConnection") as connection:
            status, _ = self.post("/v1/chat/completions", {
                "model": provider.MODEL, "messages": [{"role": "user", "content": "Hello"}]})
            self.assertEqual(status, 429)
            connection.assert_not_called()

    def test_local_rate_limit_prevents_paid_call(self):
        provider.Handler.requests.extend([provider.time.monotonic()] * 6)
        with patch.object(provider, "HTTPSConnection") as connection:
            status, _ = self.post("/v1/chat/completions", {
                "model": provider.MODEL, "messages": [{"role": "user", "content": "Hello"}]})
            self.assertEqual(status, 429)
            connection.assert_not_called()


class AssistantGuardTests(unittest.TestCase):
    def test_child_process_and_non_provider_sockets_are_denied(self):
        script = Path(__file__).parents[1] / "ops/hermes/assistant.py"
        code = f"""
import importlib.util, socket, subprocess
spec = importlib.util.spec_from_file_location('assistant', {str(script)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.guarded_runtime('192.0.2.1')
for action in [lambda: subprocess.run(['true']),
               lambda: socket.create_connection(('127.0.0.1', 5432)),
               lambda: socket.create_connection(('192.0.2.1', 80)),
               lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'guard-test', ('127.0.0.1', 9))]:
    try:
        action()
    except PermissionError:
        continue
    raise AssertionError('Runtime guard did not deny action')
print('guards_ok')
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "guards_ok")


if __name__ == "__main__":
    unittest.main()
