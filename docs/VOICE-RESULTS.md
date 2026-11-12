# Approved Retell result snapshots

`GET /crm/retell/results` is an authenticated, local recovery endpoint for the Voz
workspace. The CRM BFF admits exactly `GET /api/crm/retell/results`; queries, request
bodies, arbitrary neighboring paths and other methods are rejected. Responses are
`Cache-Control: no-store, private` and follow this shape:

```json
{
  "snapshots": [
    {
      "id": "00000000-0000-4000-8000-000000000001",
      "endpoint": "listAgents",
      "created_at": "2026-11-12T12:00:00+00:00",
      "provider_revision": 7,
      "data": [{ "agent_id": "illustrative-agent" }]
    }
  ],
  "partial": true
}
```

## Approval and isolation

This GET never invokes the gateway, bridge, vendor, model, preflight or broker.
External resource reads still require an explicit proposal and approval through
`retell.execute`, including read-only operations. This route only recovers approved
results; it does not refresh resources or execute proposals.

The SQL query binds both the current administrator's actor ID and session hash,
`action=retell.execute`, proposal status `approved`, result provider `retell`, result
status `completed`, and equal argument/result endpoints. Only operations in the
packaged reviewed registry with `risk=read` and `available=true` are returned.
Pending, rejected, expired, mutating, ready and uncertain outcomes do not qualify.
A new login cannot recover the previous session's results.

An enabled `control_connections` Retell preference is required. Its current DB
version must equal the proposal's frozen `connection:retell` JSON number. Missing
or disabled preferences produce an empty partial response. Configuration, defaults,
key and enablement changes invalidate old snapshots through that version boundary.
The returned `provider_revision` is the nonnegative integer frozen in
`provider:retell`; GET does not contact the gateway to look up its current revision.
The frontend must compare it with separately fetched `settings.revision` before
showing the snapshot. Provider state outside the DB cannot be inferred locally.

## Deliberate partiality and redaction

The ordered SQL scan considers at most the newest 96 qualifying rows, returning
only the latest valid snapshot per endpoint and at most 32 endpoints. It does not
merge records by agent/resource ID, paginate the provider inventory or guarantee
that an older endpoint exists within this bounded scan. `partial` is always true,
including empty responses. A latest-per-endpoint resource lookup may replace an
earlier lookup of a different resource; callers must not present a full inventory.

Every restored data value passes through `retell.service.safe_result` again.
Existing depth, string, sensitive-key and 50-item list bounds apply; values that
cannot be serialized as finite JSON or exceed 16 KiB after sanitization are skipped.
Malformed historical rows are skipped without echoing raw exceptions. The response
never includes full proposal arguments, revision maps, session material or raw
provider errors. Credential redaction is key-based defense in depth, not a claim
that arbitrary free text is a secure secret store.

## Local verification

Pure API and BFF checks (no database or provider calls):

```sh
apps/api/.venv/bin/python -m pytest -q -c apps/api/pyproject.toml apps/api/tests/test_voice_results_unit.py
node --test tests/web/voice-results-gateway.test.mjs
```

`apps/api/tests/test_voice_results.py` uses the existing guarded
`authenticated`/`retelled` fixtures and fake gateway. Run it only through the local
isolated CRM test runner, serially with other database suites. The fixture refuses
to reset databases not named `jardines_crm_test`. No production execution, real
provider read/write, credentials, paid call or microphone access is needed.
