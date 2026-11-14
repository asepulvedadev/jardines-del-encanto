# Approved workflow runtime

Local-only sequence execution is separate from browser sessions and Sara proposals.
Apply additive migration `012_workflows.sql` using the privileged migration role.
The normal `jardines_crm_app` role may insert immutable run snapshots and grants,
but may update only run status/version/start time. It cannot rewrite snapshots,
recipients, fingerprints, grant approvers or grant expiry. No credential is stored
in workflow plans; provider identity hashes/revisions are private frozen metadata.

## Opt-in operation

The worker is **off by default**. Explicitly set
`CRM_WORKFLOWS_WORKER_ENABLED=1` with the normal `CRM_DATABASE_URL` only in an
authorized environment, then start the API. Startup starts one process-local
worker thread; shutdown signals its stop. Readiness requires a live worker and
recent successful schema/database probe. Saving/preparing never starts workers.
Activation rejects unavailable workers, even for CRM-only sequences.

The API never applies migrations on startup. Migration privileges and schema
version must be provisioned separately. No production activation, provider call,
root policy, configuration or deployment is implied by this implementation.

## Review and authority

Definitions are versioned DAGs with at most20 reachable nodes. Reviews freeze
at most50 existing contacts, all content, bindings, sender/provider revisions,
schedules and limits. Synchronous provider review is bounded to10 external
contact×node plans and a60-second preparation/check budget; CRM-only audiences
may use50 contacts. An over-budget review returns
`workflow_provider_review_limit` or `workflow_review_budget_exceeded` and creates
no grant. Provider options are fixed reviewed reads, never unrestricted URLs.

The human must approve the exact fingerprint with consent within10minutes.
A changed draft invalidates pending review. Approval inserts a separate grant
bound to the immutable run, administrator and fingerprint for at most30days.
The worker rechecks grant expiry, enabled administrator, recipients and connection
revisions. It never creates or pretends to have a browser session. Logout does
not revoke the independently granted run; disabling its administrator does.

`days` uses ISO weekdays1=Monday through7=Sunday. Timezone is America/Bogota;
start is inclusive, end exclusive, and overnight windows are rejected. Daily
external-action limits are1..100 (default20), reserved actions count even if the
provider result is unknown. Total external actions cannot exceed the approved
contact×external-node count. Conditions read current CRM source/stage; missing
state holds the run instead of selecting false.

## Dispatch semantics

Claims lock run state and use `FOR UPDATE SKIP LOCKED` due cursors, with a unique
run/contact/node reservation. The reservation commits **before external send**. Schedule time is refreshed after
provider validation and again at the final predispatch check. Closing before reservation
defers the cursor; closing after reservation holds that action without dispatch or retry.
Only one node per recipient advances per tick; wait offsets persist in due_at.
CRM notes/tasks reuse the existing CRM service helpers in the same transaction.
Retell reuses freeze/prepare/execute_reserved and preserves the +57 route block.
Provider submission is recorded separately from delivery, answered call or sale.

A crashed reservation expires after180seconds and becomes unknown. Unknown or
failed external actions are held and **never replay automatically**. The operator
must inspect provider history and prepare a new explicit review; resume cannot
reset a held reservation. Provider errors are opaque and never persisted raw.

Pause/stop prevents new claims, but cannot promise cancellation of a request
already reserved or in flight. An immediate predispatch grant/state check narrows
this race without holding a database lock during sending. A late receipt never
reactivates a stopped run. Shutdown prevents new iterations; an in-flight vendor
request may finish before its timeout and is subject to the same reservation rule.

Authenticated Zernio webhooks reach stop-on-reply only after current HMAC,
header consistency and successful first deduplicated insert. Exact frozen
profile/account/conversation/participant/platform plus post-start incoming time
must match. For a newly opened WhatsApp template thread, the exact reviewed
phone participant and sender must match after reservation, with receipt conversation
identity also required when the provider supplied one; unauthenticated, replayed, test or ambiguous events cannot stop a run.
Sara has typed reads and exact draft/pause/stop proposals through the existing
broker; no prepare, activate, generic-execution or authority-grant tool exists.

## Local verification

Pure policy tests: `cd apps/api && .venv/bin/pytest -q tests/test_workflow_worker.py`.
Guarded integration tests: `tests/test_workflows.py`, using only isolated
`jardines_crm_test`, fake providers and the existing guarded authenticated fixture.
Run database suites serially; the fixture truncates test users/contacts.
The parent verification runner owns test database URLs and migration application.
No real customer, provider credential, paid send or live provider is required.
