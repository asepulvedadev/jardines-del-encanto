# Sara IA runtime: bounded history and voice notes

Sara IA names the existing Hermes application operator. This change adds bounded
conversation context and optional file transcription, not another agent, live calls,
TTS, native plugins, or broader tools. Implementation is local; production activation
and provider credentials remain separate owner-authorized operations.

## Verify locally

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_sara_runtime.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_hermes_operator.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_hermes_provider.py
docker compose -f ops/hermes/operator.compose.yaml config --quiet
```

These checks use local HTTP fixtures and fake upstream responses, never real keys
or paid requests. The original text-only `assistant.py`, `provider.py`, and CLI
Compose profile are unchanged.

## History and rolling compatibility

| Boundary | Rule |
| --- | --- |
| Claim | Original required keys unchanged; optional `history` only |
| History | At most 8 `{role,content}` messages; user/assistant text only |
| Text budget | 4,096 characters each, 16,000 total history characters |
| Current prompt | At most 8,000 characters including untrusted excerpts |
| SDK call | `conversation_history` supplied only when history is nonempty |
| Authority | No historical tools, proposals, identities, or approval replay |

The actual pinned `AIAgent.run_conversation` accepts `conversation_history`; source
was inspected in `agent/conversation_loop.py` within the existing pinned image.
History is validated before SDK construction. The Sara IA system instruction treats
history, attachments, and retrieved text as untrusted context, not authorization.
The single `jardines_app` tool, exact broker actions, approval requirement, four-model
iteration budget, twelve-call cap, 128 KiB provider context limit, and fixed-peer
audit guard remain in force. Oversized context fails rather than silently truncating.

New provider health advertises `history_available: true` as protocol support. Bridge
health reports it only when the provider is ready and explicitly returns Boolean
`true`. New Sara API availability must require this handshake, preventing the new UI
from advertising persistent history against an older root-owned runtime. Legacy
Hermes `available` behavior does not depend on this additional field.

## Voice flow and credential boundary

```text
Explicit recorded/uploaded note
  → administrator-only application attachment route
  → private bridge POST /transcribe
  → private provider POST /audio/transcriptions
  → verified TLS api.openai.com/v1/audio/transcriptions
  → bounded {text} reply
```

Both private requests accept exactly `{audio_base64,mime_type}`. They do not accept
filenames, URLs, model names, language selection, prompts, or native commands.
The provider alone mounts the existing OpenAI credential. The bridge supplies only
a random, one-use request-budget identifier, not a provider key. Multipart fields
are fixed to `gpt-4o-mini-transcribe`, Spanish (`es`), JSON output, and a generated
extension-bearing `voice.*` filename. There are no redirects, proxy-environment
routing, automatic retries, streaming, audio generation, or additional SDK dependencies.
These fields and formats follow the [OpenAI transcription API reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create).

`HERMES_TRANSCRIPTION_ENABLED=1` is an explicit provider-only opt-in. Compose defaults
to `0`; voice being off must not disable ordinary text readiness. Bridge health
propagates `transcription_available` only for a ready provider explicitly returning
Boolean `true`. Presence of a local credential is not proof of live upstream quota,
model entitlement, or successful speech recognition; upstream failures stay opaque.

**Compatibility deadline:** OpenAI documents shutdown of `gpt-4o-mini-transcribe`
on February 26, 2027. This implementation intentionally keeps the requested fixed
alias; reassess and explicitly review the replacement before that date, rather than
silently selecting a different model. See the [official compatibility notice](https://developers.openai.com/api/docs/guides/speech-to-text).

## Audio limits and failure behavior

| Boundary | Limit |
| --- | --- |
| JSON request | 768 KiB, exact bounded Content-Length frame |
| Decoded media | 512 KiB; canonical base64; nonempty valid container signature |
| Formats | WebM/Opus, Ogg/Opus or Vorbis, MP3, WAV, MP4 |
| MIME aliases | `audio/mp3` → `audio/mpeg`; `audio/x-wav` → `audio/wav` |
| Browser parameters | WebM/Ogg `codecs=opus` normalized; other parameters denied |
| Response | 64 KiB upstream JSON; nonempty text at most 16,000 characters |
| Input body deadline | 3 seconds total for voice; short/duplicate/chunked/compressed framing denied |
| Provider deadline | 25 seconds total, including DNS and slow responses; upstream socket 20 seconds |
| Bridge deadline | 28 seconds total; private socket 26 seconds; health probe 1 second |
| Audio rate/replay | 6 requests/minute; one attempt per ephemeral invocation identifier |
| Concurrency | Existing single-threaded production HTTPServer, one upstream request at a time |

The production servers must remain on their main thread: outer SIGALRM deadlines
interrupt even blocking DNS and cannot be swallowed by ordinary HTTP exception
handlers. On expiry the socket closes; no invented transcript or partial success
is returned. The tests separately exercise this main-thread deadline and worker-thread
loopback HTTP protocol fixtures. Application request and BFF timeouts remain above
the bridge deadline; no Nginx timeout increase is required for notes.

Container signatures establish the allowed upload envelope, not semantic validity or
proof of recognized speech. The provider still validates the file. No conversion,
untrusted code execution, temporary media files, audio/transcript/token logs, or
provider-secret mounts on the API/bridge are added. Backend storage, owner isolation,
request idempotency, and explicit browser recording/preview/discard belong to the
application contract in `docs/SARA-IA.md`.

## Genuine pinned Hermes history proof

Run from the repository root using the already cached image:

```sh
docker run --rm --network none --user 1000:1000 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --memory 1g --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m,uid=1000,gid=1000 \
  --tmpfs /opt/data:rw,noexec,nosuid,size=16m,uid=1000,gid=1000 \
  -e HOME=/tmp -e HERMES_HOME=/tmp/hermes-operator \
  -e HERMES_REAL_INTEGRATION=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/ops/hermes:/workspace/ops/hermes:ro" \
  -v "$PWD/ops/crm.compose.yaml:/workspace/ops/crm.compose.yaml:ro" \
  -v "$PWD/tests/test_hermes_operator.py:/workspace/tests/test_hermes_operator.py:ro" \
  --entrypoint /opt/hermes/.venv/bin/python \
  nousresearch/hermes-agent:stable@sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08 \
  -m unittest discover -s /workspace/tests -p test_hermes_operator.py
```

The genuine SDK consumes claimed user/assistant history, calls the actual registry
handler, receives a real loopback broker result, and makes a second model request
before finishing. Only the upstream HTTPS transport is replaced by deterministic
responses. Assertions check Sara IA's persona, the historical marker in model input,
unchanged tool restrictions, and absence of customer/history strings in SDK files.

For a future separately authorized deployment, install the reviewed root-owned
`operator_audio.py` alongside the operator/provider/protocol files and preserve
individual read-only mounts and the `/policy/hermes_operator.py` entrypoint alias.
Do not mount the entire policy directory or activate voice implicitly.
