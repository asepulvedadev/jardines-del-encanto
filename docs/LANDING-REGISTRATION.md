# Landing interest registration

The modal opens when at least 30% of `#amenities-title` enters the visible region
below the sticky header. It opens automatically once per browser session and can be
reopened through any “Quiero mi cupo” button: launch banner, hero, amenities,
final contact section and sticky mobile bar. A single `LeadCaptureProvider` owns
the existing dialog, form, request state and receipt; `LeadCaptureButton` exposes
the same action throughout the landing. These are native buttons, not WhatsApp
links. Other explicitly named contact/WhatsApp links remain unchanged.

Opening or closing the dialog never submits data. Manual opening marks the
session prompt as seen and suppresses subsequent automatic prompting. Escape
returns focus to the clicked trigger; fields survive closing/reopening, and all
buttons share the confirmed receipt state. It remains dismissible;
registration is not required to explore the project. When session storage is
unavailable, automatic prompting is limited to once per mounted page.

The shared-trigger revision passed the optimized build, TypeScript, all25 web
checks and all35 CRM gateway checks locally. Browser checks exercised every
visible trigger at390px and1440px, one dialog instance, preserved fields, Escape
focus restoration, the existing automatic section prompt and a shared saved-code
fixture. No registration POST, production data change or publication was performed.

## Data and semantics

Only full name and phone are business fields. Explicit unchecked contact consent
is required on both client and server. Source is assigned server-side as `web`.
Colombian mobile numbers use the existing CRM normalization; other supported
international numbers require a country code. No tracking/analytics dependency was added.

One transaction creates a contact, its `new` deal and a random `JDE-` registration
code. Normalized-phone retries reuse the contact and code. Existing names, sources,
pipeline stages and administrator activities are never overwritten. New public
registrations have their own consent audit, not an invented administrator actor.
The authorized CRM workspace exposes the optional `registration_code`, shown in
client detail. Anonymous responses expose only the code, never CRM IDs or PII.

The Casanova source was used as a behavioral reference: section-triggered modal,
consent and a persistent contact-associated code. No event discount, expiry,
commercial guarantee, property allocation, public verification or image download
was copied. A Jardines cupo confirms interest, **not a reservation or payment**.

The registration is keyed to canonical contact identity and the current normalized
phone, not a phone snapshot. If an administrator later changes a phone, a submission
of the old phone can legitimately create a different contact and registration.
Browser session storage contains only the prompt-seen flag and returned code, never
name or phone. Losing browser storage does not lose the database record: resubmitting
the same current phone returns its stored code.

## Boundaries and failure handling

- Public POST only: `/api/landing/registrations` -> `/public/registrations`.
- Exact configured origin, JSON, streamed 2 KiB limit, strict fields, explicit boolean
  consent and honeypot validation on the API. Private CRM session/CSRF rules are unchanged.
- The gateway forwards no credentials, cookies, CSRF tokens or forwarded-IP headers.
  It follows no redirects and returns only an allowlisted code or opaque error.
- PostgreSQL-backed fixed-window budgets: 100 valid attempts globally and five per
  normalized phone per ten minutes. Counter changes commit before returning 429.
  This protects baseline write capacity, not identity verification or comprehensive
  bot prevention. A global budget can be exhausted; production traffic may require
  separately approved edge rate limits/CAPTCHA. Origin checks alone do not stop bots.
- No public lookup/list endpoint. Codes are receipts, not authentication credentials.
- No success until the API confirms its committed transaction. Network failures keep
  the form editable; repeated submission does not duplicate a lead. Code collisions
  retry within savepoints; exhaustion rolls back the whole capture transaction.

## Migration and local verification

Migration `003_landing_registrations.sql` is additive and checksum-tracked. Run the
existing privileged migration command **before** starting this API revision:
`python -m app.crm.manage migrate` with the project's configured migration DSN.
Never apply test truncation to a real project database. API tests refuse any database
whose name is not `jardines_crm_test`.

```sh
npm run test:crm
node --test tests/landing-registration-gateway.test.mjs
npm run test:crm:gateway
npm run typecheck
LANDING_BASE_URL=http://127.0.0.1:4321 npm run test:web
```

The owner authorized production publication on 2026-11-11 through the existing
project deployment gate. A production release must include database backup, explicit
migration and normal rollback planning;
a web-only release is not sufficient for this feature. The privacy text is a concise
capture disclosure, not a certification of legal-policy completeness.

## Observed local results — 2026-11-11

- API suite: 68 passed; gateway suites: 12 passed, including three new public-route
  tests; landing/clock/masterplan suites: 15 passed. TypeScript and focused Ruff pass.
- The initial API/gateway tests failed before the new endpoint existed, then passed
  with the implementation. Duplicate/concurrent creation, strict rejection, persistent
  throttling and collision rollback are covered against the isolated test database.
- A real browser -> Next gateway -> API -> PostgreSQL submission created exactly one
  web/new lead and consent record. A second normalized-phone submission returned the
  same code without changing the name. The owned synthetic fixture was removed after
  verification, restoring the original contact/deal/registration counts.
- Browser checks verified section activation, once-per-session prompting, Escape and
  returned focus, required consent, preserved fields after simulated service failure,
  confirmed receipt/reload, mobile reflow and no page errors. Reviewed screenshots
  cover the phone form and success card. No WCAG certification was performed.
- Independent boundary verification reran API/public-gateway tests with no blockers.
  It did not independently exercise the browser. Existing Starlette/httpx deprecation
  and Node module-type warnings remain unrelated to this change.
- Local API/web images were rebuilt and healthy at `http://127.0.0.1:4321/`.
  No production database, remote server, Git commit or publication was performed.
