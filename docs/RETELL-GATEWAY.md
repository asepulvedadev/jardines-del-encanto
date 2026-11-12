# Reviewed Retell MCP gateway

The CRM and Sara share one credential-isolated Retell gateway. Production activation is an
explicit operator step, not a side effect of an application release. Installing the root-owned overlay,
creating its private volume/token, configuring a vendor key, and deploying it
require separately authorized operator work. No provider account was modified,
no call was made, and no paid vendor test was performed during implementation.
See `RETELL.md` for the subsequent owner-authorized production activation.

## Scope and provenance

- Fixed upstream: `https://mcp.retellai.com/`, authenticated with the private key.
- Official public OpenAPI: `https://docs.retellai.com/openapi.yaml`, SDK 3.0.0,
  spec revision `2026-11-12-f8c7226`, 112 operations reviewed on 2026-11-12.
- `ops/retell/registry.json` is the explicit operation/risk allowlist. Its JSON
  object is keyed by endpoint ID; entries have `endpoint`, `method`, `path`,
  `summary`, `group`, `risk`, `available`, optional `blocked_reason`.
- `ops/retell/schemas.json` pins the exact public MCP `get_api_endpoint_schema`
  input schemas for the same 112 operation IDs, downloaded without credentials
  with concurrency three. The OpenAPI and two previously captured MCP schema
  examples were cross-checked. This avoids assuming OpenAPI references expand in
  the same way as the live MCP server.
- `ops/retell/provenance.json` records public artifact hashes and source details.
  `registry_revision` hashes the checked-in registry and schema file bytes.
  Every action's `schema_hash` additionally covers its strict input schema.

Five multipart operations are visible but blocked with `requires_file_adapter`:
`addKnowledgeBaseSources`, `createAsset`, `createKnowledgeBase`, `cloneVoice`,
`uploadContactImportFile`. A reviewed file-staging adapter is required before
these can run. Future upstream operations are discovery-only and never become
executable automatically. Dashboard-only Dialer, Conductor, QA, alerts, webhook
signature verification, and billing administration are not claimed as API
features. Existing Retell agents can use those vendor capabilities where supported;
this adapter does not invent unavailable APIs.

## Private HTTP contract

The service listens on internal port 8093; no host port is published. All routes
except `GET /health/live` require the root-installed service bearer token:

| Route | Request | Response |
| --- | --- | --- |
| `GET /state` | none | configured, verified, revision, key suffix, defaults |
| `POST /configure` | revision, optional api_key/defaults | public state |
| `POST /disconnect` | revision | public state |
| `POST /catalog` | revision | registry revision, operations, new-operation metadata |
| `POST /schema` | revision, endpoint | strict input schema, hash, metadata |
| `POST /prepare` | revision, endpoint, arguments | hash, risk, requires_consent |
| `POST /execute` | revision, endpoint, arguments, request_id, expected_schema_hash, consent_confirmed | sanitized result or unknown outcome |
| `POST /sessions/<UUID>/claim` | revision | one-shot access_token |

Defaults are `agent_id`, `chat_agent_id`, and E.164 `from_number`; they are hints,
not an authorization bypass. The API owns exact CRM-contact phone binding and
human approval; the gateway separately checks non-read consent. Neither a model
argument nor a default proves consent. Retell-managed +57 origination requires a
separate reviewed routing decision in the API, not an unchecked action parameter.

## Safety boundaries

- Fixed literal TLS host/SNI and vetted public DNS addresses. DNS has bounded
  worker slots and a two-second wait; no redirect, environment proxy, alternate
  base URL, fallback host, or automatic retry is supported.
- Each MCP exchange initializes a bounded independent session, negotiates only
  reviewed protocol versions, and uses only the three official meta-tools.
  Authenticated invocations accept the observed `API Response (Status: 2xx):`
  wrapper only with a complete JSON body; discovery can remain plain JSON.
  JSON and SSE RPC responses have strict IDs, duplicate-key rejection, response
  MIME/encoding limits, a 4 MiB ceiling, and a 25-second whole-call deadline.
- Local strict JSON Schema validation closes declared objects while preserving
  explicit arbitrary-property maps. No external schema reference is allowed.
  Execute re-fetches the public operation schema and compares its validation
  structure to the pin before dispatch. Documentation-only schema changes do
  not change validation; new fields or constraints fail closed.
- Credential/header/token arguments are blocked recursively. URL parameters are
  limited to HTTPS/WSS, no embedded credentials, no credential query parameters,
  public-looking ASCII hosts, public literal addresses, and default TLS ports.
  Callback hostnames are not resolved or fetched by this gateway; this cannot
  guarantee Retell's own callback DNS/redirect behavior. Operators must use
  trusted callback destinations, and schema pinning does not establish trust in
  arbitrary vendor-hosted integrations.
- All `invoke_api_endpoint` actions, including reads, durably reserve their UUID
  before dispatch. A private fsync/rename journal and process/thread locks retain
  tombstones across restart, disconnect, and key changes. Capacity is 10,000;
  exhausted storage stops new invocations rather than erasing deduplication.
  Credential verification is the explicit configure operation's bounded
  `getApiKeyInfo` read, not a user action dispatch.
- Failures after reservation are `external_outcome_unconfirmed`, `retryable:false`.
  Do not replay with a new UUID until an operator independently resolves the
  provider outcome. This prevents local automatic replays; it cannot make an
  external vendor transaction exactly-once.
- Responses redact nested secrets, credentials, headers, token fields, ICE,
  recognized key/JWT strings, the active key even inside other strings, and signed
  or credential-bearing links. Safe output is depth/item/text/byte bounded.
  Raw vendor errors are never returned or logged.
- `createWebCall` returns only a private-session UUID and optional call ID. Its
  access token remains in process memory, is claimable once for five minutes,
  and is never written to the journal or returned to chat/audit. Expired entries
  are rejected and purged at the next session operation; disconnect or key
  change clears them. A process restart loses unclaimed tokens by design.
  Five minutes limits token claiming, not vendor billing/call duration.
- The CRM/API must bind that UUID to its approved proposal owner and browser
  session. The internal service bearer alone is not an end-user authorization
  mechanism. Microphone use and call start require separate user interaction.

## Runtime installation contract

`ops/retell/compose.yaml` is an administrator-installed overlay at
`/srv/jardines-del-encanto/retell-policy/compose.yaml`. Bind-mount the reviewed
`gateway.py`, `registry.json`, and `schemas.json` from that same root-owned policy
directory. Do not load policy from a mutable application release or dashboard.
The release API image must include `jsonschema` before this overlay is activated.

The gateway runs UID/GID 10001, read-only, all capabilities dropped, bounded CPU,
192 MiB memory, 32 PIDs, bounded logs, and a small noexec tmpfs. Only it joins
`retell_egress`; the API joins internal `retell`. Neither the API nor Hermes mounts
the vendor-key volume. Create `jardines_retell_config` with ownership 10001:10001
and mode 0700 using a separately reviewed installer. The only API credential is
`/srv/jardines-del-encanto/secrets/retell-gateway.token`, mounted read-only. Never
reuse the ElevenLabs service token or volume.

Root deployment must retain optional overlays through normal activation and
rollback. A rollback image without the Retell dependency cannot start this gateway;
use a compatibility release before migration/activation. Preserve unrelated
containers, Nginx, CRM data, operator flags, and provider secrets.

## Focused verification

```sh
python3 -m unittest discover -s tests -p test_retell_gateway.py -v
```

Tests use injected fake MCP transports and loopback HTTP, never account credentials,
paid calls, production sessions, or databases. Public schema downloads are research,
not evidence that any particular account has every feature or permission.
