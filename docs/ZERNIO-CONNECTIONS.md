# Zernio connections foundation

## Current delivery

The local CRM now has a **Conexiones** workspace for Facebook, Instagram, TikTok,
WhatsApp and Telegram. It prepares secure credentials, profile-scoped account sync,
hosted consent/code flows and durable signed webhook receipts. It does not implement
publishing, outbound messages, campaigns, automations or Hermes channel tools yet.
The broader capability inventory remains in [ZERNIO-INTEGRATION.md](ZERNIO-INTEGRATION.md).

No existing Zernio keys, profiles or other-project connections were reused or changed.
The owner's browser session was inspected read-only. Creating a dedicated credential
or granting new account permissions requires action-time confirmation in that browser.
No credential or channel has been connected by this implementation automatically.

## Local preview

Requirements: existing ignored local CRM configuration and working database, Docker,
Node 24 and uv. Never use the following local policies on the shared VPS.

```sh
uv run --project apps/api python ops/dev/crm.py init
docker compose -f ops/dev/app.compose.yaml build
docker compose -f ops/dev/app.compose.yaml up -d --wait
```

The preview is `http://127.0.0.1:4321/crm`. If an older project-owned preview occupies
4321, stop only that explicitly identified preview before starting this one. Do not
stop other applications or prune the shared Docker daemon. `init` applies additive
migrations to the named local working/test databases and writes a mode-0600 ignored
API environment file; it never creates or overwrites a CRM administrator password.

- Web binds only loopback 4321 through its dedicated ingress bridge; the app network
  remains internal. API has no published port and no web-facing DB credential.
- PostgreSQL stays in the existing `jardines-crm-dev` project/network; the application
  Compose policy neither owns nor deletes its database volume.
- `ZERNIO_CONFIG_DIR=/var/lib/jardines-zernio` is a dedicated persistent named volume,
  seeded mode 0700 / UID 10001. The non-root API root filesystem stays read-only.
- Only the API mounts this volume. Neither web nor Hermes receives provider keys.
- Stopping the preview must preserve the secret volume. Do not use `down --volumes`.
- For host development, the runner instead uses the ignored `.local/zernio/private`
  directory. Host and Docker configuration stores are separate by design.

No new external Python/JavaScript dependency is required. This first small adapter
uses fixed-host `HTTPSConnection`; a full SDK adoption can be reviewed as capabilities
expand, rather than importing a large generated client for a handful of operations.

## Credential and profile setup

1. Create a **Jardines del Encanto** brand profile in the owner-controlled Zernio
   workspace, without moving the existing other-project accounts.
2. Create a dedicated key scoped to that profile. For this foundation, only the
   account/connection operations are needed; disable unrelated resource groups.
   Telegram status uses PATCH, so a GET-only key cannot complete that flow.
3. Enter the scoped key and profile ID in **Conexiones → Verificar y guardar**.
   The backend verifies the profile at the fixed vendor endpoint before persisting it.
4. Run **Actualizar conexiones**; then explicitly start each account's consent flow.
   Social-platform logins and permissions remain the owner/operator's responsibility.
5. Do not approve paid connections or subscriptions without a separately agreed budget.
   The existing workspace's free-account allowance can already be occupied.

The credential input is a password field, never browser storage, a URL or an API
response. `credentials.json` is mode 0600 under a mode-0700 directory; replacement
is explicit, locked and atomic. A generation change invalidates pending intents.
The file also holds a generated webhook secret. Its contents must never be printed,
logged, pasted into chat or committed. Deployment administrators and the host's
Docker daemon still retain access; this is not a hardware secret vault.

## Implemented API contract

All `/crm/social/*` endpoints reuse the existing enabled-administrator session,
exact Origin and CSRF validation. The browser BFF only permits these explicit paths.
There is no arbitrary vendor endpoint proxy and no message/ads-send endpoint.

| Endpoint | Behavior |
| --- | --- |
| `GET /crm/social/settings` | Redacted configuration, stored account/event summaries, limitations/readiness |
| `POST /crm/social/settings` | Verify/store scoped API key and profile; explicit replacement required |
| `POST /crm/social/sync` | Fetch one bounded profile-filtered account page; persist sanitized fields |
| `POST /crm/social/connect/{platform}` | Store session-bound expiring intent; return allowed consent URL or Telegram code |
| `POST /crm/social/complete` | Re-read vendor state; confirm only positive account evidence, not callback query claims |
| `POST /integrations/zernio/webhook` | Verify raw-body HMAC/scope and durably deduplicate a receipt |

The public web transport for that last route is
`/api/integrations/zernio/webhook`. It forwards raw signed bytes and the three Zernio
headers to the fixed private API, never browser cookies or Authorization. Both
layers cap the body at 256 KiB. Customer creation remains name, phone and source only;
no webhook automatically creates a customer or guesses a phone number.

Vendor paths are restricted to profile lookup, account listing and the five connect
routes; no redirects, arbitrary hosts or raw vendor errors are accepted. Consent
links must be HTTPS on the documented vendor/social domain families, without userinfo
or an alternate port. They remain explicit external links, not automatic redirects.

## Webhook registration is a separate activation step

A locally generated secret is **not** a registered vendor webhook. The UI reports
`webhook.configured: false` until an administrator has registered and verified the
actual subscription and marked `webhook_registered` in the private configuration.
There is deliberately no browser/API endpoint to claim that registration is complete.

Before activation, an administrator must provision a stable authorized public HTTPS
origin, register only the needed events/profile with Zernio using the generated
secret, verify a signed test event, then record registration. Local loopback cannot
receive a vendor callback; this change does not create a tunnel or deploy the CRM.
Any configuration-file update must retain ownership/mode, use the settings lock and
atomic replacement, and must not reveal key/secret values in logs or arguments.

Receipts enforce signature/header agreement, profile/platform scope and unique event
IDs. Same-ID/different-body deliveries conflict; duplicate identical events succeed
without another row. They are recorded as **received**, not processed. Conversation
projection, a background outbox, retention tooling, delivery/lead processing and
monitoring are follow-up work, not implied by a successful receipt.

## Known limits

- Existing-account reconnects stay pending unless a newly connected account ID
  provides positive evidence. This conservative foundation does not claim a canceled
  consent flow succeeded because an old account happened to be present.
- Sync reads one page, at most 100 accounts, and reports truncation. Incomplete pages
  never mark unseen accounts disconnected. Larger-profile pagination is future work.
- Telegram supports the Zernio channel/group connector, not personal private-bot DMs.
  Its completion is a vendor PATCH with the stored code in the query string.
- Signing metadata is shown without exposing raw transcripts or provider credentials.
- Hermes stays in its existing manual, tool-free runtime. The UI explicitly labels
  the inbox, content, ads and automation workspaces as pending, not working modules.
- No vendor credential, OAuth grant, live webhook or social account was exercised by
  the automated tests; vendor responses are mocked in an isolated test database.
- No production migration, VPS deployment, public callback, Git push or CI run is
  authorized or performed by this local foundation.

## Verification

```sh
uv run --project apps/api python ops/dev/crm.py test
uv run --project apps/api ruff check apps/api ops/dev
npm run typecheck
npm run test:crm:gateway
python3 -m unittest discover -s tests -p 'test_*.py'
docker compose -f ops/dev/app.compose.yaml config --quiet
```

The tests reset only `jardines_crm_test`, not the working CRM. Source and database
permissions separate migration/runtime roles; migration `002_social.sql` is additive
and leaves `001_crm.sql` and the customer columns unchanged. Do not edit an already
applied migration's checksum: create a new migration for future schema changes.
