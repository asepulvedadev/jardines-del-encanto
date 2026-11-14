# Reviewed Zernio workflow adapter

Local adapter contract for `app.social.workflow`. No production activation, provider
test send, credential inspection, or vendor subscription was performed. API research
was checked against official Zernio documentation on 2026-11-14.

## Executable scope and limitations

- **WhatsApp approved template:** opens or continues a conversation for the selected
  existing CRM contact's exact international phone. The adapter converts an optional
  leading `+` to digits only. It requires an exact approved name/language and matching
  positional parameter count. This implementation supports simple text header, body
  and footer components only; named parameters, buttons, media, location and rich
  templates are rejected, not silently ignored.
- **WhatsApp text reply:** requires explicit account/conversation binding. The exact
  provider participant must equal the selected contact phone. A recent incoming
  message must prove the current 24-hour service window. Outgoing messages, activity
  timestamps, another sender, future timestamps and standby messages are not proof.
- **Facebook/Instagram:** blocked as `provider_control_policy_unreviewed`. Official
  documentation states that Zernio may take thread control and resend after a
  `not_thread_owner` failure. Reading `threadControl=app` cannot rule out a later
  ownership race, so workflow approval does not silently authorize this behavior.
- **TikTok:** blocked as `zernio_tiktok_eligibility_unverified`, not described as
  categorically unsupported. The platform-specific documentation supports eligible
  Business app replies (10 messages in 48 hours), but the aggregate list reference
  omits TikTok and this adapter has no reviewed eligibility/quota proof.
- **Telegram:** personal-contact outreach is unavailable. Zernio's documented inbox
  represents a connected group/channel, not private bot DMs. Never turn a CRM phone
  or a person-to-group binding into an inferred individual recipient.

Existing Meta conversation sends, including templates, require explicit app thread
control. Missing, `ai_agent`, `other`, or standby ownership fails closed. A template
for a previously unseen WhatsApp participant requires a complete account-scoped
conversation page; truncated or failed listings cannot establish that no thread
already exists. A newly appearing thread invalidates the frozen no-thread plan.

WhatsApp BSUID-only participants cannot currently be substituted for a CRM phone.
They need a separately reviewed identity-mapping design; no new required CRM fields
are added here. The adapter never invokes thread-control or marking-read endpoints.

## Preparation, options and authorization

`options(db, account_id=None)` emits bounded allowlisted UI records only. Account
records include verified platform/ownership/connection availability. Templates are
approved supported definitions only. Conversation records preserve exact participant
and account identity. `can_reply=false` with
`reason=zernio_window_verification_required` means **selectable for preparation**,
not authorized to send: listing does not trigger up to 100 separate message-history
requests. Other unavailability reasons remain blocking.

`prepare(db,node,contact,binding=None,cache=None)` is read-only. Its summary contains
the sender, exact participant, rendered message or full template text components,
language and ordered parameter values. Its private JSON-safe plan contains identity
revisions and an HMAC seal, never raw credentials or a vendor response. The optional
cache is one request-local dictionary, owned and discarded by the caller, for shared
account/template/conversation reads. It is never used by `check` or `dispatch`.

`check(plan)` performs fresh account/profile/configuration/preference checks and
revalidates template identity or conversation ownership/window. Credential changes,
including key rotation, invalidate existing plans. This uses the existing private
REST API configuration, not the read-only MCP OAuth `accounts:read` grant.

The engine must hold the exact initial human activation approval and commit its
unique per-step reservation **before** calling `dispatch(plan,request_id)`. Dispatch
locks against credential rotation, rechecks fresh identity, then attempts exactly
one outbound HTTP request. The adapter does not grant authority or replace durable
engine reservations. Reusing a request ID is not permission to call dispatch again.

`state=completed` and `receipt.status=accepted` mean Zernio accepted the request,
**not delivered, read, answered, qualified or sold**. Returned receipts contain only
bounded message/conversation identifiers and acceptance status. Any timeout, redirect,
non-success HTTP result, malformed receipt or other uncertain submission returns
`unknown`; there is no retry. A reply carries the documented `Idempotency-Key`, but
Zernio explicitly warns that ambiguous failures can release keys after acceptance.

## Network and inbound boundary

The adapter constructs only fixed `GET` account/template/conversation/message-list
routes and the two reviewed `POST` actions below. Opaque conversation IDs are encoded
as one path segment. There are no arbitrary URLs, redirects, downloads, attachments,
provider error passthroughs or changes to the older `social.provider` allowlist.
It reuses `social.transport.https_connection("zernio.com", timeout=4)` and therefore
the existing verified TLS and optional fixed CONNECT egress. Request JSON is at most
32 KiB; response reads at most 1 MiB plus one overflow-detection byte. Each upstream
call is bounded; the engine must additionally bound total preparation work across
its audience and nodes.

`normalize_event(payload)` is an I/O-free parser. Call it only **after** the existing
raw-body HMAC, header identity, ownership and replay/body-hash validation. It accepts
only non-test, non-standby incoming `message.received` events. It checks consistent
account/platform/conversation/sender identity and returns no message text or media.
Use `conversation.platformConversationId` for correlation with list-conversation
bindings: `message.conversationId` and `conversation.id` are internal IDs. The
engine must compare profile, account, participant and conversation, and persist a
new-template receipt's conversation identity before relying on exact reply matching.

## Official API evidence

- [WhatsApp inbox](https://docs.zernio.com/platforms/whatsapp/inbox):
  `POST /v1/inbox/conversations` accepts `accountId`, digit-only `participantId`,
  `templateName`, exact `templateLanguage`, and flat ordered `templateParams`;
  successful `data` includes `messageId` and `conversationId`.
- [Template reference](https://docs.zernio.com/whatsapp/get-whatsapp-templates) and
  [template guide](https://docs.zernio.com/platforms/whatsapp/templates):
  `GET /v1/whatsapp/templates?accountId=...&status=APPROVED` returns `templates`.
- [List conversations](https://docs.zernio.com/messages/list-inbox-conversations):
  account/profile filters, opaque IDs, participant identity, `threadControl`,
  `pagination.hasMore` and failed/skipped account metadata.
- [Message reference](https://docs.zernio.com/messages/send-inbox-message):
  read-only `GET /v1/inbox/conversations/{id}/messages` with `accountId`, descending
  sort and bounded limit; `POST` to the same path accepts `accountId` and `message`;
  response `success/data`, idempotency and ambiguous-failure caveats.
- [Facebook inbox](https://docs.zernio.com/platforms/facebook/inbox) and
  [Instagram inbox](https://docs.zernio.com/platforms/instagram/inbox): automatic
  provider take/resend behavior and the prohibition on automated HUMAN_AGENT tags.
- [TikTok inbox](https://docs.zernio.com/platforms/tiktok/inbox) and
  [Telegram](https://docs.zernio.com/platforms/telegram): channel-specific limits.
- [Incoming event](https://docs.zernio.com/webhooks/inbox/message-received): event,
  message, sender, account, conversation and standby shapes. Its page's embedded
  official schemas define `InboxWebhookConversation.platformConversationId` and
  `InboxWebhookAccount.accountId`; the Markdown alternate documents the payload.

## Deterministic verification

From `apps/api`, run:

```sh
.venv/bin/python -m pytest tests/test_workflow_social.py -q
.venv/bin/ruff check app/social/workflow.py tests/test_workflow_social.py
```

Tests replace configuration, connection preferences and TLS connections with
synthetic fixtures. They do not need a database, real credentials, OAuth sessions,
provider requests or paid effects. Engine reservation, approval, scheduling and
authenticated webhook integration require the separate workflow engine checks.
