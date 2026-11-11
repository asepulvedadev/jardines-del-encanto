# Shared application control plane and settings modal

Status: authorized local implementation, 2026-11-11. Production activation is separate.
The owner requested an icon-led settings modal with Redes sociales, Conexiones and
Customizaciones, and functional shared skills/tools/plugins/scripts controlled by
Hermes and the app. This replaces the existing settings page, not the private CRM.

## Security and execution decision

Hermes operates implemented application capabilities through an authenticated broker,
not a VPS shell. CRM writes and configuration changes proposed by Hermes require an
administrator's exact-action confirmation. Direct human CRM work remains available.
No other project, host filesystem, Docker socket or provider secret is exposed.

Custom scripts are executable bounded **application-action workflows**, not Python,
JavaScript or shell evaluation. Tools bind typed app actions; plugins bundle actions
and optional instructions; skills supply bounded Markdown instructions to the agent.
This is an application extension format, not arbitrary native Hermes Python plugins.
Unrecognized adapters cannot be marked effectively connected. Provider/network
activation is never inferred from a stored on/off preference.

## Shared API contract (all private, no-store)

The web gateway keeps its explicit route/method allowlist. Admin routes preserve the
existing session, exact-origin and independent CSRF checks. Item creation/edit JSON is
bounded to64KiB UTF-8; other gateway mutation bodies remain16KiB. Markdown retains
its16000-character cap; reject oversized content rather than truncating it.

- `GET /crm/control/catalog` -> `{items, capabilities, connections}`.
- `POST /crm/control/items` -> item. Input `{kind,name,description?,definition,enabled?}`.
- `PATCH /crm/control/items/{id}` -> item. Input `{version,name?,description?,definition?,enabled?}`.
- `POST /crm/control/items/{id}/run` input `{arguments?}` -> action result.
- `PATCH /crm/control/connections/{key}` input `{version,enabled}` -> connection.
- `GET /crm/hermes/status` -> `{configured,available,enabled,model,tools_count}`.
- `POST /crm/hermes/chat` input `{message}` -> `{run_id,reply,results,proposals}`.
- `POST /crm/hermes/actions` input `{action,arguments?}` -> action result.
- `POST /crm/hermes/proposals/{id}/approve` or `/reject`, input `{version}` -> proposal/result.

Item: `{id,kind,name,description,definition,enabled,effective,version,created_at,updated_at}`.
Kinds: `skill`, `tool`, `plugin`, `script`, `connection`.
Definitions:
- skill: `{content: string}` (Markdown, <=16000 characters).
- tool: `{action: string, defaults?: object}`.
- plugin: `{actions: string[], instructions?: string}`.
- script: `{steps: [{action: string, arguments?: object}]}` (1..8 steps).
- connection: `{adapter: "application", actions: string[]}` (typed local app adapter,
  never an arbitrary network URL or credential store).

Capability: `{key,name,description,input_schema,mutating,enabled}`. Built-in keys below
are canonical. Built-in tool toggles may use items of kind tool with definition.action;
if such an item exists its desired state governs that automation capability. Preserve
human CRUD routes independently. Custom items also have keys `custom.<UUID>`.

Connection: `{key,name,enabled,available,effective,version,status}`. Keys:
`hermes,zernio,facebook,instagram,tiktok,whatsapp,telegram`. Pausing social connections
blocks new sync/connect work for app and agent; it does not revoke upstream accounts.
Editing, status, disconnect and bound authorization callback completion remain available.
Hermes starts disabled until its bridge is configured and actually reachable. Other
connection preferences default enabled to preserve existing manual setup behavior.

Action result: `{result?: object, proposals?: Proposal[]}`. A mutating action returns
pending proposals, never pretend-success. Proposal: `{id,action,arguments,status,version}`;
approval returns `{proposal,result}`; rejection returns `{proposal}`. Proposal status
is `pending|approved|rejected|expired`. Exact arguments, actor and revisions are frozen.
Existing optimistic versions are mandatory for contact/deal/task edits. Editing a
custom definition invalidates its unapproved actions. No generic SQL/HTTP/shell tool.

Canonical implemented actions:
- `crm.workspace` `{query?,limit?,offset?}` (default50, maximum100, explicit paging
  metadata); `crm.activities` `{deal_id}`.
- `crm.contact.create` `{name,phone,source}`; `crm.contact.update` `{contact_id,name,phone,source,version}`.
- `crm.deal.update` `{deal_id,stage,version}`; stages new/contacted/won only.
- `crm.note.create` `{deal_id,body}`.
- `crm.task.create` `{contact_id,title,due_date}`; `crm.task.update` `{task_id,completed,version}`.
- `control.catalog` `{}`; `control.item.create` creation input above;
  `control.item.update` `{id,version,...}`; `control.connection.update` `{key,version,enabled}`.
- `social.status` `{}`; `social.sync` `{}`; `social.connect` `{platform}`.
  Credential entry is human-only. OAuth/account grants still require the provider's
  real authorization UI; Hermes never receives or invents a grant/token.

Reuse shared CRM service functions for human routes and approved broker writes in
one database transaction (including proposal consumption). A crash/retry must not
double-apply an approved note/task/action. Social network calls are fixed existing
adapters; do not create a generic proxy or pretend outbound publishing exists.

## Internal Hermes bridge protocol

API environment `HERMES_BRIDGE_URL` points only to the fixed private service
`http://hermes-bridge:8081` (loopback HTTP ports may be allowed for isolated tests).
The bridge itself knows the fixed `HERMES_BROKER_URL=http://api:8000` destination;
callers cannot supply broker/provider URLs or select arbitrary models.

`POST <bridge>/run` body `{token}`. Token is a 256-bit opaque, short-lived service
identity issued by the API, stored hashed, tied to the initiating live admin session,
scoped to one run and bounded calls/expiry. It is never returned to the browser.
The bridge uses `Authorization: Bearer <token>` to call:
- `POST /internal/hermes/claim` `{}` -> `{run_id,prompt,skills,tools}` (single claim).
- `POST /internal/hermes/call` `{call_id,action,arguments}` -> action result;
  deduplicate call_id within run and enforce per-call permissions and live admin status.
- `POST /internal/hermes/finish` `{reply}` -> `{run_id,reply,results,proposals}`.
Internal routes never accept admin cookies as service authority and are not web-proxied.
All return opaque errors/no-store; no request/token/provider-secret logging.

`skills` is a list of enabled `{name,content}` definitions. `tools` is a list of
OpenAI function schemas. Use one canonical tool `jardines_app` with parameters
`{action: enum of allowed keys, arguments: object}`; the broker validates every action
against its own typed models regardless of model output/schema. The pinned Hermes
schema requires both action and arguments and rejects additional properties. The pinned Hermes
AIAgent must genuinely call this broker tool and receive its result before replying.
A canned response or a second bespoke LLM loop must not be labeled Hermes.

Use a separately scoped operator runtime/provider policy; retain the existing
text-only CLI/provider as a safe unchanged fallback. Bound operator turns (<=4 LLM
iterations, <=12 broker calls, timeout, output size), keep secrets in the provider,
and fail closed when runtime/provider is absent. No live paid call is needed for
unit/integration tests; a deterministic upstream fixture must exercise real Hermes.

## UI contract

Settings is a named native dialog preserving the current CRM view and focus. Tabs:
Redes sociales, Conexiones, Customizaciones. Customizations filter Skills, Tools,
Plugins, Scripts. Connection rows use app icons, concise state, Edit and labeled
switches. CRUD/run/approval failures remain visible; switches reflect server state.
Creation starts disabled. Invalid/inactive definitions cannot be reported running.

OAuth/social callback markers auto-open Redes sociales. Keep exactly one callback
consumer mounted through completion, even across tabs; scrub callback URL values and
preserve existing replacement confirmations. Store no provider secrets in browser
storage. Prefer inline editor/detail panels to nested dialogs. Preserve keyboard,
Escape, focus, small-screen reflow and reduced-motion behavior.

Hermes is accessible in the modal's Conexiones tab: prompt, actual reply/tool results,
and explicit action proposals with approve/reject controls. Minimal explanatory copy
is not permission to hide errors, state or the exact consequences of approval.

## Verification

Use the isolated `jardines_crm_test` database guard and existing migration/checksum
runner. No test may truncate normal/project/production data. Cover auth/CSRF, bounded
strict definitions, effective enablement, optimistic conflicts, proposal tampering,
once approval under races, token scope/replay/expiry/revocation, no credential output,
callback return, scripts/plugin actions, and real Hermes-to-broker tool execution.
No production operations or global skill/plugin installation are authorized here.

## Runtime wiring and limits

The bridge health endpoint returns `{available: boolean, model?: string}` from actual
provider readiness. Operator compose joins only its private provider network and the
external `JARDINES_APP_NETWORK` (default `jardines_app`; local
`jardines-crm-local_app`), never the database network. The API points to the fixed bridge
service, but ordinary CRM health does not depend on optional operator availability.
Per-tool results are capped at64KiB and provider context at128KiB; overflow is an
explicit failure, not silent truncation. Production root-owned runtime installation
and real provider activation are separate deployment operations.

Broker responses additionally share a64KiB cumulative run budget. An oversized
dispatch rolls back its new proposals and records an explicit bounded error, keeping
the final response within the bridge limit. Migration006 preserves run/proposal/audit
history after logout; the live-session join still immediately revokes service access.
Health proves local policy/provider credential readiness, not upstream entitlement,
quota or model access; real inference failures remain explicit and sanitized.

## Observed delivery state (2026-11-11)

- Local application migrations005/006 applied through the migrator without resetting
  records. API and web images rebuilt; preview remains `http://127.0.0.1:4321/crm`.
- API97tests passed twice (implementation and independent verification); the existing
  Starlette/httpx deprecation warning remains. Gateway/settings26tests, landing15tests,
  TypeScript and image builds passed. Host operations ran40tests:39passed and the real
  image test was explicitly skipped there and executed separately.
- The actual pinned Hermes image passed11tests, including genuine AIAgent tool dispatch,
  deterministic upstream transport, broker response and final reply. An independent
  verifier repeated this proof without external network, keys or paid inference.
- Built-image browser checks passed editor open/focus, preserved approvals, responsive
  reflow and exactly-once MCP callback completion across tab switches/close/reopen.
  Browser APIs were isolated fixtures, not live account authorization.
- Independent bounded review found no evidenced severe change-caused defect; this is
  not a security certification. Auth-free local control/broker requests return401;
  API readiness returns200 and both local containers are healthy.
- Production remains unchanged. The new operator stack is not activated, and no live
  provider credentials, Zernio accounts, paid requests, remote operations, commits or
  publication were performed. Root-owned production runtime installation and live
  provider/account verification remain separate work.
- Temporary verification artifacts under the task-specific `/tmp/jardines-settings-*`
  and `/tmp/hermes-operator-fixture` paths were retained after the command runner refused
  forced cleanup. Test servers and the disposable browser container were stopped.
