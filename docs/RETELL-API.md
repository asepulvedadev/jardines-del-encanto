# Retell API policy adapter

Retell is a separate connection shared by the CRM and Sara/Hermes. This adapter
never exposes the provider API key to either surface. All external invocations,
including vendor reads, become exact-action broker proposals first.

## Wiring

Include `app.retell.routes.router`. Register these broker models:

- `retell.catalog`: `control.models.Empty`, read-only discovery.
- `retell.schema`: `retell.models.SchemaBrowse`, read-only compact schema paging.
- `retell.execute`: `retell.models.Execute`, **never a read action** even when the
  selected Retell operation itself is read-only.

For execution, append `service.freeze(db,args,admin)` to the proposal revisions.
The frozen keys are `connection:retell`, `provider:retell`, `retell:schema_hash`,
`retell:requires_consent`, and `retell:risk`. The normal connection revision guard
still runs. The latter four keys are validated by Retell preflight and must not
be compared to ordinary capability versions.

On human approval, call `service.prepare(db,row,args,admin,consent_confirmed)`
**inside** the broker reservation transaction. Commit the approved/consumed state
before calling `service.execute_reserved(payload,admin)`. An exception after
reservation is an uncertain external outcome, not permission to retry. Normal
broker audit must include consent only from the authenticated human approval,
never a model argument.

The shared connection enable handler must require `state()` to report all of
`available`, `configured`, and `verified`. Migration `011_retell.sql` creates the
connection disabled and adds a separately owned/session-bound one-shot claim
ledger. No provider key or transient session token is stored in PostgreSQL.

## Authenticated routes

All routes inherit CRM administrator sessions, mutation Origin/CSRF checks,
private/no-store headers and request-body limits.

| Method | Route | Input/result |
| --- | --- | --- |
| GET | `/crm/retell/settings` | Sanitized gateway state plus enabled preference |
| POST | `/crm/retell/settings` | `{revision,api_key?,defaults?}`; password is write-only |
| POST | `/crm/retell/disconnect` | `{revision}`; disables connection and bumps version |
| POST | `/crm/retell/catalog` | `{revision}`; reviewed operation metadata/discovery |
| POST | `/crm/retell/schema` | `{revision,endpoint}`; reviewed input schema for UI |
| POST | `/crm/retell/sessions/{proposal_id}/claim` | `{}`; owner/session one-shot access token |

`SchemaBrowse` takes `{endpoint,path?,offset?}`. `path` is a JSON Pointer into the
input schema. Each response summarizes one level and at most sixteen fields under
12 KiB. Composite `items`/`oneOf`/`anyOf`/`allOf` branches are advertised for further
inspection; large schemas are not silently represented as complete forms.

## Fixed private gateway

Only `http://retell-gateway:8093` is accepted in production. Development loopback
requires `CRM_ALLOW_INSECURE_HTTP=1`. `RETELL_GATEWAY_TOKEN_FILE` contains a dedicated
internal service token; it is not the vendor API key. No redirects, inherited HTTP
proxies, arbitrary routes, or user-supplied base URLs are accepted.

The packaged `app/retell/registry.json` must be an exact copy of the reviewed gateway
registry. The API never derives risk or consent from mutable MCP descriptions.
Unknown operations fail closed. Five multipart operations remain visibly
unavailable until an owned-file adapter exists. Future discovered operations
remain disabled until reviewed. Catalog/schema reads are metadata operations;
they do not prove account quota, agent readiness or international phone routing.

## Outreach and session rules

`createPhoneCall`, `createSmsChat`, and `createBatchCall` require explicit
`contacts:[{contact_id,expected_phone}]`. The set of argument destinations must
match exactly, without duplicates, and current CRM phones are checked again under
shared row locks during approval. Raw recipients without contacts are rejected.
The integration has no confirmed Colombian originating route, so `+57` outreach
fails with `retell_route_confirmation_required`; it does not imply universal Retell
US-only support. E.164 bypass is not permitted.

Every non-read operation requires the human consent checkbox. Read invocations
still require proposal approval, but no extra consent checkbox. Sensitive argument
fields (headers, auth configuration, credentials, tokens, keys) are rejected before
proposal/audit persistence. Credential provisioning operations requiring those
fields are therefore not fully usable through this broker even when cataloged.
Provider outputs are recursively redacted and bounded before storage.

`createWebCall` returns only a safe session reference. The ephemeral access token
is obtained through an authenticated owned/session-bound claim route, reserved in
PostgreSQL **before** calling the gateway. A failed claim stays consumed. No token
enters broker output, conversation, audit or database. Real SDK microphone/call
execution is a distinct manual, consented, potentially billed operation.

## Verification

`test_retell_unit.py` is pure and makes no account/database calls. `test_retell.py`
uses the existing guarded `jardines_crm_test` fixture and fake gateway responses;
run it serially with other database tests because those fixtures truncate shared
test tables. They test authentication, Origin/CSRF, limits, inactive connections,
read approvals, extra mutation consent, revision/schema drift, exact contacts,
uncertain dispatch, private session ownership and one-shot claims. No real vendor
request, key creation, customer outreach or paid operation is part of this suite.
