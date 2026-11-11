"""One on-demand, tool-free Hermes turn; real provider credentials stay outside."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import sys
import uuid


def guarded_runtime(provider_ip):
    def deny(event, args):
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork",
                     "os.forkpty", "os.exec"}:
            raise PermissionError("Child processes are disabled")
        if event in {"socket.sendto", "socket.sendmsg", "socket.bind"}:
            raise PermissionError("Datagrams and listeners are disabled")
        if event == "socket.__new__":
            if args[1] not in {socket.AF_INET, socket.AF_INET6} or args[2] != socket.SOCK_STREAM:
                raise PermissionError("Only provider TCP sockets are allowed")
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or address[:2] != (provider_ip, 8080):
                raise PermissionError("Only the project provider is reachable")
    sys.addaudithook(deny)


def main():
    prompt = sys.stdin.read(4097).strip()
    if not prompt or len(prompt) > 4096:
        raise ValueError("Provide a prompt of 1–4096 characters on stdin")
    home = Path(os.environ["HERMES_HOME"])
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    (home / "config.yaml").write_text("""agent:
  environment_probe: false
compression:
  enabled: false
plugins:
  enabled: []
mcp_servers: {}
skills:
  auto_load: []
  creation_nudge_interval: 0
memory:
  memory_enabled: false
  user_profile_enabled: false
""")
    provider_ip = socket.gethostbyname("provider")
    guarded_runtime(provider_ip)
    sys.path.insert(0, "/opt/hermes")
    # Suppress upstream startup/progress logs; return only the bounded final result.
    agent = None
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from run_agent import AIAgent
        try:
            agent = AIAgent(
                base_url=f"http://{provider_ip}:8080/v1",
                api_key=uuid.uuid4().hex,
                provider="custom", api_mode="chat_completions", model="gpt-6-luna",
                enabled_toolsets=[], max_iterations=1, max_tokens=128,
                skip_context_files=True, skip_memory=True, skip_background_review=True,
                quiet_mode=True, save_trajectories=False, fallback_model={},
            )
            if agent.tools:
                raise RuntimeError("Tool-free policy failed")
            agent.client.max_retries = 0
            result = agent.run_conversation(
                prompt, system_message=("You are the on-demand assistant for Jardines del Encanto. "
                                        "Answer concisely in professional Spanish. You have no tools, "
                                        "CRM access, autonomous tasks or verified commercial data."))
        finally:
            if agent is not None:
                agent.close()
    failed = bool(result.get("failed") or result.get("error"))
    print(json.dumps({"ok": not failed, "model": "gpt-6-luna", "tools": 0,
                      "api_calls": result.get("api_calls"),
                      "response": "Provider request failed; inspect provider status." if failed
                      else result.get("final_response", "")}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    signal.alarm(120)
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never return raw library exceptions, configuration or request headers.
        print(json.dumps({"ok": False, "error": type(exc).__name__}))
        raise SystemExit(1)
