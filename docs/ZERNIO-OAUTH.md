# Project-scoped Zernio MCP authorization

## Implemented locally

**Configuraciones → Conexiones → Zernio → Editar** uses
`https://mcp.zernio.com/mcp` with browser OAuth authorization code flow, PKCE S256
and refresh-token rotation. No global MCP, CLI, browser-session import or automatic
consent is installed. Initial scope: **`accounts:read` only**.

The server verifies access and refreshes sanitized account observations with exactly
`accounts_list({})`, without exposing generic tool execution. OAuth-only settings can
show these observations without a REST API key. This does not establish a Jardines
profile, write the profile-bound channel ledger, publish, message or spend money.
The advanced REST connection remains independent; MCP tokens never become API keys.
The existing application broker can read the same sanitized social status, but it
never receives OAuth tokens or direct upstream MCP authority.

The owner must approve consent or explicitly authorize migration of this project's
existing grant. Tests use fake issuer responses and never discover or copy credentials.

## Unified OAuth channel observations

The social settings API preserves `configured` as **REST configured** and adds:

- `oauth`: sanitized availability, authorization, reauthorization and verification state.
- `can_sync`: a configured REST adapter or an enabled, usable OAuth grant.
- `connect_mode`: `api`, `vendor_dashboard` or `unavailable`.
- `dashboard_url`: the fixed, credential-free `https://zernio.com/dashboard`.
- Channel entries identify their `source` as `rest` or `oauth`.

When REST is configured, its selected-profile ledger remains authoritative and its
existing connection/callback flows are unchanged. Without REST, `POST /social/sync`
performs the same bounded read-only MCP probe and returns OAuth observations. Settings,
control availability and the broker's social status use this shared state. An
OAuth-only channel-connect request returns a labeled fixed-dashboard handoff, not a
fake OAuth intent or permission grant. The human links accounts in Zernio, then
refreshes observations. Desired-state pause gates still block new app/agent work.

The core tool's [documented response](https://docs.zernio.com/mcp) is text, not an
assumed structured JSON contract. The parser accepts a complete counted listing of
at most 100 accounts, at most 32 KiB UTF-8, or the documented empty-account reply.
It validates every row, account ID, supported vendor-platform identifier and unique
ID before filtering to this app's five channels. Unknown, malformed, duplicate,
partial or oversized replies fail visibly. Filtered known non-app platforms produce
an explicit warning. A live read-only deployment probe also returned `phone` and
`tiktokads`; these validated non-app types are counted and filtered, not mapped to
WhatsApp or TikTok posting. TikTok Ads is a [separate account type](https://docs.zernio.com/platforms/tiktok-ads).
Arbitrary structured envelopes are not guessed or relayed.

Only sanitized identities and a successful observation timestamp are cached in the
existing private `mcp.json`, with the same lock, atomic replacement and 0600 mode as
the grant. The complete ASCII-escaped private JSON remains bounded to 64 KiB. The
cache belongs to a random grant generation: successful grant replacement discards it;
refresh rotation retains it. Failed probes retain the last identities but clear
verification. Disabled, expired or revoked access cannot report cached rows as
connected; they become `unverified`. Local disconnect removes the observations.

Account text does **not** identify profile ownership. No OAuth observation inserts
or updates `crm.social_connections`, creates a synthetic profile ID, or proves an
account belongs to Jardines. These rows represent accounts visible to the owner's
explicitly authorized grant; project-profile actions remain REST-profile-bound.

## Why MCP rather than CLI

The official CLI's `zernio auth:login` creates a device API key and saves it in
`~/.zernio/config.json`. MCP supports a separate OAuth grant without asking the
user to paste a key. Authorizing Zernio does not authorize individual social channels.

Primary references, verified on 2026-11-10 in Colombia:

- [MCP authentication](https://docs.zernio.com/mcp/setup)
- [CLI authentication](https://docs.zernio.com/cli/authentication)
- [MCP tools](https://docs.zernio.com/mcp/tools)
- [Resource metadata](https://mcp.zernio.com/.well-known/oauth-protected-resource/mcp)
- [Issuer metadata](https://zernio.com/.well-known/oauth-authorization-server)
- [Official server source](https://github.com/zernio-dev/zernio-python/tree/main/src/late/mcp)

Live metadata advertises fine-grained OAuth scopes, including `accounts:read`,
superseding the earlier integration note about absent resource-group scopes.
Resource-group scopes do not establish profile-level isolation.

## Security boundary

- Every endpoint requires an enabled administrator. Mutations additionally require
  the existing exact Origin and independent CSRF token.
- Random state is hashed, session/actor-bound, single-use and expires in ten minutes.
  The PKCE verifier remains server-side. Callback consumption precedes exchange.
- Callback: exact `CRM_ORIGIN` plus `/crm?zernio_callback=1`. HTTPS is mandatory
  except explicit loopback development. Callback issuer must be `https://zernio.com`.
- Discovery must match pinned issuer, authorization, registration and token endpoints.
  No arbitrary hosts, redirects, generic tools or broadened token scopes are accepted.
- The API's private volume stores `mcp.json` with directory 0700/file 0600, atomic
  replacement and a shared lock, including refresh rotation. This is access-controlled
  storage, not application encryption; protect host, volume and backups accordingly.
- Status/check/settings never return tokens, codes, verifiers or arbitrary provider responses.
  Callback parameters leave browser history before completion is posted as JSON;
  no secret enters localStorage/sessionStorage. The CRM sends `no-referrer`.
- MCP JSON/SSE replies, timeouts and allowed operations are bounded. Unexpected
  versions, errors or response formats fail closed. Verification is on demand and
  timestamped, not a continuous guarantee against revocation.
- Disconnect removes local tokens/pending state only. Revoke the client in Zernio
  too; social accounts stay connected there. Failed/canceled replacements preserve
  the previous grant. No REST credential or existing restricted Hermes profile changes.

## Local preview

The local Docker preview enables `ZERNIO_MCP_OAUTH_ENABLED=1`. Rebuild/recreate
only project web/API services, preserving volumes. Open `http://127.0.0.1:4321/crm`,
enter Configuraciones, press Autorizar con Zernio, approve in the provider, then
press Verificar conexión. Empty accounts are valid authorization, not a social link.
Use this production-build preview for real consent, not `next dev`, whose request
logs can include callback query strings. The native API runner remains opt-in.

## Production activation — not performed here

Production is disabled by default. A separately authorized deployment must:

1. Deploy reviewed application bytes using the existing release procedure.
2. Apply the project-only Nginx `jardines_private` log format, excluding query
   strings/referrers; run `nginx -t` before reload. Do not retain parallel combined
   logs, request-body capture or analytics recording callback URLs. The exact
   `/crm` location discards document error logs because upstream failures may
   otherwise record authorization codes; API/other-route errors remain logged.
   Validate callback privacy with an upstream failure before enabling OAuth.
3. Give only the API controlled HTTPS egress to `zernio.com:443` and
   `mcp.zernio.com:443`. The optional transport setting accepts only
   `ZERNIO_HTTPS_PROXY=http://zernio-egress:8080`; HTTPS CONNECT retains target TLS
   verification. Without that setting local HTTPS remains direct. Keep the API on
   app/data networks and put only the project-private fixed-target relay on egress.
   Do not expose Hermes to an unrestricted outbound network.
4. Preserve the private config volume, exact HTTPS `CRM_ORIGIN` and secure host
   cookies. Set `ZERNIO_MCP_OAUTH_ENABLED=1` only after logging/egress are safe.
5. Let the owner review consent scopes, authorize and verify the real grant.

Disabling the flag prevents authorization, refresh and probes without deleting
tokens; local disconnect still works. No production environment, account, Nginx
process, network or workflow was modified by this local implementation.

## Hermes follow-up

The tool-free Hermes profile remains unchanged. A future project broker must
authenticate Hermes separately, bind workspace/profile ownership, enforce approvals
and expose typed allowlisted operations. Direct upstream MCP would bypass that
boundary; OAuth authorization alone does not implement the broker/model tool loop.

## Checks

```sh
uv run --project apps/api python ops/dev/crm.py test
npm run test:crm:gateway
npm run typecheck
```

Live consent/refresh, profile selection, channel operations and Hermes execution
remain unverified until separately exercised with the owner's authorization.

Observed local checks: 62 API tests (11 isolated OAuth unit tests plus the public
HTTP guard regression), 9 gateway tests, 3 landing tests, typecheck and web/API
Docker builds passed. A browser fixture verified consent navigation, one callback
completion, query cleanup, verification/disconnect and widths 320–1440 without
console errors. Public issuer metadata is reachable from the local API container.
An independent bounded security review found no reproducible blocker. Nginx runtime
configuration and its failure-path logging test remain unverified before deployment.
