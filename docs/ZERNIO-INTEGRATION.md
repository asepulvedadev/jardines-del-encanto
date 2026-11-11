# Zernio integration research: Jardines CRM and Hermes

**Status:** research and proposed architecture only. No Zernio account, subscription,
connection, SDK, MCP server, campaign, message or runtime integration was activated.
**Reviewed:** 2026-11-10. **Priority channels:** Facebook, Instagram, TikTok, WhatsApp,
Telegram. Technical documentation is English; future product UI remains professional es-CO.

## 1. Executive recommendation

Zernio can be the external communications API behind the existing CRM: account
connections, publishing, inbox, analytics, ads, contacts and automations can share
one backend integration. Keep Jardines' PostgreSQL and business API as the source
of truth; let both the CRM and Hermes use that same authorization/audit layer.

Three boundaries matter before implementation:

1. **API coverage is not native-platform parity.** A common endpoint does not make
   every format, inbox feature or permission available on every connected account.
2. **Telegram is not a personal-DM connector.** Zernio connects channels/groups;
   private messages to its bot are not retained in its inbox. TikTok DMs are also
   conditional and reply-only, not a general outbound sales channel.
3. **Hermes is currently tool-free.** Adding a URL or API key will not enable this
   integration: the current project policy blocks tools, MCP and non-provider sockets.

The GitHub organization is an ecosystem of SDKs and example apps. The underlying
Zernio service is closed-source and still requires its account, API credentials and
billing; cloning an example does not self-host the provider.
Sources: [organization](https://github.com/zernio-dev),
[Telegram](https://docs.zernio.com/platforms/telegram),
[TikTok inbox](https://docs.zernio.com/platforms/tiktok/inbox).

### Reading paths

- Product scope: sections 3–5 and 10.
- Connection/backend implementation: sections 6–8 and 11.
- Hermes integration: section 9.
- Budget, unresolved questions and delivery: sections 12–15.
- Complete API-family inventory: Appendix A.

## 2. Evidence, version and freshness

The published [OpenAPI contract](https://zernio.com/openapi.yaml) was downloaded and
parsed as data, not executed. Snapshot:

| Item | Observed value |
| --- | --- |
| API specification version | `1.565.0` |
| Production server | `https://zernio.com/api` |
| Versioned resource prefix | `/v1`; e.g. `https://zernio.com/api/v1/accounts` |
| Distinct paths | **846** |
| HTTP operations | **1,244**, including public and deprecated operations |
| Distinct operation tags | **87** |
| Deprecated operations | **28**; do not automatically expose these |
| Download size | 5,872,505 bytes |
| SHA-256 | `a79c233ebf227c5380a201ca9af61557ea00eaf7c9fa4cd33667305dc723abbf` |

These are counts of the inspected contract, **not** a promise that all operations
are enabled for this workspace, country or account. The organization README still
mentions 369 paths/seven ad networks, while current docs describe 39 connectors
across products and the contract includes nine advertising networks. Counts refer
to different surfaces and some prose lags the schema.

Use the contract for routes/parameters, platform-specific docs for restrictions,
and a controlled account-level test for actual eligibility. Neither a README nor
a generic comparison-table checkmark is sufficient evidence of an available action.
Current reference: [introduction](https://docs.zernio.com/),
[platform comparison](https://docs.zernio.com/platforms/compare.mdx),
[SDK generation](https://docs.zernio.com/sdks).

## 3. Priority-channel capability matrix

**Documented** means supported by public documentation, not tested against Jardines'
accounts. **Conditional** means permissions, account type, geography or connection
mode must be checked. Do not display a capability as enabled until verified.

| Channel | Connect from CRM | Publishing | Inbox / engagement | Analytics / advertising | Important exclusion |
| --- | --- | --- | --- | --- | --- |
| Facebook | OAuth and Page selection | Page feed/media, Reels and supported Story formats | Messenger, comments, Page reviews, private replies where permitted | Organic metrics; separate Meta Ads connection | Not a personal Facebook profile |
| Instagram | Professional Business/Creator OAuth; two login modes | Feed, carousels, Stories, Reels | DMs, comments, mentions and supported automations | Organic/account insights; Meta Ads separately | Not personal accounts or text-only posts |
| TikTok | TikTok for Business OAuth for new connections | Videos/photos; direct publish or supported draft workflow | Conditional DMs; comments/moderation | Organic metrics; separate TikTok Ads connection | Cannot initiate a business DM |
| WhatsApp | Meta Embedded Signup; coexistence or Cloud-only | Messaging/templates/broadcasts/Flows, not a social feed | Business conversations, receipts and interactive formats | Delivery/operational metrics; no social reach/follower analytics | Not a personal WhatsApp account |
| Telegram | Bot-admin + connection code or destination chat ID | Channel/group text/media/albums; supported edits | Connected channel/group messages | No documented social analytics or ad connector | No personal account/private-bot-DM inbox |

Sources: [Facebook](https://docs.zernio.com/platforms/facebook),
[Instagram](https://docs.zernio.com/platforms/instagram),
[TikTok](https://docs.zernio.com/platforms/tiktok),
[WhatsApp](https://docs.zernio.com/platforms/whatsapp),
[Telegram](https://docs.zernio.com/platforms/telegram).

### Facebook and Instagram: account and conversation ownership

- Facebook connects a Page with an authorized administrator/editor, not an arbitrary
  user profile. The user must select the actual Jardines Page.
- Instagram needs a professional account. Its default Instagram Login need not have
  a Facebook Page; Facebook Login requires a linked Page and grants different features.
  Ads-related access and some branded-content/audio features require the appropriate
  Facebook-based connection. Inspect granted scopes, not just connection success.
- Normal messaging windows are 24 hours. The documented seven-day `HUMAN_AGENT`
  extension is for **human-written responses**, not an AI/workflow bypass.
- Respect thread handover: standby events can indicate another app owns the thread;
  sends can fail with `not_thread_owner`. Pause automation rather than fight ownership.
- Instagram request-folder listing has limitations; incoming events can still exist.
  Thread-control capabilities differ between Instagram Login and Facebook Login.

Sources: [Facebook inbox](https://docs.zernio.com/platforms/facebook/inbox),
[Instagram inbox](https://docs.zernio.com/platforms/instagram/inbox),
[Instagram connection/features](https://docs.zernio.com/platforms/instagram).

### TikTok: publishing is not permission to message

DMs require a Business Account, eligible signup region outside EEA/Switzerland/UK,
and incoming-DM permissions. The documented ceiling is ten replies within 48 hours
of the user's last message. A reply is text or one image, not both together.
Older developer-app connections cannot use the documented Business-app inbox.
Comments have different eligibility and include supported replies/moderation;
comment-to-DM parity with Instagram must not be assumed.
Source: [TikTok inbox](https://docs.zernio.com/platforms/tiktok/inbox).

Publishing needs the creator's preview/consent and valid privacy/format settings.
The documented Business-app direct-video lane is public-only; use the supported
Creator Inbox draft route where appropriate. Account replacement/reconnect behavior
has conflicting documentation; see section 14 before changing an existing account.
Source: [TikTok publishing](https://docs.zernio.com/platforms/tiktok).

### Telegram: what the connection really controls

Zernio documents `@LateScheduleBot` as the destination's administrator with posting
permission. A code is valid for 15 minutes; the CRM can show instructions and poll
status. Existing bot-admin destinations can also connect using a chat ID. Channel
posts use the channel identity; group posts use the connector bot identity.

Use this for a project announcements channel or an approved group. If the objective
is a private sales assistant bot, propose a separate official Telegram Bot API/Hermes
channel integration and validate it separately; it is not supplied by this connector.
Sources: [Telegram](https://docs.zernio.com/platforms/telegram),
[connection flow](https://docs.zernio.com/platforms/telegram/connect).

## 4. WhatsApp deserves its own setup decision

### Connection modes

| Mode | Useful for | Consequence |
| --- | --- | --- |
| Coexistence | Keep an existing WhatsApp Business app in use | Default signup mode; Meta QR step; API groups/calling unavailable |
| Cloud API only (`onboarding=api`) | API-operated number | No app-coexistence QR; advanced features still require eligibility |
| Credentials | Administrator-managed WABA/System User token | Headless route; changes existing WABA webhook ownership immediately |
| Sandbox | Controlled development with own verified recipient | Shared test number; not production or a customer broadcast channel |

Embedded Signup can create/select the WABA. Own-carrier and provisioned numbers
are different products; buying a Zernio number is not required merely to connect
an existing eligible number. A provisioned number is tied to its profile. Do not
silently switch an existing provider, webhook subscription or production number.
Source: [WhatsApp connection](https://docs.zernio.com/platforms/whatsapp/connect).

### Capabilities to expose progressively

- **Inbox:** freeform replies inside the customer-service window; approved templates
  for permitted business-initiated/out-of-window messaging, media and supported
  interactive/commerce formats. A received message is not blanket marketing consent.
  [Inbox](https://docs.zernio.com/platforms/whatsapp/inbox).
- **Templates:** manage submissions, category/language/parameters and review status;
  allow selection only when approval and recipient policy permit sending.
  [Templates](https://docs.zernio.com/platforms/whatsapp/templates).
- **Broadcasts:** recipient selection, variables, scheduled sends, delivery results
  and cancellation. Do not confuse scheduled broadcasts with a guaranteed scheduled
  individual-inbox-message feature.
  [Broadcasts](https://docs.zernio.com/platforms/whatsapp/broadcasts).
- **Flows:** forms for inquiries/visit requests, draft JSON, validation, preview,
  publishing and response capture. `data_exchange` requires its own HTTPS service
  and cryptographic setup; a static navigation Flow is simpler. Handle `nfm_reply`
  submissions and retention settings explicitly.
  [Flows](https://docs.zernio.com/platforms/whatsapp/flows).
- **Calling:** conditional eligibility, customer call permissions, destinations,
  status/recordings and costs. New-number limits can prevent enabling it; country
  restrictions and Cloud-only mode matter. Distinguish WhatsApp calls from carrier
  PSTN/SIP calls.
  [Calling](https://docs.zernio.com/platforms/whatsapp/calling).
- **Groups:** documented only under additional business eligibility, Cloud-only mode
  and supported configuration. Existing app groups are not automatically migrated.
  [Groups](https://docs.zernio.com/platforms/whatsapp/groups).
- **Numbers:** purchase/porting/KYC, verification, profile moves, quality/limits and
  business-profile management are advanced administrator operations, not prerequisites
  to expose indiscriminately to an assistant.
  [Phone numbers](https://docs.zernio.com/platforms/whatsapp/phone-numbers).

Sandbox documentation describes recipient activation, one active recipient per user,
50 messages/day and a seven-day session, with a restricted starting template. Verify
current limits before using it; no sandbox session was created in this research.
Source: [sandbox](https://docs.zernio.com/platforms/whatsapp/sandbox).

## 5. Functional catalog for the CRM

These are **candidate modules**, not completed features. Each operation remains
subject to its channel's capabilities and the administrator's permissions.

| Product family | What can be managed from Jardines | Initial treatment |
| --- | --- | --- |
| Profiles/accounts/groups/settings | Brand profile, accounts, permissions, health, reconnect/disconnect, grouping | Core connection settings |
| Hosted/headless connect | Consent redirects, destination pickers, connection handoffs, optional own OAuth app | Hosted first; headless later |
| Publishing/media/validation | Drafts, schedule/publish, per-platform content, uploads, format checks, supported edits/unpublish/pin | Core content workspace |
| Queue | Slots, next-slot selection, preview and scheduling | Content advanced options |
| Conversations/messages | Search/list/history, supported replies, attachments, labels, unread/archive, receipts, handover | Core shared inbox |
| Comments/mentions/reviews | Read/reply and supported moderation/private replies | Channel-aware inbox tabs |
| Contacts/custom fields | External contacts, channel identities, tags/groups, imports | Optional mapping; do not expand the three-field CRM form |
| Broadcasts/sequences | Audience sends, scheduling, enrollment, pause/cancel, outcomes | Explicit consent and approval |
| Comment automations/workflows | Triggers, graphs, waits/conditions, handoff, versions, execution history | Disabled until reviewed |
| Other automations/ad rules | Event-driven actions, monitoring and supported ad changes | Guarded advanced module |
| Social/inbox analytics | Content/account metrics, trends, follower data, response performance | Cached read-only dashboards |
| Paid ads | Campaigns, ad sets/groups, ads, creatives, targeting, audiences, insights, boosts, rules | Reporting first; spending requires approval |
| Leads/conversions/tracking | Lead forms/submissions, attribution, pixels/tags and conversion events | CRM acquisition with minimal data |
| Catalogs/products/commerce | Product catalogs, connected-store products/orders and supported operations | Optional; not a real-estate inventory replacement |
| Blogs | Connected Shopify/WordPress/Wix/Webflow article operations | Optional marketing expansion |
| Calendar/files/email | Connected mail, calendar and file operations | Optional; separate permissions and retention |
| Telephony | Carrier numbers, PSTN voice, SIP, SMS, RCS, verification, branded calling | Separate cost/KYC project |
| Creator campaigns/portal | Creators, submissions, campaign operations and payouts | Optional, high-consequence actions |
| Business Agent | Meta Business Agent setup/configuration APIs | Distinct from Hermes; do not enable a competing responder by default |
| Billing/usage/ledger/treasury | Usage visibility, balances, recharge/transfers and financial operations | Read-only visibility; owner-only financial changes |
| Governance | Scoped keys, users/invites, connected apps, retention, webhooks/logs/changelog | Administrator-only |
| Support Assistant | Zernio's support-question service | Vendor support, not Jardines' sales AI; separately billed |

The contract also contains network-specific Instagram, Discord, Slack, iMessage,
Twitter and Google Business operations. Appendix A inventories **every operation tag**;
the live schema remains the parameter-level reference. Existence in that inventory
is not product approval to activate finance, commerce, mail or telephony.
Sources: [OpenAPI](https://zernio.com/openapi.yaml),
[product index](https://docs.zernio.com/),
[platform comparison](https://docs.zernio.com/platforms/compare.mdx).

### Organic content, advertising and leads are separate

Create dedicated `metaads` and `tiktokads` connections for paid management; do not
infer ads permission from an organic Page/TikTok connection. Current schema also
lists Google, LinkedIn, Pinterest, X, OpenAI, Reddit and Microsoft ads.

Meta exposes campaigns, ad sets/ads, audiences, creative, metrics and Page-scoped
Instant Forms. Instagram lead ads use the Page's form. Lead Ads terms and a privacy
policy are prerequisites where documented. Real-estate/housing targeting and special
ad-category requirements need owner/platform review for the actual market before
activation; this document is not legal or advertising-policy clearance.
Sources: [Meta Ads](https://docs.zernio.com/platforms/meta-ads),
[Meta forms](https://docs.zernio.com/platforms/meta-ads/lead-forms).

TikTok Ads is a separate advertiser integration, with identity/Spark Ads constraints.
The lead API references stored TikTok leads, but full TikTok Instant Form creation
parity was not verified. Expose those controls only after schema/account tests.
Sources: [TikTok Ads](https://docs.zernio.com/platforms/tiktok-ads),
[lead listing](https://docs.zernio.com/lead-gen/list-leads).

## 6. Connecting accounts inside the application

**Recommended first version:** start connections in the CRM, send the browser through
hosted platform consent/selection, and return to the CRM. This is an in-app-managed
workflow, not a promise that OAuth runs inside an iframe or that the user's native
social account never leaves our page.

1. Authenticate the administrator through the existing CRM session/CSRF mechanism.
2. Create/reuse **one Zernio profile for the Jardines brand/workspace**. A Zernio
   multi-tenant “customer” is our organization/brand, **not each lot buyer**.
3. Store `profileId` with our workspace ID. Set a stable `externalId` for event routing.
4. Server creates a short-lived, single-use connection intent: actor, platform,
   expected profile, allowed callback, expiry and nonce. Do not trust browser-supplied
   profile/account IDs as authorization.
5. Backend requests the connect URL or channel-specific code; send only the required
   short-lived connection data to the browser, never the master API key.
6. User grants platform consent and picks Page/account/number/channel. Handle cancel,
   partial permissions, expired code, wrong account, already-connected and reconnect.
7. On return, validate our intent and re-read the account server-side. Compare the
   profile/platform/expected identity; a successful-looking query parameter is not proof.
8. Persist the verified connection and capabilities; reconcile `account.connected`,
   permission-change and disconnect events. Show permission failures and reconnect action.

Zernio supports hosted/headless selectors, optional scopes and specific short-lived
`X-Connect-Token` use on declared connection endpoints. Headless is a custom picker,
not permission to skip the external consent screen. Prefer a pending-data token over
handling raw platform tokens where the documented flow supports it.
Sources: [platform-building guide](https://docs.zernio.com/multi-tenant),
[connect guide](https://docs.zernio.com/guides/connecting-accounts),
[connect contract](https://docs.zernio.com/connect/get-connect-url).

### Verified route examples

Paths below are relative to `https://zernio.com/api`. They are API references,
not commands executed in this task; use the current schema for required bodies.

| Intent | Documented route |
| --- | --- |
| Create/reuse brand profile | `POST /v1/profiles`; `GET /v1/profiles` |
| Begin supported social consent | `GET /v1/connect/{platform}` |
| Choose Facebook Page | `POST /v1/connect/facebook/select-page` |
| Complete applicable Instagram selection | `POST /v1/connect/instagram/select-account` |
| Connect advertising separately | `GET /v1/connect/{platform}/ads` |
| WhatsApp embedded/credentials completion | `POST /v1/connect/whatsapp/embedded-signup`; `POST /v1/connect/whatsapp/credentials` |
| Telegram code/direct/status | `GET`, `POST`, `PATCH /v1/connect/telegram` |
| Read resulting accounts | `GET /v1/accounts` |
| Create content / inspect outcome | `POST /v1/posts`; `GET /v1/posts/{postId}` |
| Conversation history / reply | `GET`, `POST /v1/inbox/conversations/{conversationId}/messages` |
| Retrieve/create lead form | `GET`, `POST /v1/ads/lead-forms` |
| Retrieve acquired leads | `GET /v1/ads/leads` |
| Manage WhatsApp templates | `GET`, `POST /v1/whatsapp/templates` |
| Flow lifecycle / results | `POST /v1/whatsapp/flows`; `GET /v1/whatsapp/flow-responses` |
| Broadcast lifecycle | `POST /v1/broadcasts`; `POST /v1/broadcasts/{broadcastId}/schedule` |
| Sequence/workflow creation | `POST /v1/sequences`; `POST /v1/workflows` |
| Configure events / inspect deliveries | `POST /v1/webhooks/settings`; `GET /v1/webhooks/logs` |

Source: inspected [OpenAPI contract](https://zernio.com/openapi.yaml).

## 7. Architecture proposal, not deployed configuration

```text
CRM browser (existing authenticated Next.js app)
  -> allowlisted same-origin BFF
  -> FastAPI business services / channel authorization
     -> PostgreSQL: CRM + social mappings + approvals + inbox + outbox
     -> dedicated Zernio adapter (server-side credentials)
        -> Zernio API -> authorized social accounts

Zernio signed events
  -> public HTTPS webhook route (HMAC, body limits, durable receipt)
  -> PostgreSQL inbox / background worker
  -> conversation, delivery, lead and connection projections

Hermes (separate, restricted runtime)
  -> narrow Jardines tool broker / MCP facade
  -> SAME business services, permissions, approvals and outbox
  -> never raw SQL, shell, master Zernio key or arbitrary HTTP proxy
```

**Recommendation:** use the official Python `zernio-sdk` behind a small adapter in the
existing backend, rather than calling it directly from React or maintaining separate
Node/Python control planes. The SDK documents sync/async clients and Python 3.10+.
Pin and test a version at implementation time; the current task installs nothing.
Source: [Python SDK](https://docs.zernio.com/sdks/python).

Proposed code boundaries, not existing directories:

- `apps/api/app/social/`: connections, capabilities, inbox, publishing, reporting.
- `apps/api/app/integrations/zernio/`: vendor client, error translation, schema mappings.
- `apps/api/app/ai_tools/`: typed Hermes tools and approval-bound execution.
- Worker entry point in the same Python project; initially PostgreSQL-backed durable
  jobs/outbox rather than introducing Redis or another orchestrator without need.

Extend the existing BFF allowlist deliberately. Do not add an arbitrary vendor-path
passthrough: that would bypass customer/account, permission and spend controls.
The current BFF's small JSON-body limit is not a media-upload implementation; use
reviewed presigned/direct uploads and metadata references, not giant base64 requests.

Keep the shared VPS isolation, separate database/runtime identities and existing
project deployment rules. This research does not authorize a migration, network
change, external callback, production deployment or sibling-project modification.

## 8. Data ownership and the three-field customer constraint

The customer form remains **name, mobile number, acquisition source**. Existing
source values are `in_person`, `social_campaign`, `web`, `referral`, `whatsapp`, `other`.
Do not add mandatory email, social username, budget or address fields.
Local reference: [CRM contract](CRM.md).

| Proposed integration table | Purpose / key invariant |
| --- | --- |
| `social_connections` | Workspace/profile/account/platform, granted capabilities and connection health |
| `channel_identities` | External platform identity mapped to an optional CRM customer; scoped by connection |
| `social_conversations`, `social_messages` | Vendor IDs, ordering, direction, delivery status, assignment and retention |
| `social_contacts_map` | Optional vendor-contact ↔ CRM link; no second source of truth for core customer fields |
| `social_posts`, `post_targets` | Draft/version/approval and separate result per publishing account |
| `social_leads`, `campaign_attribution` | External lead/form/campaign IDs, dedup and evidence for acquisition source |
| `webhook_events`, `outbox_jobs` | Unique event/job keys, durable retries, dead letters and processing status |
| `ai_action_proposals`, `action_approvals` | Exact proposed payload/version, approver, expiry and execution result |
| `channel_consents`, `contact_suppressions` | Channel/purpose consent evidence and opt-out enforcement |
| `social_metric_snapshots`, `sync_cursors` | Cached reports with freshness and checkpoint state |
| `integration_audit_events` | Actor, workspace, target, request correlation, outcome and redacted context |

These names and schemas are proposals; no tables were created.

### Identity and lead rules

- An Instagram handle, Telegram ID or TikTok sender ID is **not a mobile number**.
  Keep an unlinked conversation until a customer supplies a valid phone and we can
  link safely. Never invent phone numbers or create duplicates to satisfy the form.
- Do not merge two people solely because their display names match. Phone-based
  matching still needs normalization, conflict handling and reassignment safeguards.
- Use `social_campaign` only with campaign/form attribution evidence. An organic
  social DM can use `other` plus technical channel metadata under the current enum;
  a new source option needs an explicit product/schema decision.
- Preserve original acquisition source when later conversations arrive. Keep
  last-touch/platform/campaign metadata separately; do not rewrite `web` to WhatsApp
  because a website lead later chats there.
- Consent and attribution belong to supplemental integration records; they are not
  new required customer form fields. Vendor custom fields are optional and must not
  silently become additional CRM requirements.

## 9. Giving Hermes the same capabilities safely

### Current state versus necessary changes

[Current Hermes policy](HERMES.md) uses GPT-6 Luna, no enabled tools/MCP, a private
OpenAI credential proxy, one provider request per invocation, one iteration and 128
output tokens. The proxy rejects tool definitions, and the audit/network guards
allow only its provider. Therefore **Hermes cannot operate Zernio today**.

A later tool-enabled profile needs an explicitly reviewed change to all relevant
layers: tool registration, permitted broker destination, model request schema, tool
results/loop budget, output budget and credential scopes. Increasing only a prompt,
skill or `max_iterations` is insufficient. Keep the present restricted profile as
an independent fallback rather than silently broadening it.

GPT-6 Luna documents Chat Completions function calling with
`reasoning_effort: none`, matching the current model mode. A future reasoning/tool
configuration or GPT-6.1 Sol tool integration must use its supported API contract;
do not assume the present fixed text proxy can relay it unchanged.
Source: [OpenAI GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).

### Zernio's official agent interface

The hosted MCP endpoint is `https://mcp.zernio.com/mcp`, using Streamable HTTP with
OAuth or Bearer API-key authentication. It offers core tools such as `accounts_list`,
`posts_create`, `posts_publish_now`, `posts_cross_post` and media helpers, plus
schema-generated tools. `search_tools`/`call_tool` discover and invoke the long tail.
Sources: [MCP overview](https://docs.zernio.com/mcp),
[tool catalog](https://docs.zernio.com/mcp/tools).

Direct remote MCP is convenient for an administrator sandbox, but would place broad
operations outside our CRM's normal approval path. In particular, hiding tools from
`tools/list` does **not** restrict generic `call_tool`, resource access or another API
surface. Live metadata verified on 2026-11-10 now advertises OAuth resource-group
scopes. The local connection requests only `accounts:read`; that does not establish
profile-level isolation. See [ZERNIO-OAUTH.md](ZERNIO-OAUTH.md) for its implemented
boundary and updated primary sources.
Sources: [MCP authentication](https://docs.zernio.com/mcp/setup),
[key restrictions](https://docs.zernio.com/api-keys/create-api-key).

**Recommended production design:** Hermes calls a narrow local Jardines broker.
The broker maps allowlisted typed tools to our business service, enforces account
ownership and approval, and keeps provider credentials outside the agent. Authenticate
Hermes with its own short-lived, audience/workspace/tool-scoped service identity,
never a reused administrator cookie or master Zernio credential. A thin
REST-tool implementation or a project-local MCP facade can supply that boundary;
choose the smallest implementation compatible with the pinned Hermes runtime.
No external skill/plugin or global MCP configuration is installed by this document.

### Proposed tool tiers — project tool names, not Zernio MCP names

| Tier | Example Jardines tools | Permission / effect |
| --- | --- | --- |
| Read | `channels.list`, `inbox.get_thread`, `leads.get_summary`, `reports.get_metrics` | Workspace-scoped, bounded, redacted data; no external sends |
| Prepare | `replies.propose`, `posts.propose`, `campaigns.propose`, `followups.propose` | Create local drafts/proposals only |
| Confirmed execution | `actions.execute_approved` | Exact stored payload/version, target, approver and single-use approval |
| Restricted administration | Keys, connects/disconnects, webhooks, billing, imports, retention | Human administrator; no unrestricted assistant access |
| High consequence | Bulk outreach, ad spend, phone purchase/calls, transfers, destructive deletion | Separate policy and explicit approval; disabled initially |

Execution path: read context → create draft → show target/content/cost/window checks
in CRM → human approves → immutable payload hash and expiry are stored → worker
executes with idempotency → audit/result updates the UI. Approval must not authorize
a later edited payload, another recipient or a different account.

Incoming text, comments, captions, images, files and vendor errors are untrusted
content, never instructions to change tool scopes, reveal keys, run shell commands
or override approval. A customer cannot approve an administrator action by saying
“yes” inside a DM. Human takeover, opt-out and conversation ownership must suppress
all automated send paths, including vendor workflows and delayed outbox jobs.

### Useful Hermes workflows after explicit implementation

- Summarize an inquiry and suggest the next Kanban action without inventing a phone.
- Draft a channel-valid reply using approved lot/pricing/financing information.
- Prepare a week of Facebook/Instagram/TikTok content with per-format variations.
- Suggest a visit follow-up; let the operator approve the actual channel and send.
- Explain campaign spend/lead trends from synced evidence, not fabricated figures.

Do not claim available lots, reserve property, promise financing, grant discounts,
activate campaigns or send broadcasts from a model-generated statement alone.

## 10. CRM surfaces without losing the minimalist interface

Proposed es-CO navigation:

| Surface | Essential controls | Progressive advanced options |
| --- | --- | --- |
| **Conexiones** | Connect, permission status, reconnect, disconnect | Profile mapping, scopes and callback diagnostics |
| **Bandeja** | Channel filters, thread, reply, assign/link customer, human takeover | Labels, comments/reviews, handover and moderation |
| **Contenido** | Drafts, calendar, preview, approval, publish result | Queues, per-platform formats, bulk and edits |
| **Publicidad** | Read-only spend/results and leads | Creative/audience/forms/budget actions after approval |
| **Automatizaciones** | Draft/inactive flows, execution logs, pause | Broadcasts, sequences, graph/version management |
| **Ajustes** | Usage, redacted integration health and permissions | Retention, webhook repair, owner-only financial/admin actions |

Every action needs loading/empty/error/permission/unsupported states, per-target
outcomes and capability checks. Scheduled, approved, sent, delivered and failed are
different states. Do not present a queued request as a successful publication.
Follow the existing [design contract](../DESIGN.md); no UI was designed or changed here.

To cover “all options” without an unsafe universal console, maintain an explicit
**operation coverage registry**: `operationId`, resource group, channel prerequisites,
backend handler, UI action, Hermes scope, side effect, approval class and test status.
Treat new/deprecated schema operations as review items, not automatically exposed
routes or generated unrestricted forms. Coverage should say supported, unavailable,
planned or intentionally restricted, with a reason.

## 11. Events, retries, synchronization and failure behavior

### Webhook ingress

Verify `X-Zernio-Signature` using HMAC-SHA256 on the **raw bytes** and constant-time
comparison before trusting JSON. Validate body size/type, expected event and account
ownership. Persist a unique provider event ID (`X-Zernio-Event-Id`/payload `id`) and
only then acknowledge quickly; process asynchronously. Zernio documents 2xx within
five seconds and up to seven attempts over about 51 hours. Duplicate and delayed
out-of-order events must be harmless. A transient storage failure must not receive
a success response that loses the event.

Use a dedicated HTTPS webhook route authenticated by the signature, not a public
bypass of all CRM authorization. Do not require browser CSRF/session cookies on
provider callbacks. Reconcile missing events with controlled backfills and delivery
logs; do not run an assistant or slow API request inside the acknowledgement path.
Source: [webhook delivery contract](https://docs.zernio.com/webhooks).

### Writes and inbox synchronization

Generate one `Idempotency-Key` per logical action and reuse it on supported retries.
An `x-request-id` is for correlation, not a universal exactly-once guarantee.
Check each endpoint's contract; some creates, including lead-form operations, do not
have equivalent retry guarantees. For uncertain outcomes reconcile before resending;
never automatically duplicate a message, form, ad budget or paid call.
Source: [idempotency guide](https://docs.zernio.com/guides/idempotency).

Use webhook-first conversation updates, one-time/paginated history backfill and
bounded repair jobs. Avoid polling each thread on every render. Store delivery and
read transitions without downgrading newer states when old events arrive.
Source: [inbox integration](https://docs.zernio.com/multi-tenant/inbox).

### Reports and rate limits

Render dashboards from local snapshots with “last synced” information; unsupported
metrics are null/unavailable, never zero by invention. The current contract provides
`GET /v1/analytics/delta`, despite older integration prose saying there is no change
cursor. That feed documents taking a cursor **before** baseline import, then draining
changes; its retention is seven days, so expired cursors need rebaseline/repair.
Do not use publish timestamps or `syncedAt` as an opaque cursor replacement.
Sources: [analytics integration](https://docs.zernio.com/multi-tenant/analytics),
[current delta contract](https://zernio.com/openapi.yaml).

The rate-limit guide currently lists 60/600/1,200 requests per minute by connection
count, plus separate analytics windows and team caps. Honor `Retry-After` and actual
`X-RateLimit-*` headers; scope upstream throttles correctly, cap worker concurrency
and apply jitter. Track 401/reconnect, 403/permissions, 409/conflict and 429/backoff
rather than repeatedly retrying every error.
Source: [rate limits](https://docs.zernio.com/guides/rate-limits).

## 12. Credentials, retention and costs

### Credential model

The OpenAI key already used by Hermes is **not a Zernio credential**. A future
administrator must provision a separate Zernio key through protected server-side
setup; do not ask them to paste it into chat, commit it or expose it as `NEXT_PUBLIC_*`.
Store keys and webhook secrets outside application source and browser bundles.

The key schema supports profile scopes, expiry, GET-only `permission: read`, and
`disabledResourceGroups`. This is an **opt-out denylist**, not a per-operation allowlist;
default full/read-write credentials are broad. Current groups include publishing,
engagement, messages, contacts, analytics, ads, telephony, accounts, billing, webhooks,
commerce, creator campaigns, money, calendar and files. Scope both credentials **and**
our broker; constrain existing webhook subscriptions separately.
Source: [API key contract](https://docs.zernio.com/api-keys/create-api-key).

Do not call a credential “read-only” solely because the application promises not
to write. Separate administrator, reader and sending/worker credentials where the
vendor's actual resource-group mapping permits it. Rotate/revoke independently;
never grant the assistant API-key management, generic URL/path dispatch or money access.

Decide transcript/media/raw-event retention, redaction, deletion/export and processor
permissions before real customer ingestion. Zernio exposes a content-retention setting;
zero-retention mode can return content as null, so webhook capture and data-loss
expectations need testing. Keep logs/audit useful without recording credentials or
unnecessary customer text. This is a design requirement, not a compliance certification.

### Published price components — illustrative, not an approved purchase

Amounts below retain the vendor's dollar notation; they are not COP quotes. Confirm
invoice currency, current rates, tax and conversion before approving a budget.

| Meter | Documentation snapshot | Budget implication |
| --- | --- | --- |
| Connected accounts | Two free; graduated $6/account for positions 3–10, $3 for 11–100, $1 thereafter/month | Organic accounts, ads connections and WhatsApp numbers count separately |
| Outbound inbox messages | 10,000/month included, then $1/10,000 | Broadcast recipients contribute individually; check current billing rules |
| Managed active ads | 500 included, then $0.01/ad/month | Does **not** include platform advertising spend |
| Automations | 2,000 runs included, then $2/1,000 under documented new-account meter | Delayed/repeating workflows need limits |
| Phone/SMS/voice/RCS | Separate number/usage/setup meters | Not included just because WhatsApp connects |
| WhatsApp | Meta-related fees and Zernio number/carrier charges are distinct | Verify actual country/category/current Meta terms |
| Other products | Creator payouts/support questions and optional paid services have separate meters | Do not enable automatically with a broad key |

Sources: [pricing overview](https://docs.zernio.com/pricing),
[account pricing](https://docs.zernio.com/pricing/social),
[inbox pricing](https://docs.zernio.com/pricing/inbox),
[ads pricing](https://docs.zernio.com/pricing/ads),
[WhatsApp pricing](https://docs.zernio.com/pricing/whatsapp).

For illustration, one connection per requested channel is five accounts: the
published ladder implies **$18/month** for connections alone. Adding separate Meta
Ads and TikTok Ads connections makes seven and implies **$30/month** for connections
alone. These are arithmetic examples, not a quote or proof that every connection is
eligible. Add messaging, phone/Meta charges, automations, ad spend, OpenAI usage,
taxes/FX and existing team connections as applicable.

Pricing pages currently say all features are included with usage billing, while
some older pages mention Ads add-ons/legacy plans. Confirm workspace entitlements,
prepaid balance/card requirements and billing-owner approval before any paid action.
The WhatsApp page's specific claimed Meta service-message allowance was **not**
independently confirmed against Meta's rate card; do not hardcode it into estimates.

## 13. Proposed implementation sequence and acceptance evidence

This is a suggested order for a later authorized implementation, not new task
orchestration, a deployment instruction or permission to send real messages.

| Stage | Deliverable | Evidence required before moving on |
| --- | --- | --- |
| 1. Account discovery | Owner-controlled Zernio workspace, scoped credential, one brand profile | Read-only capability/entitlement and usage check; key absent from client/logs |
| 2. Connections | CRM-managed hosted consent for five priority channels | Connect/cancel/reconnect/expired/partial-scope/wrong-account tests; capability differences visible |
| 3. Event foundation | Signed webhook ingress, dedup/outbox worker, retention and audit | Invalid signature denied; duplicate/out-of-order/retry tests; no cross-workspace routing |
| 4. Inbox + minimal CRM | Read conversations, reviewed replies, explicit identity/customer links | Three customer fields preserved; no invented phones; actual delivery/window/ownership errors shown |
| 5. Content + reports | Draft/calendar/media, approval, per-target publishing, cached metrics | Real preview/consent, format validation, partial-failure handling, bounded retries |
| 6. Hermes read/draft | Narrow broker and reviewed tool-enabled profile | Injection/scope tests, no provider key in agent, no shell/SQL, bounded loops and cost |
| 7. Approved actions | Exact-payload approval and idempotent execution | Edited/expired/reused approval denied; recipient/account/cost bound to approval |
| 8. Ads + automation | Reporting first, then approved forms/spend/flows/broadcasts | Sandbox/test destinations, opt-out/human takeover, spend/recipient caps and global pause |
| 9. Optional extensions | Advanced numbers/calls, other networks/products | Explicit business approval, cost/region/KYC and recovery checks per product |

The current CRM also needs its already-documented production/authentication/database
release steps before exposing these private surfaces publicly. Connection callbacks
and webhook domains must be agreed and secured; do not reuse a temporary preview
origin as a permanent platform integration without that decision.

## 14. Open decisions and source contradictions

| Topic | What is known | What must be resolved |
| --- | --- | --- |
| Telegram intent | Zernio supports connected groups/channels | Whether Jardines also needs a private customer-service bot via a separate adapter |
| WhatsApp number | API and coexistence modes differ | Actual ownership, current provider/app, account eligibility, migration/rollback, desired calling/groups |
| TikTok reconnect | General connect schema supports multiple accounts and preserving same-account history | Platform prose warns replacing a different handle can delete history; get vendor confirmation before replacement/rename |
| TikTok lead forms | Stored-lead endpoints mention TikTok | Verify create/manage scope and real advertiser support; do not mirror Meta blindly |
| Analytics sync | Current schema has delta; older guide denies a cursor | Validate deployed delta behavior/cursor expiry before depending on it |
| Pricing/entitlements | Current usage-based all-features pricing; legacy/add-on prose remains | Check actual workspace, billing model/card/balance and allowed resource groups |
| Housing advertising | API exposes targeting/special-category options | Owner/platform policy review for the actual real-estate campaigns/market |
| Messaging policy | Windows, opt-outs and human handover affect sends | Approved consent text, retention, human ownership and autonomy limits |
| Publication/brand facts | CRM/landing contain owner-provided project material | Approved knowledge source and versioned commercial facts for Hermes |
| Full API parity | 1,244 operations documented in inspected schema | Account-by-account eligibility and an operation coverage registry, not an “everything works” promise |

These are implementation prerequisites, not questions requiring an answer to finish
this research document. No live vendor entitlement or platform-owner permission was
verified.

## 15. Research verification and reusable upstream projects

### What was checked

- Public organization, official platform/integration/security/pricing docs and Python SDK.
- Published schema downloaded, safe-parsed, hashed and counted; selected route/method
  references below checked against it. No schema-derived code was executed.
- Existing local CRM/Hermes documentation and implementation boundaries, including
  the three-field form, allowlisted BFF and current tool-free agent policy.
- Channel restrictions and contradictory sources explicitly separated from proposals.
- Structural validation: 24 distinct literal API paths exist in the inspected schema;
  local document links resolve, Markdown fences balance, and all 87 tag counts match
  the parsed operation inventory. No application build is needed for this passive document.

### What was not checked or performed

No vendor login, credential creation, OAuth consent, account connection, sandbox
activation, message, upload, campaign, billable API action, plugin installation,
Hermes permission change, database migration, runtime test, SSH operation, commit,
push or deployment. Some topical documentation URLs were not retrievable through
the research browser; their route-level inventory was checked against the published
schema instead. This is not an exhaustive SDK security/source audit.

### Official repositories worth reviewing before reusing code

| Repository | Useful reference | Why not install it as the CRM integration now |
| --- | --- | --- |
| [zernio-python](https://github.com/zernio-dev/zernio-python) | Backend SDK and operation mapping | Pin/test later; do not assume README/schema versions match |
| [zernflow](https://github.com/zernio-dev/zernflow) | Visual messaging/workflow product | Separate app; would not automatically inherit our auth, data model or approvals |
| [unified-inbox](https://github.com/zernio-dev/unified-inbox) | Unified inbox patterns | A reference app is not our durable CRM event/identity integration |
| [latewiz](https://github.com/zernio-dev/latewiz) | Calendar/composer/queue patterns | Preserve our design system and backend ownership |
| [ads-dashboard](https://github.com/zernio-dev/ads-dashboard) | Ads reporting examples | Reporting does not grant spend-management authorization |

Review each repository's actual license, maintenance and security before copying
code. Open-source example availability does not make the service itself open-source.

## Appendix A. Complete API-family inventory

Generated from the inspected schema's operation tags. Counts include deprecated
operations and do not certify feature eligibility. Each listed family is discoverable
in the [canonical contract](https://zernio.com/openapi.yaml). This compact inventory
covers the full schema without copying 1,244 parameter-heavy operations into a stale
manual. Use `operationId` as the stable adapter/coverage-registry reference, and review
schema changes before exposing new actions.

| API family (tag) | HTTP operations |
| --- | ---: |
| Account Groups | 4 |
| Account Settings | 20 |
| Accounts | 21 |
| Ad Accounts | 71 |
| Ad Audiences | 8 |
| Ad Campaign Results | 6 |
| Ad Campaigns | 70 |
| Ad Creatives | 18 |
| Ad Insights | 11 |
| Ad Library | 1 |
| Ad Rules | 11 |
| Ad Targeting | 6 |
| Analytics | 44 |
| API Keys | 4 |
| Automations | 31 |
| Blogs | 10 |
| Branded Calling | 17 |
| Broadcasts | 10 |
| Business Agent | 55 |
| Calendar | 10 |
| Calls | 3 |
| Changelog | 1 |
| Comment Automations | 6 |
| Comments | 15 |
| Commerce | 76 |
| Connect | 86 |
| Connected Apps | 2 |
| Contacts | 9 |
| Content Retention | 2 |
| Conversions | 32 |
| Creator Campaigns | 44 |
| Creator Portal | 14 |
| Custom Fields | 6 |
| Discord | 24 |
| Email | 37 |
| Feedback | 1 |
| Files | 9 |
| GMB Attributes | 3 |
| GMB Food Menus | 2 |
| GMB Location Details | 2 |
| GMB Media | 3 |
| GMB Place Actions | 4 |
| GMB Reviews | 5 |
| GMB Services | 2 |
| GMB Verifications | 4 |
| iMessage | 20 |
| Inbox Analytics | 7 |
| Instagram | 11 |
| Invites | 1 |
| Lead Gen | 10 |
| Ledger | 2 |
| LinkedIn Mentions | 1 |
| Logs | 1 |
| Media | 2 |
| Mentions | 2 |
| Messages | 24 |
| Messaging Ads | 3 |
| Phone Numbers | 31 |
| Posts | 13 |
| Product Catalogs | 19 |
| Products | 3 |
| Profiles | 5 |
| Queue | 6 |
| RCS | 13 |
| Reach and Frequency | 4 |
| Reddit Search | 3 |
| Reviews | 3 |
| Sequences | 10 |
| Slack | 1 |
| SMS | 22 |
| Support Assistant | 3 |
| Tracking Tags | 22 |
| Treasury | 19 |
| Twitter Engagement | 8 |
| Usage | 6 |
| Users | 2 |
| Validate | 4 |
| Verify | 3 |
| Voice | 18 |
| Webhooks | 7 |
| WhatsApp | 49 |
| WhatsApp Calling | 16 |
| WhatsApp Flows | 15 |
| WhatsApp Phone Numbers | 17 |
| WhatsApp Sandbox | 3 |
| WhatsApp Templates | 1 |
| Workflows | 15 |

**1,244 distinct HTTP operations; 1,245 tag memberships.** One operation
belongs to two families, so summing the rows double-counts that operation.

Revisit this inventory when the vendor specification version/hash changes.
