"""Private, bounded text-only OpenAI credential boundary for Jardines Hermes."""
from collections import deque
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time
import re

MODEL = "gpt-6-luna"
MAX_BODY = 65536
MAX_REPLY = 2 * 1024 * 1024
SECRET = Path("/run/secrets/openai_api_key")


def validate(raw):
    if len(raw) > MAX_BODY:
        raise ValueError("Request too large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid JSON") from exc
    allowed = {"model", "messages", "max_tokens", "max_completion_tokens",
               "temperature", "stream", "stream_options", "tools", "tool_choice", "reasoning_effort"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Unsupported request")
    if data.get("model") != MODEL or data.get("tools"):
        raise ValueError("Model or tools denied")
    if data.get("tool_choice") not in (None, "none", "auto"):
        raise ValueError("Tools denied")
    messages = data.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise ValueError("Invalid messages")
    for msg in messages:
        if (not isinstance(msg, dict) or set(msg) - {"role", "content"}
                or msg.get("role") not in {"system", "developer", "user", "assistant"}
                or not isinstance(msg.get("content"), str)):
            raise ValueError("Only text messages are allowed")
    limit = data.get("max_completion_tokens", data.get("max_tokens", 512))
    if type(limit) is not int or not 1 <= limit <= 512:
        raise ValueError("Invalid token limit")
    # Preserve the previous non-reasoning workload on GPT-6 Luna, regardless
    # of the pinned Hermes custom-provider default (medium).
    if data.pop("reasoning_effort", None) not in (None, "medium", "none"):
        raise ValueError("Unsupported request")
    data.pop("max_tokens", None)
    data.pop("tools", None)
    data.pop("tool_choice", None)
    data["max_completion_tokens"] = limit
    data["reasoning_effort"] = "none"
    return data


class Handler(BaseHTTPRequestHandler):
    # Single-threaded server bounds upstream concurrency to one. No body/header logs.
    requests = deque()
    runs = {}

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_args):
        pass

    def reply(self, status, body, content_type="application/json"):
        print(json.dumps({"http_status": status}), flush=True)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 404, b'{}')

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.reply(404, b'{"error":{"message":"Route denied"}}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                raise ValueError("Invalid length")
            data = validate(self.rfile.read(length))
        except (ValueError, OSError) as exc:
            reasons = {"Request too large", "Invalid JSON", "Unsupported request", "Model or tools denied",
                       "Tools denied", "Invalid messages", "Only text messages are allowed", "Invalid token limit", "Invalid length"}
            reason = str(exc)
            print(json.dumps({"denied": reason if reason in reasons else "Malformed request"}), flush=True)
            self.reply(400, b'{"error":{"message":"Request denied by provider policy"}}')
            return
        run = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not re.fullmatch(r"[0-9a-f]{32}", run):
            self.reply(401, b'{"error":{"message":"Missing invocation identifier"}}')
            return
        now = time.monotonic()
        type(self).runs = {key: timestamp for key, timestamp in self.runs.items()
                     if now - timestamp < 300}
        if run in self.runs:
            self.reply(429, b'{"error":{"message":"One provider request per invocation"}}')
            return
        while self.requests and now - self.requests[0] >= 60:
            self.requests.popleft()
        if len(self.requests) >= 6:
            self.reply(429, b'{"error":{"message":"Local request limit reached"}}')
            return
        self.requests.append(now)
        type(self).runs[run] = now
        connection = HTTPSConnection("api.openai.com", timeout=60)
        try:
            key = SECRET.read_text().strip()
            connection.request("POST", "/v1/chat/completions",
                               body=json.dumps(data).encode(), headers={
                                   "Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(MAX_REPLY + 1)
            if response.status != 200:
                # Never echo upstream messages, request content, or credentials.
                try:
                    code = json.loads(body).get("error", {}).get("code")
                except (ValueError, AttributeError):
                    code = None
                safe_codes = {"invalid_api_key", "insufficient_quota", "rate_limit_exceeded",
                              "model_not_found", "billing_hard_limit_reached"}
                print(json.dumps({"upstream_status": response.status,
                                  "code": code if isinstance(code, str) and code in safe_codes
                                  else "upstream_error"}), flush=True)
                self.reply(response.status, json.dumps({"error": {
                    "message": "OpenAI rejected the request",
                    "code": code if isinstance(code, str) and code in safe_codes else "upstream_error",
                    "upstream_status": response.status}}).encode())
            elif len(body) > MAX_REPLY:
                self.reply(502, b'{"error":{"message":"Response too large"}}')
            else:
                content_type = ("text/event-stream" if data.get("stream")
                                else "application/json")
                self.reply(200, body, content_type)
        except Exception:
            self.reply(502, b'{"error":{"message":"Provider unavailable"}}')
        finally:
            connection.close()


if __name__ == "__main__":
    if not SECRET.is_file():
        raise SystemExit("Missing provider credential file")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
