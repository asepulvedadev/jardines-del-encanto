# Application control plane

The API is the authority for typed local capabilities, extension definitions and
connection preferences. The shared wire contract lives in `SETTINGS-HERMES.md`.
Neither creating an extension nor setting a preference installs host code or grants
an upstream account. All CRM human routes remain independent of automation toggles.

## Definitions and execution

- Skills provide Markdown context to Hermes; they are not executable tool actions.
- Tools alias one canonical action, merging stored defaults with supplied arguments.
  At most one tool item overrides each canonical capability's automation preference.
- Plugins and application connections expose an action subset. Run with
  `arguments: {action: "crm.workspace", arguments: {limit: 10}}`.
- Scripts execute one to eight fixed typed steps. Run with empty arguments. Read steps
  return results; write steps produce individually reviewable, exact-action proposals.
  They cannot interpolate code, execute shell/Python or access arbitrary URLs.

Unknown actions may be stored disabled, never enabled. Strict Pydantic models validate
all definitions and every dispatch. Item and connection updates require their current
optimistic version. The registry is limited to 200 items. Definitions are bounded to
65,000 UTF-8 JSON bytes; skill content remains limited to 16,000 characters. HTTP item
creation/edit is bounded to 64 KiB before parsing; other human control mutations use
16 KiB. Internal bridge bodies use 64 KiB. All private responses are no-store.

Operator workspace reads accept query, limit (default 50, maximum 100) and offset.
They report the 500-contact snapshot boundary, filtered match count, pagination and
whether more data may exist; human workspace behavior is unchanged.

## Confirmation and consistency

Automation writes store normalized arguments, initiating actor/session, expiry and
capability/parent-item revisions. Approval only accepts proposal ID and version;
arguments cannot be replaced. A PostgreSQL advisory transaction lock serializes
registry changes and permission/revision checks. Proposal row locks and consumption
in the same transaction as shared CRM service writes prevent double application.
Human edits still use existing optimistic record versions. A conflict preserves the
pending proposal and all stored CRM data; rejected or expired proposals cannot apply.

External social actions cannot participate in a PostgreSQL transaction. Approval
therefore commits a once-only dispatch reservation before contacting the existing
bounded adapter. Concurrent approvals cannot dispatch twice. A crash or uncertain
provider result remains consumed and non-retryable; it is not labeled successful.
There is no exactly-once claim about an upstream provider or a generic retry loop.
An administrator can inspect the real upstream status before explicitly initiating a
new action. Social pauses block new sync/connect/OAuth-start work, not settings edits,
status, disconnect or completion of an already-bound authorization callback.

## Hermes identity and transport

Hermes is disabled initially and cannot be enabled without a reachable configured
bridge. The only normal destination is `http://hermes-bridge:8081`; explicit loopback
HTTP ports support isolated local tests. Redirects and ambient HTTP proxies are
rejected. Health and inference failures return opaque unavailable errors, never a
fabricated answer. Provider credentials are never part of the API registry or broker.

Chat issues a random 256-bit service token stored only as SHA-256, valid for 120
seconds and bound to one initiating live administrator session. It is passed only to
the private bridge. Claim is single-use. Claims persist the allowed action keys and
custom-item revisions in the audit log; later calls cannot expand that run's scope.
Every call rechecks the live session, admin state, effective capability and revisions.
A run permits at most 12 calls, including application-validation failures. Successful
and rejected calls are deduplicated by call ID and exact request; a different request
with a reused ID conflicts. Finishing closes the run to further calls. Logout revokes the token via the live-session
join while retaining run, proposal and audit history.

One canonical OpenAI function, `jardines_app`, takes action and arguments. Its description
contains compact argument schemas and effective custom definitions, capped at 16 KiB
UTF-8. An oversized selected catalog fails closed rather than silently hiding actions.
Enabled skills and plugin instructions are separate claim context. Cached call results
share a cumulative 64 KiB UTF-8 budget; an oversized dispatch rolls back its pending
proposals and returns an explicit error rather than truncating results. The pinned Hermes
operator must execute this broker tool; the API only returns the durable finished
run, not a bridge-supplied canned response. The existing restricted text CLI remains
separate. No browser response contains the service token or provider secrets.

## Local verification

`npm run test:crm` uses the existing isolated `jardines_crm_test` runner and checksum
migration machinery. Tests import the guarded administrator fixture; global connection
preferences are explicitly restored around control tests. They cover authentication,
CSRF, strict definitions, Unicode bounds, optimistic conflicts, parent/toggle
revocation, script/plugin runs, approval races, uncertain external dispatch, bearer
claim/replay/expiry/revocation, budgets and deterministic bridge handoff. The operator
runtime's separate deterministic pinned-Hermes fixture supplies SDK execution proof.
No production activation, paid inference, global plugin install or remote operation is
part of these tests.
