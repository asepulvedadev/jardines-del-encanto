# Unified CRM inbox

The owner requested an Inbox below Plantillas for connected social channels and WhatsApp,
including the inbox features exposed by Zernio. Production publication was authorized
on November 15, 2026. This module does not activate automations or send test messages.

## Interface

Inbox is after Plantillas; Pipeline, Clientes and Seguimientos remain below Sara IA.
Select a connected channel and account, then Mensajes, Comentarios, Menciones or Reseñas.
Lists preserve opaque cursors and distinguish partial, empty and unavailable results.
The selected conversation shows messages and a reply composer. Public replies are
labeled separately from private messages. Incoming messages are polled every 30 seconds
only while visible, active and without an unsent draft or confirmation dialog.
Refresh remains available manually. Reading never marks a message as read implicitly.

Draft text and attachment URLs stay in component memory, keyed by account, section and
thread. Changing threads preserves drafts; leaving Inbox or closing the tab warns.
No incoming message history is mirrored into the local CRM database.

## Provider contract

The checked-in registry contains all 43 JSON operations under `/v1/inbox/` in the
November 15 official OpenAPI snapshot: conversations, replies, editing/deletion,
read receipts, archive, thread handover, requests, labels, reactions, attachments,
comments and moderation, likes/pins/private replies, mentions, reviews and their replies.
Advanced operations are available in Herramientas with structured scalar fields and
schema-backed JSON fields for nested objects (WhatsApp interactive/templates, carousels,
Telegram markup, contacts and locations). An approved WhatsApp template lookup is also
available; the local Plantillas draft library is NOT equivalent to Meta approval.

The normal composer supports text and public-HTTPS attachment URLs. Direct local binary
uploads are not implemented; use an accessible HTTPS asset supported by the platform.
Attachment retrieval asks Zernio for a JSON URL; neither the API nor gateway follows
provider redirects or fetches arbitrary attachment hosts. Remote files are not embedded
or fetched automatically. Open them explicitly from a safe HTTPS link.

Not every platform supports every operation. Permissions, account type, billing,
message windows and Meta app eligibility still apply. Unsupported actions return a
provider rejection rather than simulated success. No account grants are automatically
expanded. Facebook/Instagram sends may reclaim thread control; the confirmation warns
about this, public replies and potential outbound messaging cost.

Pinned sources:
- https://zernio.com/openapi.yaml
- https://github.com/zernio-dev/zernio-node (Apache-2.0)
- https://docs.zernio.com/messages/list-inbox-conversations
- https://docs.zernio.com/cli/inbox

`ops/dev/build_inbox_registry.py` reads an already-downloaded JSON representation of
the official YAML, resolves local schema references and extracts fixed paths and JSON
request schemas. It does not download or execute vendor code. The registry records the
source URL/date and SHA256 of that JSON representation. No runtime discovery or new
package is required. External references and unknown request fields fail closed.
Binary multipart upload and inbox analytics are outside this JSON inbox catalog;
analytics, broadcasts, sequences, ads and outbound calls are separate products, not
silently activated by this inbox.

## Security and execution

All routes use the existing administrator session, exact Origin and CSRF checks,
private no-store responses and narrow Next gateway allowlists. Inputs are bounded to
64 KiB at gateway/API and 48 KiB per argument group, validated against pinned JSON
schemas; opaque IDs are encoded once. The server injects accountId/profileId, rejects
cross-scope values, and confirms the account belongs to the configured profile on each
request. Existing Zernio/channel enable switches remain authoritative.

Reads use only fixed vendor GET routes through the established TLS egress. Credentials,
raw provider errors and secret-like result keys never reach the browser. Do not replace
this with a generic URL proxy, browser tokens or an MCP token repurposed as a REST key.
The existing REST API connection must be configured; MCP-only authorization is not an
implicit API credential. The UI directs missing configuration to Conexiones.

Every external write has two steps:
1. Prepare an actor-bound, immutable payload and live participant identity with a
   ten-minute expiry. This performs account/context reads but no vendor mutation.
2. Show exact account, recipient, content, IDs and consequences, then explicitly
   confirm. Revalidate credentials, account, expiry and participant identity; atomically
   reserve and commit `sending` BEFORE one external request with an Idempotency-Key.

No background worker, retry, broadcast or real test send is introduced. A crash after
reservation stays `sending`; ambiguous transport/provider errors become `unknown`.
Neither can be replayed. Reopening history never dispatches. Check the actual channel
before preparing a new action after uncertainty. A successful HTTP provider result
means accepted by Zernio, not proof of delivery or a recipient reading it.

The migration role alone applies 015_inbox_actions.sql and
016_inbox_recipient_context.sql. Runtime can insert/select plans and update only state,
error and completion time, not the immutable arguments or recipient snapshot.
Prepared outgoing content is retained in the private action table for audit; no
automatic retention deletion policy is introduced. History is actor-scoped (100 latest).
No provider credential, customer phone or message content belongs in logs or screenshots.

## Verification and deployment

- API tests: `uv run --project apps/api --frozen python ops/dev/crm.py test`
  uses only the isolated local jardines_crm_test database.
- Gateway/UI tests: `npm run test:crm:gateway`
- Types/build: `npm run typecheck` and `npm run build`
- `tests/fixtures/inbox-preview.mjs` runs a synthetic loopback-only workspace.
  All fixture sends mutate memory only, never a customer or vendor account.
- Normal publication: existing Verify and deploy GitHub Actions, logical backup,
  checksum-checked additive migrations and health-checked application activation.
  Follow docs/DEPLOY.md; do not bypass failing gates or copy credentials.
- Live verification must be read-only: module placement, account visibility, connection
  state, migration presence and readiness. Do NOT send real messages, mark them read,
  accept requests, hand over control, delete content or submit templates as a test.

If this release is rolled back, retain the additive inbox tables and restore only the
previous healthy application images through the existing gate. A migration rollback or
restoring production data requires separate authorization.

### Release verification — November 15, 2026

The final isolated API suite passed 500 tests, including 70 inbox tests covering all
43 pinned route constructions, closed schemas, profile/account isolation, explicit
Boolean consent, actor ownership, expiry, credential rotation, live recipient changes,
concurrent confirmations, unknown outcomes and no replay. The gateway/UI suite passed
232 tests. Operations ran 159 tests (one existing optional Hermes fixture skip); Ruff,
TypeScript and the production Next build passed. Source-only formatting changes were
followed by another gateway run. The cohesive module is larger than the usual review
slice, including the generated provider registry; its backend, UI, safeguards and tests
ship together rather than splitting an unusable intermediate production release.

Synthetic browser checks covered desktop and 320px mobile layouts, the selected
conversation/composer, explicit confirmation, one-shot result, returning to the list,
thread-keyed draft preservation, comments and all 43 tools. The mobile document width
was 320px and the composer bottom stayed inside the 760px viewport. No real customer
message, read receipt, reaction, comment, review or template submission was produced.

Read-only production metadata showed the existing channel switches enabled but no
REST credential configured. The existing OAuth probe is limited to accounts:read;
it is not a messaging grant. Enabling the live inbox therefore remains dependent on
owner-confirmed storage of the API key/profile through the private settings form.
Do not copy a key from an open page without that explicit confirmation. Publishing
the module does not imply the private messaging connection has been completed.
