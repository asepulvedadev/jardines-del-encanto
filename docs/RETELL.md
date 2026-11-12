# Retell AI integration

## Status and scope

The owner-authorized production connection was activated on 2026-11-12. Retell appears
under CRM Settings > Connections, independently of Zernio social channels. Sara uses
three compact application actions: `retell.catalog`, `retell.schema`, and
`retell.execute`. Execution always creates an exact, owner/session-bound human
approval proposal, including read operations. Enabling a key does not make paid
calls, synchronize customers, provision phone numbers, or publish agents.

The reviewed catalogue contains **112 official API operations**, pinned from Retell's
2026-11-12 OpenAPI/MCP revision. The adapter supports reviewed JSON inputs; five
multipart operations are visible but disabled pending a dedicated file adapter:
`addKnowledgeBaseSources`, `createAsset`, `createKnowledgeBase`, `cloneVoice`, and
`uploadContactImportFile`. Large or credential-bearing inputs may be rejected by
local policy; catalogue visibility is not an unconditional execution grant.
The basic UI handles one outbound CRM recipient; complete batch recipients require
explicit bindings through Sara's broker. Never advertise a complete dashboard clone.

Retell's dashboard-only Conductor, current Dialer, alerts and QA interfaces are not
implemented here. No webhook ingestion or automatic lead synchronization is enabled.
A future webhook adapter requires raw-body signature verification using the actual
Retell webhook-badge key, deduplication and a separately authorized callback URL.

## Available API families

- Voice/chat agents, versions and publishing; Retell LLMs and conversation flows.
- Phone/web calls, call/chat history, monitoring, live intervention and analysis.
- SMS/chat, contacts, imports and customer conversation history.
- Knowledge bases, voices, test cases, simulations and batch tests.
- Phone numbers, app templates/configuration, CRM configuration and sync jobs.

These are catalogue families, not a statement that the current account has agents,
carrier numbers, credits, permissions or all corresponding configuration. Schema and
permission changes fail closed; newly discovered operation IDs remain unreviewed.

## Credential and execution boundaries

The private Retell gateway alone stores the vendor key. API/Hermes receive a separate
internal service token; the API never mounts Retell private state. Retell networking
has its own internal and egress networks, no published port, a non-root read-only
container, fixed official MCP host, TLS verification, public-address DNS checks, no
redirects and no inherited proxies. Both the API and gateway sanitize credential-bearing
outputs, including tokens inside call reads, custom headers and ICE credentials.

The gateway validates pinned schemas, checks provider/schema revisions, writes durable
per-request reservations before dispatch and never retries ambiguous operations.
The broker commits its own reservation before network I/O. Disabling a connection,
changing a key/schema or editing a bound CRM telephone invalidates pending proposals.
Outbound destinations must match existing CRM contacts and explicit recipient consent.
Other mutating, paid, destructive or security-sensitive operations require an additional
human acknowledgement of their exact scope; model-generated consent is not approval.

Browser call tokens are short-lived, private, one-shot claims for the owning actor and
session. They never enter chat, audit records or database results. Microphone start is
an explicit browser action. The client timer is a convenience limit, not a billing or
provider-side guarantee. The pinned official browser SDK 3.0.4 still exports the legacy
`RetellWebClient` used by this adapter; it is deprecated and must be replaced before an
SDK 4 migration. New public-key/client-side gateway flows are not silently enabled.

**Colombian outreach is not claimed ready.** Retell's published carrier coverage does
not currently list Colombia. This adapter blocks unconfirmed `+57` destinations until
a compatible imported/custom telephony route is explicitly verified and supported.
No payment method, credit purchase, auto-recharge, number purchase, voice cloning,
recipient contact or paid test is performed as part of setup or automated tests.
Retell does not provide a free testing sandbox; web/chat/simulation tests can be billed.

## Local verification

Use fake gateway/MCP/vendor fixtures and the existing isolated PostgreSQL test runner.
Database fixtures truncate `jardines_crm_test`; never run those suites concurrently or
against development/production databases. The runtime unittest suite now uses the
locked API Python environment because the gateway requires `jsonschema`.

```sh
uv run --project apps/api --frozen python -m unittest discover -s tests -v
npm run typecheck
npm run build
npm run test:crm:gateway
# The configured CRM runner must target its guarded local test database only.
npm run test:crm
```

See [RETELL-API.md](RETELL-API.md) and [RETELL-GATEWAY.md](RETELL-GATEWAY.md) for exact
contracts, schema pins, focused tests and known limitations. Fake tests do not prove
live provider quota, audio quality, permission groups or carrier readiness.

## Production activation is a separate authorization

1. Confirm the Retell workspace and authorize a project-specific API key, its precise
   permission groups and storage only in Jardines' gateway. Do not borrow another
   project's key or copy credentials into GitHub, prompts, transcripts or `.env` examples.
2. Before migration011, establish a healthy **compatibility rollback boundary** whose
   connection catalogue ignores unknown provider keys. The pre-Retell b421614
   release cannot render a later `retell` connection row. Do not call that
   old release a fully compatible rollback after adding this migration; migrations are
   not automatically reversed. Preserve backups and an explicit recovery plan.
3. Back up the dedicated project database and capture sibling-container/vhost identities.
   Review/install only the root-owned Retell overlay, registry, schemas, gateway module,
   new private token and empty private volume. Preserve the installed ElevenLabs overlay,
   its private state and active configuration. Never restart shared Docker/Nginx or
   expose a new application port.
4. Build the new API image with locked `jsonschema` before starting the gateway. Deploy
   migration011 using maintenance credentials only; the new connection starts disabled.
   The gate includes an installed fixed Retell overlay for CRM activation and recovery,
   and refreshes only an already-running gateway with compatible Retell release images.
   It deliberately does not auto-start a stopped provider or downgrade the gateway to
   older images that lack its dependency.
5. Install the updated application manifest allowlist in **both** Hermes policy services,
   preserving the active transcription flag and existing model. Observe anonymous401,
   CSRF/body/response bounds, unchanged sibling state and healthy application services.
6. Save the authorized key over HTTPS in Connections > Retell, verify a harmless
   metadata request/catalogue, choose actual account defaults and explicitly enable.
   Any real paid test or customer outreach requires separate explicit consent.

## Production verification (2026-11-12)

The owner authorized a dedicated Retell key, private gateway storage and direct VPS
activation without paid tests. The credential was entered over HTTPS, verified using
`getApiKeyInfo`, and stored only by the gateway. The connection is enabled; the live
catalogue reports 107 JSON operations and five disabled multipart operations. Agent,
chat-agent and originating-number defaults remain unset rather than borrowing another
project's configuration. No agents, numbers, calls, messages or paid tests were created.

Sara's deployed manifest exposes `retell.catalog`, `retell.schema` and `retell.execute`.
Both operator policy services were refreshed with their existing environment, model and
transcription flag preserved. Readiness and the existing ElevenLabs connection were
verified without a model invocation or microphone access.

The actual authenticated MCP invocation wraps JSON as
`API Response (Status: 200):\n{...}`, unlike discovery responses. The adapter accepts
only that anchored 2xx status envelope or complete plain/structured JSON. Error statuses,
arbitrary prefixes, trailing data, duplicate keys and non-finite numbers remain denied.
Diagnostic events contain controlled codes or exception class names, never exception
messages, request payloads, provider responses or credentials.

The healthy pre-migration rollback boundary is
`7b0a307da8b9cd16f0d1edb37ef26345aecc2d89`. Roll back application images through the gate;
retain migration011, the installed overlays and the compatible Retell gateway image.
Do not revert to b421614 after migration011. The private operator checkpoint retains
backups and policy/container/vhost evidence; no credentials belong in this document.

## Local verification (2026-11-12)

- API suite: 263 passed; one existing Starlette/httpx deprecation warning.
- Web gateway/UI suite: 111 passed.
- Runtime suite: 144 passed, one opt-in pinned Hermes fixture skipped.
- TypeScript, production web build, Ruff and whitespace checks passed.
- Independent loopback HTTP and React probes reproduced and then verified fixes for
  composed-schema validation, encoded callback credentials and provider-specific voice controls.
- Browser checks used a loopback-only fake API, never the Retell account. The connection
  editor, enable-state synchronization, 112-operation catalogue and schema fields rendered
  correctly. At 390px the settings dialog had no horizontal overflow.

The isolated tests do not establish webhook ingestion, Colombian carrier routing or
microphone behavior. Production verification was limited to authenticated metadata,
discovery and readiness; paid execution remains deliberately untested.

## Primary evidence (verified 2026-11-12)

- [Official hosted MCP](https://docs.retellai.com/get-started/mcp-server)
- [Official OpenAPI](https://docs.retellai.com/openapi.yaml)
- [Official Python SDK API surface](https://github.com/RetellAI/retell-python-sdk/blob/main/api.md)
- [Official browser SDK](https://github.com/RetellAI/retell-client-js-sdk)
- [Testing charges](https://docs.retellai.com/test/testing-pricing)
- [International calling](https://docs.retellai.com/deploy/international-call)
- [Secure webhooks](https://docs.retellai.com/features/secure-webhook)

The source OpenAPI declares Apache-2.0. Public schema artifacts contain no account
credentials or customer data. The pinned source hash/revision belong with the gateway
registry; refreshing public documentation must not grant new runtime permissions.
