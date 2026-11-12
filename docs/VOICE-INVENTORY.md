# Automatic Retell inventory and exact reads

The owner explicitly authorized automatic resource loading on the Voz page. These
narrow endpoints implement that read-only exception; they do not approve Hermes
proposals or enable automatic writes, paid calls, destructive or security operations.
Provider credentials and deployment remain outside this feature's scope.

## Public API

Both routes require the existing administrator session, exact origin and CSRF token.
They reject query parameters, extra fields, missing/invalid JSON and noninteger or
negative revisions. The CRM BFF allows only their exact POST paths and preserves
private/no-store responses and its existing 16 KiB body bound.

`POST /crm/retell/inventory`, body `{ "revision": 7 }`:

```json
{
  "snapshots": [
    {
      "endpoint": "listAgents",
      "provider_revision": 7,
      "created_at": "2026-11-12T12:00:00+00:00",
      "data": [{ "agent_id": "illustrative-agent" }]
    }
  ],
  "partial": true,
  "errors": [{ "endpoint": "listVoices", "code": "retell_read_unavailable" }],
  "cached": false
}
```

The fixed eleven inventory operations, in response order, are `listAgents`,
`listVoices`, `listCalls`, `listPhoneNumbers`, `listKnowledgeBases`,
`listTestCaseDefinitions`, `listRetellLLM`, `listConversationFlows`, `listChats`,
`listContacts` and `listApps`. Each receives an empty argument object. There is no
caller-controlled operation list, refresh loop or provider pagination traversal.

`POST /crm/retell/read`, body:

```json
{
  "revision": 7,
  "endpoint": "getAgent",
  "arguments": { "agent_id": "illustrative-agent" }
}
```

It returns `{ "provider": "retell", "status": "completed", "endpoint": "getAgent",
"data": ... }`. Only the eleven list operations above and `getAgent`, `getVoice`,
`getCall`, `getPhoneNumber`, `getKnowledgeBase`, `getTestCaseDefinition`,
`getRetellLLM`, `getConversationFlow`, `getChat`, `getContact`, `getApp` and
`listAgentVersions` are admitted. Caller URLs, token/credential/header fields,
consent fields, paid endpoints and all other operations are rejected before provider
access. Arguments retain existing depth/size/finite JSON constraints and are further
bounded to 12,000 serialized bytes. A provider-reviewed schema validates field names,
locations and values; this is not a generic provider proxy.

## Policy and state boundaries

Every operation must still be available and `risk=read` in the packaged reviewed
registry. Requests reuse existing schema preflight, prepare, execute validation and
`safe_result` sanitization. No `hermes_proposals` record is created or approved.
Existing writes and paid actions keep their exact broker proposal/consent flow.
The unchanged `GET /crm/retell/results` recovers approved broker snapshots locally;
it never initiates these automatic reads or returns this process-local cache.

Each read rechecks the current enabled connection version and live actor/session
before dispatch and after network completion. Provider revision and schema hash
are checked before execution, at gateway dispatch and after completion. A global
connection/provider/schema/session change fails closed rather than publishing stale
data. The dedicated `retell.automatic_read` audit records prepared/completed endpoint,
provider revision, connection version and stage only, never arguments or provider
payloads. Prepared audits commit before the external read.

`safe_result` applies its existing sensitive-key, depth, string and 50-item list
bounds. Results must also remain finite JSON and at most 16 KiB per resource after
sanitization. Snapshots are always explicitly partial, not live account totals.
A failed/unavailable resource produces a bounded error code without erasing the
other successful resources. Raw provider exceptions are never included.

## Cache, concurrency and deadlines

- Successful snapshots use a process-local 30-second LRU cache with at most 128
  combined cached/in-flight keys. Keys include actor, session hash, connection
  version, provider revision and an actor/session-only completed non-read proposal
  watermark. The watermark includes both count and newest proposal creation time,
  so an older proposal completing later also invalidates the cache.
- A completed broker write/delete makes the previous inventory key ineligible.
  Pending proposals, other actors and other sessions do not invalidate this cache.
  New login, preference changes and provider revision changes cannot reuse it.
- Concurrent requests with the same key share one flight. Responses are copied so
  consumers cannot mutate cached snapshots. Provider/session/version/watermark
  checks also apply when returning cached/shared snapshots.
- A new explicit load retries missing resources once, preserving successful cached
  snapshots without extending their original expiry. There are no background retries.
- One shared executor has three workers; a process-wide semaphore caps automatic
  read concurrency at three, including direct reads. Admission bounds the executor
  to 33 running/queued jobs. Every worker owns its DB connection contexts.
- Individual reads have an 18-second phase deadline. Local prepare calls use at most
  1.5-second transport timeouts; actual reads can use up to 8 seconds, limited by the
  remaining budget. Existing provider-state checks retain their 3-second timeout.
- Inventory collection has a 64-second absolute wait deadline, leaving budget for
  final state checks within the existing 95-second BFF timeout. Pending jobs are
  cancelled; already-running read-only transports remain in the bounded shared pool
  until their own timeout. Responses never wait for per-request executor shutdown.
  Jobs that start after the deadline initiate no provider work. Slow DB operations
  retain the existing connection/statement limits; these are operational timeout
  budgets, not a hard real-time guarantee under arbitrary OS or DB stalls.

The cache is neither distributed nor durable. Multiple API processes can perform
independent fixed reads; it never coordinates writes. No migration, dependency,
provider registry or gateway policy is changed.

## Verification

Pure, mocked checks:

```sh
apps/api/.venv/bin/python -m pytest -q -c apps/api/pyproject.toml apps/api/tests/test_voice_inventory_unit.py
node --test tests/web/voice-inventory-gateway.test.mjs
```

`apps/api/tests/test_voice_inventory.py` contains guarded local DB cases for the
existing isolated CRM runner. Run DB suites serially; tests use a fake gateway and
never paid calls, microphones, provider credentials or production data.
