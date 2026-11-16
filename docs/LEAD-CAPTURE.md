# Temporary inbound lead safety net

The owner authorized this production capture on November 16, 2026. It is independent
of Sara/Hermes, reply generation, workflow activation, calls and message delivery.

## Execution

- The existing HMAC-authenticated Zernio webhook attempts deterministic intake inside
  a savepoint. A broken reply-agent enqueue cannot discard the signed receipt or lead.
- An API lifespan worker runs a repair sweep every 60 seconds. This is a persistent
  in-process scheduler, not a per-message operating-system cron. It restarts with the
  container and requires no open browser or Codex session.
- It lists active and archived conversations, plus Facebook inbox and request folders.
  Opaque cursors, unfinished history, retry state and identity candidates are durable
  in PostgreSQL. At most one list page per folder is fetched per minute and 20 queued
  history pages are processed per batch. Backlog/outage can exceed a minute; no strict
  delivery-time or provider-retention guarantee is implied.
- Only existing GET inbox operations can reach Zernio. It never marks messages read,
  sends replies, joins sequences, changes thread control or calls an AI model.
  Existing separately configured Sara/onboarding replies retain their own authorization;
  deploying this safety net does not activate or reconfigure them.

## Explicit scope

The application policy allowlists only the verified Jardines WhatsApp account and
the shared Grupo Pumax Facebook account in `social/lead_capture.py`. Account ownership
is reverified against the currently configured Zernio profile and channel preferences.
Casanova WhatsApp and all other accounts are excluded.

Shared Facebook contacts need incoming evidence naming Jardines del Encanto or the
owner's current November 22 fair form (`Full name:` and `Phone number:` labels).
Unknown project/phone/name stays in the intake ledger for completion; explicit
other-project inquiries cannot create a Jardines contact. Replace the temporary fair
marker when the campaign changes; do not broaden it to every shared-profile thread.
Internal operator numbers are excluded from acquisition.

Only incoming, sender-matching records are parsed. Self-declared labeled form fields
take precedence over WhatsApp display names and sender numbers. Arbitrary numbers in
message prose, Facebook numeric participant IDs, and WhatsApp `CO…` identifiers are
never converted into telephone numbers. Content is inert, never instructions.
Missing identity is not replaced by fabricated names or telephone numbers.

Contact/deal creation and the intake record commit atomically, protected by the
existing unique normalized phone constraint. Concurrent/manual/webhook/poll duplicates
reuse the contact and preserve its name, source, version and existing deal stage.
New contacts enter `Nuevo`; existing won/contacted deals are never reset. A real,
enabled CRM administrator is required for creation activity attribution.

## Operation and recovery

`CRM_LEAD_CAPTURE_ENABLED=0` disables webhook intake and polling. The authorized
release defaults to enabled only when `CRM_ORIGIN=https://jardinesdelencanto.site`;
other environments default off. `CRM_LEAD_CAPTURE_ACTOR` defaults to `adminjardines`.
An unavailable actor retains pending work instead of bypassing attribution.

Authenticated, no-store `GET /crm/inbox/lead-capture` exposes heartbeat, registered
conversation/pending/error counts and per-folder sweep results without names, phone
numbers or content. The CRM Inbox displays this status and refreshes it each minute.
“Registered” counts conversation links, not unique customers.

Migration `021_lead_capture.sql` is additive. Use the existing tested main/CI gate,
migration role and health checks; never edit an applied migration. Rollback restores
the previous image and stops the worker; leave the additive ledger intact. No existing
contact, deal or signed receipt is deleted.

## Verification

Use isolated `jardines_crm_test` through `ops/dev/crm.py test`. Focused tests cover
identity precedence, opaque IDs, incoming/scope checks, concurrent replay, preserving
won deals, pending identity recovery and GET-only polling. Signed webhook, workflow
stop-on-reply and inbox/gateway suites remain required. Never send synthetic customer
messages or create synthetic production contacts to test intake.
