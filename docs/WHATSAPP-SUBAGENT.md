# Sara WhatsApp subagent

Customer traffic uses a dedicated, text-only Hermes subagent, not a canned-reply
rule or the administrator's Sara conversation. It receives only its published instructions,
project knowledge, and up to three earlier exchanges from the same WhatsApp
account, participant, conversation and configuration version. It has no CRM tool,
credentials, filesystem actions, app skills, or self-programming authority.

## Configuration and learning

In **Configuraciones → Sara WhatsApp**, set the existing Zernio account ID,
international business number, instructions, reference knowledge and up to two
trusted developer numbers. Names are labels only; authorization uses the exact
E.164 number proven in authenticated, freshly revalidated inbound messages.
The developer run receives the verified developer's configured name alongside the
unaltered message in a structured prompt. It receives neither developer's phone
number or the other developer's name. This label grants no additional capability;
source-bound authorization and revocation checks still run independently.
Developer authorization and channel routing numbers are not embedded as configuration
in the public repository. The existing owner-approved public adviser contact remains
in the immutable customer-assistance floor.

The authenticated web settings save explicitly binds a real administrator owner.
Previously saved channel configurations do not acquire developer authority until
that owner saves them again. Revocable developer runs use their verified inbound
job, phone/account/profile identity and owner grant; they never create or borrow a
browser session. Customer messages always remain on the tool-free path.

Verified developers can converse with the private scoped broker to create, inspect,
update, test and install their owner's Sara skills/tools; edit the shared published
configuration; explicitly teach knowledge; enqueue bounded brand-aware image jobs;
and run isolated synthetic customer simulations. Only typed allowlisted actions
are available. The two verified developer numbers can also directly read CRM
records; create and edit clients (creation adds a New pipeline lead); move deals
between New, Contacted and Won; add notes; create and complete follow-ups; inspect
sequence definitions/runs; create and edit validated sequence drafts; and pause or
stop existing runs. These business actions reuse the same canonical CRM/workflow
services, version checks, activity history, capability switches and once-only
broker call receipts. They do not create browser sessions or pending web proposals.

WhatsApp sequence listings are compact and paginated (`query`, `limit`, `offset`);
`workflows.definitions` with `id` retrieves one exact document before editing it.
`workflows.run` without `id` similarly lists execution IDs, status and versions;
with `id` it returns the existing exact run details. Definition IDs are never used
as execution IDs. The legacy web definition lookup with empty arguments keeps its
existing full-list response.

Sequence preparation, activation and resumption still require exact human review
in Secuencias; WhatsApp cannot authorize bulk messaging or calls. Public customers
remain tool-free: mentioning a developer name or asking for CRM access does not
create a developer grant. Removing a developer, disabling the owner/channel or
revoking a connection immediately blocks subsequent CRM calls. Developer tools
cannot modify channel grants, change connection permissions, run arbitrary source,
expose secrets or impersonate web sessions. Custom tools may target only the same safe capabilities; installed
custom tools and skills become visible on the next turn. The catalog excludes
other owners' definitions. Image and simulation jobs return inspectable receipts;
unknown outcomes must not be automatically resubmitted.

Trusted developers can also send `/estado` or `/aprender <text>` to the business number.
`/aprender` creates a knowledge proposal, not an executable command or an immediate
change to public answers. An authenticated administrator approves or rejects it in
the web interface. Approval publishes a versioned knowledge update and pauses the
agent for explicit review/reactivation. Customer messages cannot teach the agent,
change developer identity, run tools, or become shared knowledge.

Web and WhatsApp share one published profile with compare-and-swap versions.
Changing it revokes queued or generating responses based on the previous profile.
The initiating developer training job alone may advance to its own new version;
all other obsolete jobs are blocked. Conversation history is isolated by participant,
channel configuration and shared profile version. Channel settings cannot silently
overwrite newer shared instructions or knowledge without the current shared version.

Training means versioned instructions and retrieval context, not model fine-tuning.
The immutable public-agent safety floor overrides references and conversation text.
It prohibits invented commercial/legal promises, payments, bookings and admin actions.

## Activation requirements

1. Apply additive migrations through `017_sara_shared_profile_grant.sql` with
   the migration owner. Preserve the checksums of previously applied migrations.
2. Install the reviewed `operator_public.py` policy alongside the existing bridge
   and provider policies; mount it read-only in both. Preserve the existing networks,
   model, credential boundary, operator tool validation and other applications.
3. Enable only the dedicated worker with `CRM_WHATSAPP_AGENT_WORKER_ENABLED=1`.
   This does **not** enable the outbound sequence worker.
4. Configure a real Zernio REST credential and matching profile through the existing
   private connection settings. MCP account-read authorization alone is insufficient.
5. Register and verify the HMAC webhook subscription for `message.received`, scoped
   to the intended account/profile. A locally generated secret alone is not proof
   of registration; `webhook_registered` must reflect an actual verified subscription.
6. Review and explicitly activate inbound-only replies for the configured number.
   Fresh vendor metadata must prove the account's WhatsApp number, app ownership,
   conversation recipient and customer-service window. Unknown identity fails closed.

The worker starts disabled. Configuration is saved paused when prerequisites are
missing; an enabled flag is not reported as verified availability.

## Delivery invariants

- Webhooks authenticate raw HMAC, profile membership and stable event headers before
  durable enqueue. Provider and model calls never delay webhook acknowledgment.
- Only first-seen, non-test, non-standby incoming text after activation is enrolled.
  Events older than fifteen minutes, other accounts, own numbers, and malformed
  identities are ignored. No campaign, contact-list enrollment, or conversation opener.
- Durable uniqueness covers both event ID and account/conversation/message identity.
- Claims serialize across API processes; at most six per minute, one thousand per
  rolling day and thirty per conversation per day. These are safety/spend ceilings,
  not promised throughput. The owner raised both rolling daily limits to 1,000
  on November 16, 2026: agent reply claims and new welcome conversations. The six/minute
  and thirty/conversation limits remain unchanged. Public provider calls also have a
  separate six/minute cap.
- Before sending, a fresh source read proves exact incoming text and sender. Existing
  reviewed Zernio preparation/dispatch rechecks ownership, connection state and the
  24-hour WhatsApp window. Literal model output is never template-interpolated.
- Configuration changes revoke pending/generating jobs. A committed send reservation
  precedes external I/O; pause/reconfiguration serializes with final dispatch.
- Ambiguous or interrupted reservations are held, never automatically retried. Vendor
  acceptance is not delivery or read confirmation. No production sends are simulated
  as successful.
- A socket/HTTP transport failure during a read-only Zernio verification GET gets
  one fresh-connection retry (four-second socket timeout per attempt). HTTP rejection,
  malformed/oversized responses, failed ownership checks and POST submissions are
  never retried. The complete final identity/control/window validation still runs.

## Verification

The owner-requested November 16 welcome runs once per verified participant,
account, profile and channel, not once per incoming message. On WhatsApp and
Facebook its separate, durably reserved messages are **audio → official website
→ WhatsApp group**. Each URL has its own explanation; the group invitation
explains that it provides information before the event. The existing recording,
voice/model, URLs and routing identity remain unchanged.

An initial greeting without identity still receives the three-message welcome.
Only genuine name/phone details create a CRM contact through `capture_contact()`.
Missing identity is requested after the group invitation, never before the audio.
Verified follow-up inputs are queued separately (maximum 30 per conversation per
rolling day), so later chatter cannot overwrite a pending registration form.
The existing independent intake repair remains available. STOP suppresses all
known conversations for the same scoped participant.

Migration 026 adds participant claims, separate text receipts and the input queue.
Migration 027 indexes the input budget. Migration 028 corrects historical claim
selection: opt-outs and uncertain sends take priority over unfinished welcome
progress, and accepted audio takes priority over an older pending conversation.
Historical opt-outs propagate across the scoped participant; runtime guards also
check sibling conversations rather than trusting only the canonical claim.
It preserves completed/ambiguous history; interrupted reservations become unknown.
An accepted old audio resumes at the website, not the audio. Old combined-link
receipts remain historical and are never replayed. An additional conversation for
an existing participant may capture real identity but cannot repeat the welcome.
Unknown send outcomes are never retried automatically.

TikTok remains excluded from the audio agent and generic workflows: Zernio documents
text/image replies, not audio. A separately owner-activated private-message text
registration lane is documented in SOCIAL-ONBOARDING.md; it does not bypass the
generic workflow eligibility guard or activate an account automatically. The fair-specific expiration remains November 23, 2026,
00:00 Colombia; this change does not extend the dated campaign.

All ordinary tests use synthetic phone numbers, isolated `jardines_crm_test` data,
and mocked provider traffic. No real customer message, campaign, provider key or
administrator conversation is required. Browser visual checks and a pinned-Hermes
runtime test are distinct from mocks; report their actual results separately.

## Requested spoken answers

An explicit current-message request such as `Respóndeme en audio`, `Envíame una
nota de voz`, or `/audio <question>` selects a private MP3 attachment. A negated
request or a question about audio remains text. This is not a persistent preference.
The existing inbound-only channel and its enabled ElevenLabs connection authorize
this narrow rendering path; customer models acquire no voice tools or developer
permissions. It starts no Retell call or ElevenLabs conversational session.

Hermes generates the answer using the same published knowledge, training and
participant-scoped history. ElevenLabs speaks that exact answer using the verified
server-selected default voice/model from **Configuraciones → Conexiones → ElevenLabs**.
Never select a provider voice by display-name similarity alone: a Retell custom
voice ID is not necessarily its underlying ElevenLabs ID. Confirm the mapping or
the intended existing ElevenLabs voice with the owner first.

Migration `020_whatsapp_audio.sql` adds private source-job-bound artifacts, not fake
human proposals. The inbound job and the gateway each reserve before paid synthesis.
The exact original MP3 and its hash are persisted before one sealed multipart send
to the original conversation. The same worker handles both phases; no extra worker
or policy-overlay installation is needed. Rendering is limited to 1,500 characters,
2 MiB, twenty reservations per owner per rolling day, and at most 100 retained
artifacts within a 25 MiB owner quota. Unknown paid/send outcomes consume the
reservation and are never regenerated or replayed automatically.

Source, enabled owner/channel/connections, provider revision, configured voice and
shared profile are rechecked. Recipient ownership, handover and the service window
are prepared before paid synthesis and checked again before the supervised send.
Pause/configuration changes share the existing final-send locks. Preparation/dispatch
failure is recorded with a sanitized error; no silent retry or public hosting occurs.

The result is an **MP3 audio attachment**, not a native recorded voice-note bubble.
Zernio requires mono OGG/Opus and `voiceNote: true` for that representation. Provider
acceptance is not delivery/read proof. Incoming WhatsApp audio transcription and
voice cloning are not introduced by this change.

The initial live preflight found no configured REST credential in the CRM, despite
the number appearing in Zernio's dashboard. Production activation remains pending
until that connection and webhook are actually verified. Zernio also displayed a
business-verification restriction; this implementation does not bypass it.

## Private concept-image delivery

Developer-origin image generation now inserts a once-only attachment outbox in the
same transaction that persists the generated PNG. Migration
`019_sara_image_delivery.sql` retains immutable owner, source-run, recipient binding
and PNG hash. Web-only jobs never acquire a WhatsApp recipient; public customer
messages do not acquire developer capabilities.

Enable the separate opt-in worker `CRM_WHATSAPP_IMAGES_WORKER_ENABLED=1` only after
the image service, verified WhatsApp developer configuration and REST messaging
connection are active. It revalidates the current grant, owner, channel, credentials,
PNG, exact conversation ownership, human handover and customer-service window before
one committed reservation and one multipart submission. Revocation validation uses
the same connection holding the final agent/control locks to avoid self-deadlocks.

The transport sends the original private PNG directly as multipart `attachment`
with `accountId`, a fixed concept caption and a stable idempotency key. It uses no
public upload URL or arbitrary destination. Vendor acceptance is not delivery/read
confirmation; malformed or uncertain responses stay unknown and are not retried.
Read-only preparation and final send each run in a supervised fixed-module subprocess.
A timeout kills and waits for that process before releasing credential/authority
guards, covering DNS, connection setup, TLS and a slow response after `Connection: close`.
Credentials use stdin, never argv or logs; only the existing database/config/fixed-proxy
environment is inherited. The child cannot choose a new endpoint or spawn agent tools.

WhatsApp images are conservatively capped at 5,000,000 bytes. Larger valid PNGs
remain private web artifacts with `image_exceeds_whatsapp_limit`; there is no hidden
resize, regeneration, MIME relabeling or public-hosting fallback. The fixed Zernio
CONNECT relay keeps the same host/DNS/connection/deadline restrictions with an 8 MiB
aggregate encrypted-traffic allowance. Existing JSON workflow request caps stay 32 KiB.

Contracts: [send attachments](https://docs.zernio.com/messages/send-inbox-message),
[WhatsApp media limits](https://docs.zernio.com/platforms/whatsapp/reference).
This local implementation is not evidence of a real image or WhatsApp delivery.

## REST source-content compatibility

Signed inbound webhooks carry `message.text`, but the Inbox REST history returns
the same content in each record's `message` string. Source verification compares
that canonical REST field with the signed inbound content, retaining legacy `text`
records only when they are unambiguous. Conflicting dual fields fail closed.
Account, conversation, message, sender, direction, deletion and standby checks stay
unchanged. Regression tests exercise the real matcher rather than mocking it.

The specialized agent stores the signed webhook's opaque `conversation.id` for
REST lookup/reply; `platformConversationId` is not substituted for it. Message
verification still uses the exact platform message ID returned by Inbox history.

For untouched WhatsApp threads, Zernio omits `threadControl` until a handover has
occurred ([vendor contract](https://docs.zernio.com/messages/list-inbox-conversations)).
Only that absent-key WhatsApp case is supported alongside explicit `app` control.
Explicit null/external/AI-agent control and standby messages still block replies,
and every dispatch rechecks current ownership. Facebook/Instagram rules are
unchanged. No thread-control takeover request is issued.
