# Social lead welcome

Sara's first-contact welcome is a server-owned workflow, not an LLM instruction.
It is enabled only for explicitly selected Jardines WhatsApp and Facebook accounts.
Other brands in the same Zernio profile are excluded. Verified developer messages
retain their existing privileged routing; form names and phone fields grant no authority.

## Order and identity

New WhatsApp enrollments, including replies to
`jardines_db36df695b5e19dabfbe7ca17b628228_v4`, use **audio → identity request or
confirmation → canonical registration → website → project WhatsApp group**.
The two links are separate, ordered messages. No template-name claim is inferred
from a bare “sí”: this safer identity-first rule applies to all new WhatsApp
enrollments on the configured project account. Developers retain their routing.

1. Authenticate and deduplicate the incoming Zernio webhook.
2. Re-read the exact original conversation and incoming message from Zernio.
3. Extract the actual named ad-form fields, regardless of field order. Use verified
   sender details as confirmation candidates, not silent WhatsApp registration.
   Opaque platform identifiers are routing identifiers, never phone numbers.
4. Send the existing fixed MP3 welcome with the configured, pinned voice. Then ask
   for full name and mobile, or show both verified candidates and ask “Confirmo”.
   Self-declared labeled details may already establish identity. Partial fields
   survive separate messages. Conflicting details never create a contact.
5. Commit the canonical contact/deal before sending either link.
   New contacts enter Nuevo. Existing contacts, source and won/contacted stages are
   not overwritten; a normalized phone deduplicates contacts across channels.
6. Send the official website, then the privately configured project-group link.
   Synthesize audio once per immutable script/provider identity and reuse it.

Migration032 preserves historical enrollment mode and receipts: it does not replay
old welcomes. Facebook keeps its existing audio → website → group → missing-identity
question order. The separately configured TikTok text-only flow is unchanged.

WhatsApp source is `whatsapp`; Facebook source is `social_campaign`. The private
ledger retains the exact account, original thread, participant and event provenance.
Always reply to the original thread, NEVER to a number found inside a submitted form.
MP3 acceptance is not a delivery/read receipt or a native WhatsApp voice-note guarantee.

## Safety and operations

- Use the existing `CRM_WHATSAPP_AGENT_WORKER_ENABLED=1` worker, no new daemon.
- Additive migrations021–022 create private configuration, a once-only ledger and
  a private shared MP3 cache. They do not modify existing commercial records.
- Owner-only maintenance calls `app.social.onboarding.configure` with the actual
  enabled administrator ID, configured Zernio profile, exact account/platform map,
  approved group URL and explicit Facebook takeover consent. This pins current
  credentials and ElevenLabs voice identity. No invitation or credentials belong in Git.
- Read back the configuration after activation. Do not reset existing Sara knowledge,
  developer numbers, integrations, root gateway policies or unrelated webhook events.
- The existing project webhook must include `message.received` and exactly the target
  account allowlist. Preserve its URL, HMAC secret and headers. Do not enable all accounts.
- Recheck active accounts, connection switches, administrator, credential revision,
  message content, source identity, 24-hour incoming window and thread control before
  each submission. Standby/human ownership and opt-outs stop the welcome.
- Owner consent permits Zernio's documented implicit Facebook takeover/resend only
  on the configured page. Explicit other/human ownership remains blocked.
- Reservations commit BEFORE external I/O. An interrupted or ambiguous submission is
  `unknown` and is never automatically replayed. `audio_accepted` resumes with links
  only. `blocked` and `unknown` require operator inspection, not blind resets.
- Explicit SALIR/STOP, “No recibir información”, “No gracias”, bare “No” and clear
  disinterest persist a participant/account/profile/platform refusal. There is no
  acknowledgement or automatic opt-in. Ordinary negative questions such as “No
  entiendo el precio” do not unsubscribe the customer. Refusal recording is independent
  of welcome activation, expiry and public-agent readiness. Refusals commit without waiting behind a network send. Final text, audio and
  workflow submissions recheck the durable ledger; queued jobs cannot bypass it.
  A submission already in flight or accepted externally cannot be recalled.
- At most 1,000 new threads are admitted per rolling 24 hours, with at most10 immutable
  audio cache entries. Raw content and MP3 bytes remain private; no public media URL.
- This specific fair welcome expires at the end of November22,2026 in Bogotá. It
  must not keep advertising an already elapsed event. No hour was supplied or invented.
- Activation applies to NEW signed incoming messages. Do not replay historical inbox
  threads, rewrite old jobs or fabricate events to demonstrate a customer send.

## Verification

Run `apps/api/tests/test_template_followup.py`, `apps/api/tests/test_social_onboarding.py`, landing registration, WhatsApp agent
and audio regressions in the isolated disposable PostgreSQL test database, serially.
The tests cover contact capture, shuffled form fields, opaque identifiers, cross-channel
phone deduplication, existing won leads, ordered delivery, missing fields, uncertain
outcomes, source/revocation/handover/window checks and unchanged developer routing.

### Native Zernio broadcast opt-outs

Migration032 adds the private `crm.social_opt_outs` ledger. The existing worker
attempts one bounded subscription sync at a time. It resolves the original Inbox
conversation's `contactId`, verifies the exact account/participant channel and only
PATCHes `isSubscribed: false`. A read-back must confirm it. There is no message,
opt-in, guessed phone search, extra credential or arbitrary provider route.

Because subscription is contact-wide, contacts with channels belonging to another
brand/account are blocked for operator review rather than changed globally. Missing
contact IDs and credential changes also require review. Transient failures retry
this idempotent unsubscribe at most five times, five minutes apart. Local suppression
does not wait for remote synchronization and survives later incoming messages.
Operators must inspect pending/blocked rows and exclude those people manually
before a native Zernio campaign; do not claim a successful remote unsubscribe from
the local flag alone. Importing a spreadsheet does not establish commercial opt-in.

Implementation and tests do not deploy, modify an approved template, import the
owner's real audience or send a live broadcast. Apply migration032 through the
existing authorized release gate before restarting the application. Before rolling
back to an older image without these consent guards, pause the WhatsApp worker and
reconcile pending refusals; an additive schema alone does not preserve old-code safety.

Provider contracts checked 2026-11-17:
[Contacts lookup](https://docs.zernio.com/contacts/list-contacts),
[Contact channels and subscription](https://docs.zernio.com/contacts/get-contact),
[Subscription update](https://docs.zernio.com/platforms/whatsapp/contacts).

Official contracts: [inbox message send](https://docs.zernio.com/messages/send-inbox-message),
[Facebook inbox](https://docs.zernio.com/platforms/facebook/inbox),
[conversation detail](https://docs.zernio.com/messages/get-inbox-conversation),
[message detail](https://docs.zernio.com/messages/get-inbox-conversation-messages).

## Owner-authorized unanswered recovery

An operator may call `onboarding.recover_unanswered(db, event_id, actor_id=owner_id)`
only after explicit owner approval for the missed inbound messages. This maintenance
entry point is not exposed through HTTP, public models, tools or webhook fields.
It requires the current enabled administrator owner and an already authenticated,
persisted `message.received` receipt from the configured account/profile.

Ordinary webhook enrollment retains its fifteen-minute freshness requirement.
Explicit recovery may consider the original incoming event within the existing
24-hour reply window, after activation and before the fair expiry. It never
rewrites source timestamps, replays a webhook or resets an existing job. Any prior
agent-job, completed, uncertain, suppressed or already-sent welcome history excludes
recovery. A single current-version blocked welcome may be recovered only when it
has no receipts, no asked question, no competing queued input and the canonical
participant claim. Its live history must independently prove no outgoing reply.

Recovery reuses canonical enrollment, its daily quota, participant claim and input
queue. Migration 029 adds a private source-event audit marker. Live Inbox reads run before taking the shared enrollment lock, so recovery does
not block fresh webhook enrollment. Account scope and history are rechecked under
the short enrollment transaction. A live Inbox check must prove the same account, participant, message, content and app control before
the new claim commits. Incomplete or explicitly partial/paginated history, a newer incoming message or
any outgoing message excludes the candidate. Before every welcome phase, the worker rechecks
that no other reply appeared; only its own accepted phase receipts are exempt.
Once the group phase is accepted, ordinary identity capture continues unchanged.
A failed proof rolls back enrollment, and uncertain submissions remain held.

Ambiguous identity fields do not halt a verified welcome. No ambiguous name or
phone is saved; the existing identity question follows the group invitation.

## TikTok private-message intake

The separately activated TikTok lane is **text-only** and accepts authenticated
`message.received` DMs for one explicitly configured Jardines account. Comments,
comment-to-DM, outgoing events, other accounts and generic workflow sends remain
excluded. It does not change WhatsApp/Facebook activation versions or audio order.

The sequence is introduction/request for `Nombre completo:` and `Celular:` → wait
for both valid, self-declared fields → canonical CRM contact/deal capture → text
registration confirmation → website → configured WhatsApp-group invitation.
Partial identity survives separate messages, but TikTok names must be explicitly
labeled `Nombre completo:` or `Full name:`. Ordinary interest phrases, display
names and opaque IDs are not registration identity. No links or registration claim precede persistence.
The contact INSERT trigger queues the existing two internal team notices in that
same transaction, with TikTok shown as origin. Existing phone records and stages
are preserved without duplicate new-lead notices. Hourly report category contracts
remain unchanged; TikTok contacts currently belong to their existing other category.

Migration 030 adds independent private configuration, text phase receipts and a
rolling reply-reservation ledger. Activation is not automatic: an enabled owner
calls `tiktok_intake.configure` with the exact profile/account and a recent signed
DM receipt. A live Inbox read must independently verify that source. The existing
Zernio credential/profile, project group, connection switches, control ownership
and administrator must match. This does not reconnect an account or infer DM
eligibility from posting access. Provider eligibility remains required; no permission
error is bypassed. Verify the internal-notice configuration separately before activation.

Each external phase requires a durable reservation. At most ten local reservations
per scoped participant are allowed in a conservative rolling 48-hour window,
including uncertain outcomes. Complete live history adds other outgoing messages
to that budget. Partial history, manual replies after intake starts, STOP, revoked
configuration, stale sources or explicit human ownership halt sends. Original source
messages must be within 48 hours; WhatsApp/Facebook retain their 24-hour guard.
An ambiguous submission is never automatically retried. Identity can still be
persisted when the outbound budget is exhausted. No TikTok TTS/audio call is made.
The existing fair expiry still applies; activation does not extend the campaign.

Verification uses signed synthetic DMs and fake Inbox/TTS in the isolated CRM test
database, including cross-channel regressions, ordered receipts, opt-outs, 48-hour
expiry, ten-reply boundaries and concurrent reservation attempts. Production
activation and an actual platform-accepted send are separate operational checks.

Provider contract: [TikTok Inbox](https://docs.zernio.com/platforms/tiktok/inbox).
