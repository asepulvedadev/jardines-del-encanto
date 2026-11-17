# WhatsApp broadcasts and cold-lead provenance

## Scope

The CRM **Envíos masivos** sidebar section imports a UTF-8 CSV (comma, semicolon
or tab delimiter, BOM/quoted values supported), reviews an approved template and
requires a separate explicit paid-send confirmation. This implementation is local
until an owner-authorized deployment applies migration `031_whatsapp_broadcasts.sql`.
No live campaign or real-recipient test is part of implementation verification.

The CSV has explicit name and phone column mapping, a 512,000-byte limit and at most
500 data rows per campaign. Validation reports invalid row numbers and normalizes
phones with the existing CRM helper. Repeated normalized numbers are omitted;
invalid rows must be corrected before saving. No CSV is executed or stored as a file.

## CRM identity and reporting

Saving creates an immutable local campaign and all its recipient memberships in one
transaction. It sends **nothing**. A caller-held UUID makes retries of the same import
idempotent; changes under the same UUID are rejected. The existing phone uniqueness
constraint and shared conflict-safe intake protect against simultaneous web, Sara,
social and CSV intake. Existing names, sources, versions and pipeline stages stay intact.

Only contacts newly inserted by this import receive a cold-lead provenance record.
They start in Nuevo with source WhatsApp. Existing contacts receive campaign membership,
not a cold reclassification. Membership never implies delivery or customer interest.

The dashboard shows two global, disjoint counts:

- **Leads en frío · WhatsApp masivo:** contacts originally created by CSV broadcasts.
- **Leads de campañas de redes:** source `social_campaign`, excluding cold provenance.

These two cards are not a partition of all CRM contacts: web, referral and in-person
origins remain separate. Existing total/pipeline/landing analytics are preserved.
Clientes and Pipeline support server-side campaign or cold-provenance filtering,
including matching records outside the unfiltered first 500. The existing per-view
500-row limit and warning remain; campaign label lists show the latest 100 campaigns.

## Approved templates

Templates and connected WhatsApp accounts come from the existing private Zernio
configuration and profile-scoped account verifier. No new API key is exposed to the UI.
Only APPROVED name/language pairs are selectable. The selected template and credential
revision are frozen at import, then verified live again before paid execution.

Supported templates: static content, numbered body/header text variables, image/video/
document header links, static buttons and dynamic URL buttons. Body values are fixed
for the campaign, not per-row CSV personalization. Named variables, carousels, OTP and
other unsupported component shapes are blocked visibly, never silently stripped.
Media must be publicly accessible HTTPS and meet Meta's type/size limits; the UI does
not upload private CRM documents to Zernio. Confirmation includes the actual body,
header, footer and button targets. It never shows a guessed price.

## Consent and audience safety

Import requires the administrator to attest WhatsApp commercial-message authorization
and record its source. A purchased list or mere presence in a CSV is not consent.
Remove opt-outs before import. No automatic opt-in or re-subscription is performed.

After the human types `ENVIAR N` and confirms:

1. Acquire a per-campaign PostgreSQL advisory lock; enforce draft/version/count.
2. Reverify enabled Zernio/WhatsApp connections, account ownership/activity, approved
   template revision and credential identity before any remote mutation.
3. Commit the irreversible attempt marker before making any vendor write.
4. Bulk-import the frozen audience into Zernio with an unguessable campaign-specific
   tag. Existing tags merge, without writing `isSubscribed`.
5. Create a native WhatsApp broadcast with that tag and `isSubscribed: true` segment.
6. Materialize the segment, verify the owned broadcast and enumerate the complete
   audience with bounded pagination. Reject unexpected/duplicate phones, incomplete
   results, explicit opt-out/block flags, non-pending recipients or count mismatches.
7. Send once; never automatically replay any vendor write.

Remote unsubscribed contacts can reduce the actual eligible audience. The displayed
CRM import count is not a claim that all those contacts were reached. Meta/Zernio
limits, anti-spam decisions, balance and recipient errors may further reduce delivery.

## Failure and reconciliation

State progresses `draft → preparing → sending → submitted`, with provider-derived
`completed`, `failed` or `cancelled`. Timeouts, unexpected responses and partial failures
become `unknown`. A crash may leave preparing/sending. None of these states can invoke
send again. Do not reset an attempt to draft in SQL or duplicate a campaign to retry
an uncertain send without investigating the native Zernio broadcast first.

`Consultar entrega en Zernio` performs account-scoped reads only and updates aggregate
and recipient status. It uses the same lock as sending, preventing stale reads from
replacing newer attempt state. An unknown create without a persisted provider ID
requires operator reconciliation in Zernio; there is deliberately no blind retry button.

All endpoints use the existing administrator session, exact Origin and CSRF checks.
The Next gateway admits only finite routes, rejects arbitrary query strings, bounds
request/response bytes and forwards no provider credentials. Fixed-host vendor transport
has bounded timeouts/body size, no redirects and no mutation retries. No public webhook,
unsolicited autonomous Sara send permission or production credential change is added.

## Verified documentation

- [Broadcast lifecycle and variable mapping](https://docs.zernio.com/platforms/whatsapp/broadcasts)
- [Bulk contacts, tag merge and subscription state](https://docs.zernio.com/platforms/whatsapp/contacts)
- [Approved template states](https://docs.zernio.com/platforms/whatsapp/templates)
- [Individual broadcast delivery status](https://docs.zernio.com/broadcasts/list-broadcast-recipients)

Documentation checked 2026-11-16. Context7 quota was unavailable; official Zernio
references were used directly. Actual live-template compatibility and subscriber
exclusion require an authorized controlled recipient test after deployment.

## Native Zernio broadcasts and lead cohorts

Migration `033_template_lead_cohorts.sql` adds an independent attribution ledger.
The GET-only repair pass in the lead-capture worker recognizes the owner's native
**Jardines · Base 1 · Feria 22 nov 2026** broadcast on the existing Jardines WhatsApp
account. It verifies the exact approved `..._v4` template and the
`jardines-base1-20261117` segment tag before reading recipient delivery receipts.
It does not create a CRM broadcast or fabricate an import/send result.

A recipient is counted under **Templates · WhatsApp** only when a CRM lead already
exists and a verified incoming message in its account/conversation/participant
namespace is later than that recipient's successful `sentAt`. Failed sends,
outgoing messages, old conversations and CSV membership alone are not conversions.
The persistent badge is **Templates · Base 1**. Names, original source, pipeline
stage, subscription and consent remain unchanged; contact uniqueness still uses
the existing normalized-phone constraint. Edited phone identities do not inherit
the previous number's cohort.

Dashboard campaign and template counts are disjoint: template provenance takes
precedence over the social-campaign counter, without rewriting the original
contact source. The cold CSV-import counter remains separate and is not a count
of replies. The total-contact counter continues to include all unique leads.
The existing authenticated, CSRF-protected `POST /crm/broadcasts/filter` accepts
an optional `cohort` (`campaign`, `template`, `imported` or `other`), alongside its existing
`campaign_id` and `cold_only` filters. Contact and pipeline filtering runs in SQL,
not just on the first 500 client-side rows.

### Complete dashboard distribution

`GET /crm/workspace` and the filter response include an additive `lead_origins`
summary and each returned contact's computed `lead_origin`. Classification is
read-only and exhaustive, with precedence: verified template reply, imported
contact, recorded `social_campaign` source, then other sources. The four counts
sum to the global contact total, even when the current list is filtered or capped
at 500 records. `other_sources` breaks down the last group by the stored source.

The UI calls the social bucket **Campañas y redes**, not paid-ad attribution:
the stored source alone does not prove a click on an ad. **Respuestas a templates**
counts only verified replies, never the audience or all delivered messages.
An imported contact with such a reply appears only under templates. Legacy
`cold_only` and `counts.cold_leads` retain raw import membership for existing
consumers; `cohort=imported` is the disjoint dashboard group. No original sources,
identities, stages, opt-outs or receipts are rewritten. No provider call or send
is made by opening or filtering this distribution.

Each dashboard card opens its exact SQL-filtered contact list. The original
source and dashboard group remain separate in the contact detail. Missing or
inconsistent distribution data is shown as unavailable, not as zero.

Each minute, the independent repair pass reads at most two recipient pages and
checks at most ten linked conversations. A 913-recipient snapshot needs at least
five passes; unanswered/failed reads are retried as **reads** after five minutes.
It reads the latest 100 messages per conversation and never infers a reply from
an incomplete history. An older response absent from that window remains
unattributed. No message, template, import, opt-in, retry-send or resend is executed.
Webhook lead capture stays network-free. Attribution failures do not roll back
lead creation or replay welcome messages. Applying the migration and deploying
this code are required before production counts change.

Provider contract references: [broadcast detail](https://docs.zernio.com/broadcasts/get-broadcast),
[recipient receipts](https://docs.zernio.com/broadcasts/list-broadcast-recipients),
[conversation messages](https://docs.zernio.com/messages/get-inbox-conversation-messages).
