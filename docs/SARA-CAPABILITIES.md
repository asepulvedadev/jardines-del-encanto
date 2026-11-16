# Sara capability expansion

## Requested outcome

> quiero que al agente sara tanto el web como eld e whatsaap tenga permiso de crearse skills tools de editar sus configuraciones de crear imagenes con la api key de openia tenga acceso a los logos e imagenes que estamos usando para tener las bases del diseño que se pueda entrenar desde el whatsaap simule conversaciones con el cliente que sea muy estable, dejala funcional completamente te autorizo

The full outcome includes the web assistant, the specialized WhatsApp agent,
trusted developer training, brand-aware OpenAI image creation, editable agent
configuration, skills/tools, customer conversation simulation, and verified stable
production operation. Local tests or a visible configuration form alone do not
establish completion.

## Authority and behavior

- Web administrators and the owner's verified developer numbers can build and
  install Sara-owned skills/tools and change the agent's published configuration.
  These capabilities must be available through actual conversational tool dispatch,
  not only settings forms or explanatory messages.
- Customer messages do not inherit developer authority. Recognition is based on
  authenticated channel identity and a revocable server-side developer grant,
  never a display name, prompt, customer-provided number, or fabricated web session.
- Configuration editing covers instructions, knowledge and response preferences;
  provider credentials, authentication, immutable runtime policy, network endpoints
  and source code are not model-editable configuration.
- Brand references use the actual supplied logo variants and current approved site
  photographs. Generated creative is labeled as a concept, not construction proof.
- Image work uses the project's existing isolated OpenAI credential boundary.
  Durable jobs reserve before paid I/O and never replay an uncertain generation.
- Training changes are versioned and attributable. Customer transcripts do not
  silently become global knowledge. Developers can teach from WhatsApp; web users
  can review published versions and test customer conversations.
- Simulations use isolated synthetic customer turns and a configuration snapshot.
  They must not send real messages, create real leads, publish, or train themselves.

## Delivery evidence checklist

- [ ] Web Sara creates, edits, tests and installs owned skills/tools through Hermes.
- [ ] Trusted WhatsApp developer can use the same authorized capabilities.
- [ ] Public WhatsApp customer stays isolated from developer configuration/tools.
- [ ] Shared versioned agent configuration changes affect both web and WhatsApp.
- [ ] Brand asset catalog contains original approved logos and current photographs.
- [ ] OpenAI image generation uses selected reference pixels and returns real artifacts.
- [ ] Generated artifacts are inspectable in the web assistant and usable from developer WhatsApp.
- [ ] WhatsApp training persists and is reflected in later agent responses.
- [ ] Customer simulations return an inspectable transcript without business side effects.
- [ ] Failure, concurrent update, ownership, revocation, quota and no-replay tests pass.
- [ ] Production credentials, webhook signature and exact channel delivery are verified.
- [ ] Authenticated production web and developer WhatsApp paths are exercised.

## Current implementation evidence

At the start of this expansion, web Sara already had an owned declarative extension
lifecycle. Pending local WhatsApp code recognized two explicit developer commands
but used a tool-free public agent for all other conversation; it did not satisfy
conversational developer capabilities. No image API or customer simulator existed.
The last production inspection found account-read MCP authorization without a REST
messaging credential. A webhook and scoped-key form were prepared but not submitted.
Those external prerequisites remain unverified; they do not prevent local progress.

## Local integration and verification (2026-11-15)

- Shared versioned profile API: `GET/PATCH /crm/sara/config`, version history and
  explicit typed Hermes `sara.config.get/update`, `sara.learn` actions. No runtime,
  permission, provider URL or credential field is editable. Concurrent stale writes
  are rejected. Published updates invalidate other queued WhatsApp responses.
- Isolated simulations: `POST/GET /crm/sara/simulations` and per-ID status. The
  worker commits its once-only claim before model I/O, uses the frozen published
  profile and synthetic turns only, and leaves interrupted/uncertain work terminal.
  Each administrator has a three-run rolling daily cap; up to four customer turns.
- Brand image queue and private previews are connected through `images.*` actions,
  exact web gateway routes and private bridge/provider handlers. The provider alone
  reads the existing OpenAI secret. Original asset hash checks apply at both ends.
- Settings includes a **Sara IA** tab for profile publication/history and synthetic
  tests. Image receipts render directly in the chat, outside collapsed diagnostics.

### Runtime activation prerequisites

These are manual project deployment prerequisites, not evidence of deployment:

1. Apply the additive migrations with the existing project migrator; never edit an
   applied migration. Preserve current customer data and take the normal backup.
2. Install `image_server.py` and mount `operator_images.py` only in the dedicated
   image provider. Activate `image-provider:8083` and `image-bridge:8082`; the API uses
   `HERMES_IMAGE_BRIDGE_URL=http://image-bridge:8082` without a text-service fallback. Copy `apps/api/app/images/brand` unchanged to the dedicated
   root-owned brand directory, or set `HERMES_BRAND_ASSETS_DIR` to that exact directory.
   The read-only bind uses `create_host_path:false`; a missing directory fails closed.
3. Set `CRM_IMAGES_WORKER_ENABLED=1` and `CRM_SIMULATIONS_WORKER_ENABLED=1` in the
   project's API runtime environment. These workers are opt-in to prevent accidental
   paid work in unrelated environments. Enable WhatsApp only after exact provider,
   business account, signed webhook, owner and developer grants are verified.
4. Recreate only this project's affected services; test actual model access and
   generated PNG retrieval with an authenticated owner before claiming readiness.

The locally passing mocked/isolated tests do not prove actual account model access,
OpenAI charges, production deployment or external WhatsApp delivery.

## Verified corrections and remaining work

Independent review found and reproduced two integration defects, both corrected:

- The actual public bridge returns a `model` field; synthetic runs now validate that
  real envelope and a regression exercises the actual producer rather than inventing
  a mock response shape.
- Developer-origin paid queues now retain immutable channel provenance (migration
  018) and revalidate the current grant before claiming work. Removing a developer
  blocks both queued image and simulation calls with zero provider I/O. Finishing
  an otherwise authorized developer chat does not invalidate its queued work.

Still incomplete, not substituted by local checks:

- Deploy the locally verified dedicated image bridge/provider. A separate-process
  loopback regression proves text health/replies remain responsive during blocked
  image generation; real production/model concurrency is still unproven.
- Deploy and exercise direct generated PNG delivery in developer WhatsApp. Local
  migration019/outbox/private multipart transport now exists; real accepted output
  and the intended developer receiving it still need production proof.
- Exercise the production UI and real-provider replies. Local parent browser verification
  covered login, profile publication/history and synthetic simulation on desktop/mobile;
  it used a fixed loopback response, not actual model output.
- Real provider/model access, signed production webhook, REST credentials, runtime
  activation, deployment and exact web/developer/customer channel smoke tests.

## Signed production webhook evidence (2026-11-15)

Owner-authorized direct inspection found the current production origin is
`https://jardinesdelencanto.site`, on release
`95864e0b4e56a392794a6c2c4cc5be1106026615`. A scoped REST credential already exists;
account metadata reads succeed, while webhook-management calls are explicitly
forbidden by that key. Its permissions were not expanded.

The authorized browser session created subscription `6afa4a151c45bcc86583d71b`
for `message.received`, scoped only to the Jardines WhatsApp account, using the
existing backend HMAC. The actual vendor test returned HTTP200 in one attempt and
was persisted by the backend under the same event ID. Only then was the private
registration metadata marked configured. No API/HMAC credential value changed,
no customer message was sent, and none of this pending feature code was deployed.

Evidence remains in `.local/verification/zernio-webhook/RESULT.md` and
`verified.json`; screenshot `created-success.png` shows the vendor result.
Messaging capability and specialized Sara activation still need separate proof.

## Private developer image outbox (local, not deployed)

Migration019 atomically associates completed developer-origin PNGs with the exact
verified source grant. A dedicated opt-in worker revalidates current ownership,
developer membership, channel, credential revision, image hash, conversation control
and WhatsApp window. A committed reservation precedes one fixed-host multipart POST;
unknown reservations are never replayed. Web-origin jobs never acquire a recipient.

Independent verification reproduced a DNS deadline escape before socket assignment.
The correction isolates read-only preparation and final submission in fixed trusted
subprocesses, then kills and waits on timeout before releasing authorization guards.
The process receives credentials through stdin, not argv, and no OpenAI credential.
Regression probes exercise actual blocked loopback-only DNS and a stalled response
body, asserting process termination rather than assuming socket close interrupted DNS.
The additive migration was applied only to disposable `jardines_crm_test`.

Enable `CRM_WHATSAPP_IMAGES_WORKER_ENABLED=1` only with the matching migrations,
provider/image services and verified intended developer channel. No production upload
or model generation has been performed for this unit.

## Local rendered UI proof

The parent Cua runtime exercised actual login, Sara IA settings, synthetic publication
fromv1tov2, both history entries, simulation creation and auto-refreshed completed
transcript with frozen profilev2. Desktop and390x844 screenshots are preserved in
`.local/verification/sara-ui/`; mobile DOM width equals scrollWidth390. Tab navigation
remained in the modal and Escape closed it. This is not a full accessibility audit.
The fixed loopback model fixture proves UI/API orchestration, not real model behavior.
Owned servers/tab were stopped/closed and the viewport reset after verification.

Current local suite:483APItests passed;26focused media tests passed. Related runtime
checks:65passed,107subtests,one opt-in fixture skipped. Independent DNS timeout
regression rechecked closed and parent repeated its actual-process probe.

## Authorized release attempt and concurrent replacement (2026-11-16 UTC)

The owner explicitly authorized root SSH deployment to the project VPS with the
workstation Ed25519 key, preserving existing production changes and configured
credentials, followed by one real OpenAI image and a Johan-only WhatsApp test.
No GitHub publication or commit authorization was inferred.

The first reconciled source snapshot, `6fc22adbd53c7d6c488be4f5d123bca3af1a924d`,
was a content digest, not a Git commit. It included public main `95864e0` plus Sara,
retaining campaigns, Inbox, the branded origin and newer workflow UI. The normal
root deployment gate was not changed. Before activation, the root-only checkpoint
`/srv/jardines-del-encanto/sara-capabilities-gwco80mu` retained policies, logical
backups, business counts, container identities and vhost hashes.

Production Docker web/API builds, isolated imports and activation succeeded.
All 16 prior migration checksums remained unchanged; seven additive Sara migrations
brought the total to 23. Existing business counts, 21 protected container identities
and all 12 enabled vhost hashes were preserved. Image bridge/provider and text
operator boundaries were healthy. The existing credential retrieved metadata for
`gpt-image-2.5-flare` with HTTP200; this is not proof of actual generation or quota.

A real authenticated web conversation created, validated and installed the owned
skill `Guía visual Jardines` (version2, effective=true). Before the next capability
test completed, another deployment replaced the API/web with public commit
`eabffc84a5f31768f42bf82eac662eb05962f54e` at 01:07UTC. That newer application lacks
`app.social.whatsapp_agent` and the image catalog actions. Its guarded broker
correctly rejected two attempts to create the image-catalog tool. No such tool,
image generation or WhatsApp send is claimed successful.

The SDK also exhausted its original four-completion budget. A deterministic
loopback regression reproduced rejection of the fifth completion. The local fix
uses eight shared model completions, retaining the existing twelve-tool-call,
time, token and global request ceilings. Public customer runs remain tool-free
with one iteration. Focused protocol/operator/public tests passed (30passed,
one opt-in skip,56subtests), and independent review found no blocker. This budget
fix is local only; it has not been installed into the root-owned operator policy.

The latest local candidate now reconciles Sara with public/live `eabffc84`, not
with the superseded release. Evidence is in `.local/verification/release-latest/`.
A shared-source publication decision is required before claiming durable delivery;
repeated direct snapshots alone can be replaced by the next normal deployment.
Full-goal completion remains unproven: real image creation, exact developer channel,
WhatsApp training/media, shared configuration effects and production simulations
still need their actual runtime evidence.

### Operator-only budget correction installed

After the scoped tests and independent verification, the separately managed
root-owned operator protocol was updated to eight completions. Only the existing
text provider and bridge were recreated; both became healthy. The application
release stayed `eabffc84`. The protocol SHA256 is
`3831de9e25c970f48c0c8bce90c5443c799b8a02e42f938900247879efe8adfa`.
Original policy bytes and the correction receipt remain in the root checkpoint.
The latest reconciled candidate passes585APItests and252gateway/UIchecks, with
all12 nonoverlapping newer files byte-identical and the workflow overlap additive
only. Its final production build and real image/WhatsApp proofs remain pending.
One opt-in pinned-Hermes fixture remains skipped; no full readiness claim is made.
