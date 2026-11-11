# Shared settings UI

The private CRM footer opens a native named settings dialog without changing the
current overview, pipeline, contacts or tasks view. Escape and the close button
close it; native dialog behavior restores focus. Tab controls support arrows,
Home and End. The forest/light Manrope presentation follows `DESIGN.md`.

## Surfaces

- **Redes sociales:** Zernio OAuth/REST setup and existing channel authorization,
  with server-owned connection preferences. Pausing prevents new connection/sync
  work; it does not revoke upstream authorization. Replacement confirmations and
  local-versus-upstream disconnection remain explicit.
- **Conexiones:** actual Hermes health, desired enablement, prompt, broker results
  and exact proposals; typed local application adapters can also be created here.
- **Customizaciones:** Skills, Tools, Plugins and Scripts share the private
  control catalog with Hermes. New items start disabled. Tools select a canonical
  app action and object defaults; plugins select actions with optional instructions;
  scripts contain 1–8 JSON action steps, never executable Python or shell.

All writes use the current version and existing session/CSRF gateway. Switches
remain unchanged until the server confirms a response. Body limits use UTF-8 bytes:
64 KiB for control-item creation/edit and 16 KiB for other operations. No provider
secret is persisted in browser storage. Existing social authorization stores only
an intent ID and platform, not credentials.

## Callback lifetime

The dialog lazily mounts exactly one `SocialPanel` after first opening and never
unmounts it when changing tabs or closing. `ZernioMcp` remains its sole OAuth
consumer. Social intent values are captured and scrubbed before the settings
request; the completion request waits for server settings. Callback capture is
idempotent under effect replay. Callback errors and authorization state remain
available on reopening, even if the callback completes while the dialog is closed.

## Verification

`node --test tests/settings-ui.test.mjs` checks modal navigation contracts,
server-owned versions, disabled creation, actual rendered switch/tab/proposal
semantics, escaped proposal arguments and persistent callback ownership.
`npm run typecheck` validates the web app.

Browser integration must additionally exercise keyboard/focus return, 390/893/1440
reflow, server failure/conflict states and callback completion while changing tabs
or closing/reopening. A local deterministic provider fixture is required to claim
Hermes execution; missing runtime/provider is not a connected integration. No live
customer/provider operations or publication are part of these frontend checks.

Observed local verification (2026-11-11): ten focused rendering/contract tests and
TypeScript checks passed. Browser tests with an isolated mock API covered creation
of all four customization kinds (initially disabled), edit/toggle/run, approval and
rejection, optimistic conflicts, keyboard/focus restoration and preserved Pipeline.
The built production image additionally passed the Hermes editor open/focus/collapse
and preserved-proposal flow, reflow at320/390/893/1440, and exactly one MCP completion
after callback URL scrubbing, tab switching and dialog close/reopen. These are UI
fixture checks, not proof of live Zernio/OpenAI authorization. Genuine pinned Hermes
execution is verified separately as documented in `HERMES-OPERATOR.md`.

### Observed local fixture checks (2026-11-11)

A loopback-only disposable API fixture plus Next development server exercised:
server-version switch changes, unchanged switch after 409, disabled creation for
all four customization categories, skill edit/enable, invalid Tool JSON then valid
execution, Hermes prompt/approve/reject, Escape/focus return to Configuraciones,
and preservation of the preceding Pipeline view. Home/Arrow tab navigation passed.
The social-intent return was scrubbed and completed once while switching tabs and
closing/reopening the dialog. This was a fixture, not real Hermes/provider proof.

Screenshots at 1440, 893 and 390 px showed no modal-body horizontal overflow;
centering and textarea 16px text/120px minimum height were measured. App resets
initially removed native centering and later CRM form rules overrode font sizing;
explicit scoped settings rules fix both. Console showed Next development CSS
preload warnings; the deliberately intercepted 409 appears as an expected network
error. Two attempts at the additional MCP OAuth race check ended with Playwright
CLI `Session closed`; that browser path remains unverified. No code exception was
observed during the completed fixture flows.

Editar Hermes opens/focuses a persistent inline panel; collapsing it retains chat
and proposal state. This final interaction adjustment has source-contract coverage;
the expanded-panel screenshots precede that toggle-only adjustment.

Approval and execution are distinct: approved proposals are labeled **Aprobado**.
External `dispatch_reserved` / `external_outcome_unconfirmed` results explicitly
remain unconfirmed, with no retry control. Refresh failure after a successful
server response is a separate warning, never a claim that the write failed.

## OAuth-only account observations

`configured` continues to mean REST profile configuration; it is not the gate for
OAuth account visibility or refresh. Settings now expose sanitized `oauth` state,
`can_sync`, `connect_mode` and a fixed credential-free `dashboard_url`. OAuth account
observations carry `source: oauth` and remain distinct from the REST profile ledger.
They do not prove association with this project's brand or permission to publish.

Refresh uses `can_sync` and existing connection preferences. In vendor-dashboard
mode, channel details offer a fixed `https://zernio.com/dashboard` handoff, labeled
Conectar/Gestionar en Zernio, then the user refreshes observations here. No REST API
key, synthetic connect intent, broader grant or write scope is invented. Pending or
paused work cannot open the handoff. Without authorization, the channel action
focuses the real MCP authorization control; unavailable OAuth/paused state remains
visible in the access panel.

The single persistent MCP consumer notifies SocialPanel only after successful
completion, check or local disconnect. SocialPanel reloads settings and the modal's
shared control catalog. Status GET does not notify, preventing refresh loops.
Generation checks prevent slower pre-authorization settings responses from replacing
a newer account snapshot. Refresh errors do not imply that authorization itself failed.

`node --test tests/zernio-oauth-ui.test.mjs tests/settings-ui.test.mjs` covers the
OAuth-only regression while retaining REST credential/intent and callback-lifetime
contracts. Live accounts, tokens, provider writes and production browsers are not
part of the UI test scope.

Failed MCP verification uses a separate invalidation notification, never a success
notification from a status GET. OAuth observations immediately lose verified
presentation, then sanitized settings and the shared catalog reload. If that reload
also fails, observations remain visible as Por verificar and the verification error
remains visible. REST profile rows are not invalidated by an OAuth failure. Failed
OAuth-only manual refresh follows the same rule.

Observed local regression checks: three source cases failed before implementation,
then eight source/TSX-rendering cases passed, including OAuth-only refresh/WhatsApp,
fixed dashboard handoff, pause/pending, inherited REST and unverified snapshots.
A separate failed-check regression also failed before its correction. A loopback
fixture verified check-triggered settings/catalog refresh exactly once, OAuth-only
sync, local unlink removing stale state, actionable authorization focus and fixed
vendor links. Callback completion was exchanged once, scrubbed its return URL,
updated settings/catalog, survived tab changes and close/reopen, and left local and
session storage empty. 390/1440 screenshots showed no horizontal modal overflow.
A failed-check fixture retained the account observation as Por verificar, removed
connected styling, preserved the actual error and reloaded settings/catalog once.
These are disposable UI fixtures, not live provider/grant or deployment evidence.
