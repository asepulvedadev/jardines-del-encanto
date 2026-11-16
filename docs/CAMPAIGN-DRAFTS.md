# Internal WhatsApp campaign drafts

The private CRM sidebar contains **Plantillas**, an editable library independent
of live contacts and workflow execution. Saving never submits anything. A separate,
explicitly confirmed action can submit one saved version for Meta review through
Zernio. There are no message-send, schedule or activation routes in this module.

## Initial collection

- Four invitation and four information drafts.
- Seven registered-lead drafts with suggested dates November 16–22, 2026.
- Fifteen private portrait images, using the owner's logo as a composition input.
- Editable records remain `local_draft`; a separate versioned review summary reports
  the last observed provider status without approving later local edits.
- Suggested dates are editorial metadata, not scheduled jobs or event promises.
- Contact permission must be established before any eventual marketing use.

The collection lives in `apps/api/app/campaigns/seeds.json`. GET merges these
source-controlled defaults with database overrides. First save creates version 1;
later saves compare and increment the version atomically. Stale edits return 409
without overwriting existing work. New drafts receive a server-generated identifier.

Migration `013_campaign_drafts.sql` is additive. Existing records and formats are
unchanged. Runtime grants are SELECT/INSERT/UPDATE only. Normal admin authentication,
Origin checks and CSRF protection apply to mutations. Images require authentication
and come from a fixed allowlist, never a user-provided filesystem path or fetch URL.

## Editing and preview

Edit the name, audience, suggested date, image selection, body, variables and up to
three buttons. The editor validates unresolved placeholders, duplicate variables,
invalid links and button limits before saving. Navigation, reload and logout warn
about unsaved changes. Failed saves preserve the editor; export is available even
for conflicted drafts so the user can recover their text before reloading.

Named variables use `{{nombre}}` syntax. Values are examples, not contact bindings.
Links can be variables such as `{{enlace_proyecto}}`; a URL button accepts a complete
link variable or literal public HTTPS URL. The draft editor never fetches these user-provided links. Values
are substituted once, never evaluated or recursively expanded. Text is rendered
through React, not HTML injection. A future sender must bind and validate actual
recipient values; example values must not be sent as live personalizations.

Reply buttons carry editable response keys. Preview clicks simulate a choice only;
they do not send a reply or connect a branch. Link previews open the displayed URL
on explicit click. The actual WhatsApp layout and final content approval remain subject to Meta.
Review preparation checks contiguous button-type groups and a maximum of two URL
buttons without silently reordering the preview. These drafts are not wired
to the existing simple-text approved-template workflow adapter.

JSON export is `jardines-internal-draft-v1`, not a Meta or Zernio submission payload.
Copy text uses example values and does not copy executable WhatsApp controls.
Image text is baked into the PNG: changing message copy does not edit those pixels.

## Explicit review workflow

1. Save the draft, including an unchanged seed, to create a persisted version.
2. Choose **Enviar a revisión**. The dialog loads active WhatsApp accounts from
   the configured Zernio profile only; the user must select one.
3. Choose **Revisar contenido** to validate that exact saved version. No external
   template is created at this step. The dialog shows its generated provider name,
   account, image, example text, buttons, Marketing category and `es_CO` language.
4. Check the explicit consent box, then **Confirmar envío a revisión**. This shares
   that version and its examples with Zernio/Meta, not with contacts.
5. Open **Historial de revisiones** and **Actualizar estado** to read Meta's latest
   verdict through Zernio. Updates are read-only at the provider. No automatic
   polling, resubmission, remote edits or background delivery is installed.

Migration `014_campaign_reviews.sql` adds immutable document snapshots, actor,
account/profile, timestamps, version, provider identity and separate review status.
A unique `(slug, version, profile_id, account_id)` reservation commits **before** the
single external create. Concurrent clicks cannot duplicate the request. An ambiguous
network or provider result stays `UNKNOWN` (or `SUBMITTING` after an interrupted
process); the same version/account cannot be retried. Read back its generated name
and exact language rather than guessing success or failure. Provider names incorporate
32 hex characters of a deterministic identity hash and the local version number.

Refresh checks profile, active account, exact name/language and any known provider
ID. A compare-and-swap on `checked_at` prevents a slower refresh from overwriting a
newer observation. Submission completion cannot overwrite an intervening refresh.
Unrecognized or ambiguous replies preserve the prior state. Editing creates a new
local version; it never changes an already-submitted snapshot or implies that the
new version was approved. After rejection, inspect Meta's reason in WhatsApp Manager,
correct the draft and save a new version before requesting another review.

The review adapter only calls the fixed Zernio template collection route using the
existing pinned-host TLS transport. It does not widen the social provider allowlist
or the simple-text approved-template workflow sender. Credentials, raw provider
errors and image capabilities are not returned in history or preview responses.
Authenticated mutations retain existing Origin, CSRF and 16 KiB body limits.

### Images and link variables

Zernio's [official header component schema](https://github.com/zernio-dev/zernio-node/blob/main/src/generated/types.gen.ts)
accepts a public URL in `header_handle` and performs the upload to Meta. The module
creates a random 256-bit, single-image capability only after confirmation. Its hash,
15-minute expiry and selected asset SHA-256 are stored privately. No session is
required for this exact capability URL, but private original images still require
admin authentication. Wrong, expired or mismatched capabilities return 404. Responses
are bounded PNGs with `no-store`, `nosniff` and `no-referrer`; no asset directory is
made public and no user-controlled filesystem path or server fetch is introduced.

Set `CAMPAIGN_MEDIA_ORIGIN` to the public HTTPS origin serving the Next gateway;
otherwise the configured `CRM_ORIGIN` is used. Local HTTP, IP origins and origins
with credentials, paths, query strings or fragments are rejected. Keep the public
`/api/crm/campaigns/review-media/{id}/{token}` route reachable from Zernio. Do not log
or redistribute capability paths. The 15-minute window is for the create-time
sample upload, not a permanent link for later message delivery. Live reachability
and provider acceptance must be verified separately after authorized deployment.

Named body variables and their examples are preserved. A full-link variable on a
URL button becomes a fixed `https://host/` prefix plus positional `{{1}}` suffix;
its example preserves the path, query and fragment (a root URL uses the equivalent
`?` suffix). Later sending must bind only the suffix and cannot change that button's
domain without another review. Literal links stay static. Quick-reply labels go to
Meta; local response keys stay in the snapshot and do not create workflow branches.
These rich reviewed templates are still not wired to the existing workflow sender.

[Zernio's template guide](https://docs.zernio.com/platforms/whatsapp/templates)
documents custom creation and review statuses. Provider approval is never guaranteed.

## Brand and image provenance

Exact original logo SVG copies: `assets/campaign-drafts/brand/`. The reference PNGs
are rasterizations of those unchanged SVGs. The preview conversation header uses
the exact original SVG at `apps/web/public/brand/jardines-del-encanto-refinado.svg`.
No global logo replacement is included.

Private final campaign images: `apps/api/app/campaigns/assets/campaign-01.png`
through `campaign-15.png`. Images are AI reference-guided compositions, not
pixel-identical vector compositing. They were visually checked against the supplied
brand references. The supplied SVGs remain the authoritative brand assets.

The built-in `image_gen` tool was used, not the CLI or Magnific. Prompt set:
1. Existing pieces 01–12: replace the provisional top branding with the complete
   supplied official lockup, green on light or white on dark, preserve the copy,
   photo, visible construction state and commercial qualifications, remove generic
   substitute leaf marks, do not restore the removed illustration caption.
2. Piece 13: real aerial photo and supplied green logo; ivory/forest portrait layout;
   “Recorre antes de decidir.” / “Descubre el proyecto y prepara tus preguntas.”
3. Piece 14: real entrance photo and supplied green logo; same layout family;
   “Conversemos sobre tu visita.” / “Coordina los detalles con un asesor.”
4. Piece 15: real aerial photo and supplied green logo; same layout family;
   “Sigamos a tu ritmo.” / “Tus preguntas merecen respuestas claras.”

All new pieces include Acacías, Meta. No invented dates, offers, completed amenities,
QR codes, testimonials, sales deadlines or illustration captions were requested.
Earlier local visual revisions remain separate, with source locators in
`assets/campaign-drafts/2026-11/official-logo-manifest.json`.

### Owner photo refresh — November 16, 2026

The owner requested the same fifteen pieces with only their property photographs
replaced by two newly supplied site photographs. The original source copies are
`assets/campaign-drafts/2026-11/source-photos/owner-lots-roads.png` and
`assets/campaign-drafts/2026-11/source-photos/owner-entrance-court.png`.
Pieces 03, 07, 10 and 14 use the entrance/court photograph; the remaining pieces
use the lots/roads photograph. All fifteen existing private PNG paths and dimensions
are retained, so the existing image selections continue to resolve.

Each built-in `image_gen` edit received the original poster as its edit target and
one owner photograph as its replacement input. The prompt requested replacement
of the photograph rectangle only, preserving the logo, layout, colors, typography,
Spanish copy and commercial qualifications, without inventing property features.
The full outputs were visually checked. This remains reference-guided image editing,
not a guarantee of pixel-identical preservation outside the photograph.

The manifest records updated hashes, prior hashes and the source photograph for
each piece. Message documents, variables, dates, button definitions and review
snapshots are unchanged. This local refresh does not submit to Meta, change an
existing provider template or send messages. Production publication remains a
separate authorized release. Previously issued image capabilities remain bound to
their original hashes; changed image bytes do not inherit previous review approval.

## Verification

- API tests: strict models, 15 valid seeds, seven dates, authenticated private media,
  persistence, reload, optimistic conflicts, creation, CSRF, body limits and no-send
  route boundary, using the isolated `jardines_crm_test` database.
- Node tests: gateway allowlist, authenticated forwarding, Origin/body limits, PNG
  validation/bounds, variable rendering and unsafe/unresolved links.
- `npm run typecheck`, `npm run build`, `npm run test:crm:gateway`.
- Synthetic loopback browser fixture: `tests/fixtures/campaign-preview.mjs`. It uses
  the real Workspace/CampaignPanel components and synthetic in-memory records;
  it never connects to production, a CRM database or a messaging provider.

Provider tests use synthetic responses; no real review submission is part of release
verification. Production deployment is authorized separately from sending to Meta
or contacting leads.

### Observed local results — November 15, 2026

- API suite: 418 passed, including 13 campaign tests. The existing Starlette/httpx
  deprecation warning remains; no skipped tests in this run.
- Gateway/UI source suite: 223 passed. Typecheck, production build and Ruff passed.
- Browser fixture: sidebar navigation, 15 drafts, seven registered-lead dates,
  editing and reloading a saved example, resolved name/link variables, URL button
  destination, simulated reply selection and unresolved-variable save blocking
  were observed. Viewports 320, 390 and 1440 pixels were checked. At 320px the
  content width equaled its scroll width (305px); no horizontal overflow occurred.
- Search control: observed 16px input text and 39px left padding after correcting
  a collision with the existing CRM input selector.
- Switching templates remounts the preview scroll container. The newly selected
  image was observed with `scrollTop: 0`, rather than retaining a previous image's
  scrolled position.
- Exit-guard interaction is only partially verified: invoking it blocked the
  in-app browser automation at a native JavaScript confirmation dialog. The
  automation could not dismiss that dialog; the disposable fixture tab was
  closed and reopened. Manual acceptance/cancellation remains unverified.
- Browser evidence is synthetic UI proof, not a claim of production deployment.

### Review extension — observed local results, November 15, 2026

- API suite: 429 passed, including 11 new review tests. One pre-existing
  Starlette/httpx deprecation warning remains; no tests were skipped.
- Gateway/source suite: 224 passed. Production build including TypeScript, separate
  typecheck, Ruff, targeted Prettier checks and `git diff --check` passed.
- Synthetic browser: saving an unchanged seed enables review; account selection,
  unchecked confirmation blocking, simulated submission, PENDING display, history,
  simulated APPROVED refresh, duplicate blocking and dirty-edit blocking were
  observed. Saving version 2 preserved version 1's submitted snapshot and displayed
  “Hay cambios locales posteriores”. The obsolete save-only notice is cleared
  after review operations so it does not contradict the displayed request state.
- Native HTML dialog: initial focus on Close and Escape dismissal were observed.
  At 320px, the page width equaled its scroll width (320px). The populated dialog
  had client/scroll widths of 269px, and vertical content remained scrollable.
  No full accessibility certification is claimed. The older unsaved-navigation
  native JavaScript confirmation still needs the manual check described above.
- All review requests used test doubles. No live account lookup, review submission,
  public image fetch by Zernio, remote migration or production deployment was run.
  The next authorized deployment must apply migration 014, verify the public media
  origin and separately validate a deliberately chosen real template.


## Production release preparation — November 15, 2026

The owner authorized deployment of Plantillas and all pending project changes.
The release includes migrations 013/014, the final 15 campaign images, original
brand assets, editable previews and explicit review submission controls. It also
records the already-applied canonical-domain policy. Workstation `.atl/` state and
superseded `without-caption/` image revisions remain local and are excluded from
Git. The public asset manifest contains repository-relative paths and content hashes,
not workstation source paths. No lead sends or real Meta submissions are authorized
as part of this deployment.

Before publication, the image-capability route was excluded from Nginx access/error
logging and from Uvicorn HTTP access logging; logging other routes is unchanged.
Install the project-specific Nginx policy before exposing that endpoint. Default
`CRM_ORIGIN=https://jardinesdelencanto.site` supplies the public sample-image origin.
The deployment gate takes a private database backup, applies additive migrations,
checks readiness and retains the previously healthy application images for rollback.

Release-candidate checks: 430 API tests passed, 224 gateway/UI-source tests passed,
and the operations suite ran 159 tests with one existing optional pinned-Hermes
fixture skipped. Typecheck, production build, full API Ruff, targeted Prettier and
whitespace checks passed. No live Meta request was used for those checks.

The project-only Nginx log-protection policy was installed and validated before
publication. Its root-only recovery checkpoint is
`/srv/jardines-del-encanto/templates-policy-qhiprt66`; the canonical login cutover
checkpoint remains separate. Application activation and migrations use the normal
`Verify and deploy` pipeline, not an unverified manual copy of the working tree.
