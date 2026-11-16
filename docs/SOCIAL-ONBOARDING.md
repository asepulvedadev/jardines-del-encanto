# Social lead welcome

Sara's first-contact welcome is a server-owned workflow, not an LLM instruction.
It is enabled only for explicitly selected Jardines WhatsApp and Facebook accounts.
Other brands in the same Zernio profile are excluded. Verified developer messages
retain their existing privileged routing; form names and phone fields grant no authority.

## Order and identity

1. Authenticate and deduplicate the incoming Zernio webhook.
2. Re-read the exact original conversation and incoming message from Zernio.
3. Extract the actual named ad-form fields, regardless of field order. Use verified
   sender contact details only when the form omits them. Opaque platform identifiers
   are routing identifiers, never phone numbers. Missing fields produce one concise
   request for the full name and mobile number; conflicting fields stop intake.
4. Commit the contact and pipeline record before generating or sending audio.
   New contacts enter Nuevo. Existing contacts, source and won/contacted stages are
   not overwritten; a normalized phone deduplicates contacts across channels.
5. Send the owner's fixed welcome as an MP3 attachment using the pinned verified
   Sofía voice. Synthesize once per immutable script/provider identity and reuse it.
6. Only after provider acceptance of the audio, send the website and privately
   configured project-group invitation together in a separate text message.

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
- Explicit SALIR/STOP and Spanish no-contact requests suppress the thread. This does
  not constitute a global marketing-consent database or authorize broadcasts.
- At most100 new threads are admitted per rolling24hours, with at most10 immutable
  audio cache entries. Raw content and MP3 bytes remain private; no public media URL.
- This specific fair welcome expires at the end of November22,2026 in Bogotá. It
  must not keep advertising an already elapsed event. No hour was supplied or invented.
- Activation applies to NEW signed incoming messages. Do not replay historical inbox
  threads, rewrite old jobs or fabricate events to demonstrate a customer send.

## Verification

Run `apps/api/tests/test_social_onboarding.py`, landing registration, WhatsApp agent
and audio regressions in the isolated disposable PostgreSQL test database, serially.
The tests cover contact capture, shuffled form fields, opaque identifiers, cross-channel
phone deduplication, existing won leads, ordered delivery, missing fields, uncertain
outcomes, source/revocation/handover/window checks and unchanged developer routing.

Official contracts: [inbox message send](https://docs.zernio.com/messages/send-inbox-message),
[Facebook inbox](https://docs.zernio.com/platforms/facebook/inbox),
[conversation detail](https://docs.zernio.com/messages/get-inbox-conversation),
[message detail](https://docs.zernio.com/messages/get-inbox-conversation-messages).
