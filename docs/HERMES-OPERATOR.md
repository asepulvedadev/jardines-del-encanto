# Private Hermes application operator

This is a separate, locally verified operator profile. It does not replace or weaken
`assistant.py`, `provider.py`, or their tool-free CLI Compose profile. Production
activation, credentials, and live paid calls remain separate owner decisions.

## Execution contract

The bridge exposes private `GET /health` and `POST /run` with **only** `{token}`.
The initiating prompt, enabled skills, and one `jardines_app` function schema come
from the API's single-use `/internal/hermes/claim`. Callers cannot choose a prompt,
broker URL, provider URL, model, native tool, or command through `/run`.

The actual pinned `run_agent.AIAgent` owns conversation/tool iteration. Its registered
`jardines_app` handler calls `/internal/hermes/call` with a fresh deduplication ID,
action, and arguments. Broker tool results return to the genuine Hermes model
conversation before `/internal/hermes/finish` freezes the final reply. The API is
responsible for token hashing/expiry/revocation, typed application authorization,
proposal confirmation, and transactional exactly-once approved writes. A returned
proposal is not a successful write. The bridge does not implement a second LLM loop.

Bounds: four model requests per invocation, 1,024 output tokens per request, twelve
broker calls (locked across tool threads), a 120-second bridge deadline, 64 KiB per
broker result/arguments, 128 KiB per model request, 16,000 final-reply characters,
and a 16 KiB UTF-8 capability manifest. The hard deadline allows at most five
additional seconds for cleanup before terminating the isolated bridge process. Oversized results fail closed; they are not
silently truncated. Workspace reads should use the broker's paging fields.

## Isolation and credentials

- The only usable model tool is `jardines_app`; an exact-surface assertion rejects
  any unexpected tools. Built-in discovery is disabled before SDK import, native
  plugins use `HERMES_SAFE_MODE=1`, and MCP configuration is empty.
- Application skills are bounded instruction data. Tools/plugins/scripts are typed
  broker workflows, never imported Python, shell, JavaScript, or native plugins.
- Memory, trajectories, context files, background review, fallback models, and
  persistence are disabled. Startup/progress streams are discarded, not retained.
- A Python audit hook denies child processes, new listeners, datagrams, and TCP
  connections except the resolved fixed broker/provider peers. The model client
  additionally disables environment proxies, redirects, and automatic retries.
- Only `operator-provider` mounts the credential file. Hermes receives a random
  ephemeral request-budget identifier, not the provider credential or API run token
  in its prompt. The provider uses fixed `HTTPSConnection('api.openai.com')` and
  `/v1/chat/completions`; it does not follow redirects or environment proxies.
- Both services are non-root/read-only, capability-free, process/CPU/memory capped,
  and have only ephemeral tmpfs storage. No Docker socket, host code execution,
  persistent customer volume, or other project mount is provided.
- The bridge joins the external application network plus a private operator network,
  never a database network. Only the provider joins egress. Port 8081 is exposed
  internally, not published to the host. The external application network must itself
  be internal, as in the existing app Compose configuration.

Provider health is unavailable without a nonempty credential file; bridge health
requires initialized Hermes and a provider reporting the fixed model and configured
readiness. This does not promise that an untested key has live quota or entitlement:
upstream denial becomes an opaque failure, never an invented reply or success.

Live deployment verification observed normal OpenAI assistant replies containing
`refusal: null` and `annotations: []`. The provider strips only that inert metadata
and nullable/empty tool-call lists before strict validation. Nonempty refusals,
annotations or unsupported reply fields remain denied. Request schemas/tool names
stay unchanged; this is not permission to forward arbitrary response extensions.

## Pinned SDK evidence

Inspected the actual image, not an assumed SDK:

`nousresearch/hermes-agent:stable@sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`

The image contains no Git metadata or OCI revision labels. Source SHA-256 evidence:

| File under `/opt/hermes` | SHA-256 |
| --- | --- |
| `run_agent.py` | `633c968343fe4c54f8f81a07a67bbc753deb0e3cc64ef87c1aa49d053a76ebc9` |
| `tools/registry.py` | `f73137030e95b47b92702f935d95f2cd01740b61161d7d940d6c83f02401294d` |
| `model_tools.py` | `d1da6f6d7346ca7c9a4eb67337056492bdc219dc55fb1df7cb1f49cd189a94aa` |

The pinned registry accepts `register(name, toolset, schema, handler)` where `schema`
is the function body and `handler(args)` returns a JSON string. Hermes's tool
executor calls `model_tools.handle_function_call`, then `registry.dispatch`.
`AIAgent` accepts iteration/token/runtime bounds and has `close()` cleanup.

Three important pinned behaviors are handled explicitly:

1. Progressive tool search otherwise replaces custom tools with three generic bridge
   tools. `tools.tool_search.enabled: off` preserves the exact canonical surface.
2. Schema sanitization adds empty `properties`/`required` to a bare arguments object.
   The provider accepts only that precise benign normalization, not arbitrary schemas.
3. A script mounted as `/policy/operator.py` shadows Python’s standard-library
   `operator` during startup. Compose mounts the source as `/policy/hermes_operator.py`
   instead; do not replace those individual binds with a whole-directory policy mount.

## Local verification without live credentials

Ordinary policy and unchanged fallback checks:

```sh
python3 -m unittest discover -s tests -p test_hermes_operator.py
python3 -m unittest discover -s tests -p test_hermes_provider.py
docker compose -f ops/hermes/operator.compose.yaml config --quiet
```

The host suite explicitly skips real-image proof unless requested. Run the actual
pinned SDK fixture from the repository root with no external network or secrets:

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

The fixture does **not** substitute a fake AIAgent: it substitutes only the fixed
provider's HTTPS upstream transport with deterministic OpenAI-shaped responses. Real
loopback HTTP servers exercise the operator provider policy and broker. Assertions
require claim → call → finish, exactly two model requests, a broker marker in the
second request's tool-result message, the final answer, absence of credentials from
model input, and absence of customer fixture content in SDK-created files.

## Compose integration, not activation

`operator.compose.yaml` expects the external app network `jardines_app`. Local dev
can explicitly set `JARDINES_APP_NETWORK=jardines-crm-local_app`. The secret file
path can be supplied with `HERMES_OPENAI_SECRET_FILE`; its default is the existing
production provider-secret location. Compose parsing does not read the key or
activate services. Do not bring this stack up or copy credentials to a destination
without explicit owner authorization for that destination and operation.
