# Restore production Zernio OAuth connectivity

Owner authorization: migrate only this project's local Zernio OAuth grant to its VPS
and complete the integration. Baseline:3807f64. Do not touch concurrent landing work.

## Boundaries

Keep accounts:read, the exact accounts_list({}) MCP probe, PKCE, live admin sessions,
CSRF, fixed vendor hosts and private token storage. No generic MCP/HTTP proxy, new
social write scopes, REST-key substitution or other project's credentials. OAuth
observations are accounts visible to the explicitly authorized Zernio grant, not
proof of a Jardines profile or permission to publish/send messages. Never insert
invented profile IDs or attach these accounts to the REST profile ledger.

## Shared state contract

Preserve existing SocialSettings.configured as REST configured. Add:

- oauth:{available,authorized,needs_authorization,verified_at} (sanitized MCP status).
- can_sync:boolean (REST configured or enabled/authorized usable MCP grant).
- connect_mode:"api"|"vendor_dashboard"|"unavailable".
- dashboard_url:"https://zernio.com/dashboard" (fixed, credential-free).
- connection entries may add source:"rest"|"oauth". OAuth-only entries use bounded
  sanitized id/platform/username/display_name/status/connected_at, no synthetic profile.

When REST is configured, retain its profile-bound ledger as the channel list. When
REST is absent, show OAuth account observations from the last successful exact MCP
probe. Parse the documented text strictly with count/length limits; malformed or
incomplete results clear verified state and fail visibly, never silently erase the
last observed snapshot or fabricate connected status. Inactive/expired/revoked grants
must not count as effectively connected. Refresh OAuth through /social/sync without
requiring a REST key. Refresh after callback/check and propagate to control catalog.

Keyless connecting uses a clearly labeled fixed vendor dashboard handoff, not an
undocumented write tool. REST channel flows remain unchanged. An OAuth-only
POST social/connect/{platform} may return {mode:"vendor_dashboard",platform,url}
for an approved Hermes handoff; no fake OAuth intent/profile/grant is created.
The browser UI uses a labeled "Conectar en Zernio" link in this mode.

## UI ownership

ZernioMcp onStateChanged callback runs only after successful completion/check/local
unlink, not each status GET; SocialPanel reloads its settings and informs parent
settings catalog. Exactly one persistent callback consumer; no callback query/code
storage, duplicate exchange or authorization token exposure. Keep icon-led rows and
errors/disabled reasons concise, Escape/focus/mobile behavior intact.

## Controlled egress contract

New social.transport.https_connection(host,timeout) permits only zernio.com and
mcp.zernio.com. Without ZERNIO_HTTPS_PROXY it preserves direct local HTTPS. The only
proxy configuration accepted is http://zernio-egress:8080. Use HTTPSConnection to the
proxy plus set_tunnel(target,443), retaining end-to-end TLS verification of the target.
A project-private CONNECT relay allows only these hosts:443, rejects private/reserved
resolved IPs, bounds headers/concurrency/bytes/deadlines, exposes no host port and has
no credentials or database mounts. Only relay joins project egress; API remains app/data
and Hermes retains its existing fixed-peer guard. Production OAuth flag is enabled
only after project Nginx callback logging is sanitized and egress is verified.

## Verification and delivery

Use only guarded jardines_crm_test for mutation tests. Coordinate one DB suite at a
time. RED/GREEN regression for OAuth-only WhatsApp/status/refresh and unchanged REST,
failed/partial probes, generic RPC denial, state refresh UI, proxy denial/TLS policy.
No real social linking/messages/publications in tests. Parent handles secret-free
streamed grant migration, reviewed root-owned policy installation, live read-only
verification and CI deployment. Workers never commit, deploy, use real tokens or
write memory (runtime session identity unavailable). Ordinary workflow only; no
Gentle AI orchestration/registry/receipt tooling.
