# Sequence workspace UI

`Secuencias` follows `Voz` in the existing CRM sidebar. It is a local administrative
workspace; no credential, provider, deployment or remote activation is implied.
The shared API and execution authority contract is in `WORKFLOWS.md`.

## Interaction

- **Constructor**: choose an existing versioned draft or create a new definition.
  The canvas takes the full editor width until a panel is requested. `Agregar paso`
  opens a searchable catalog; selecting a card opens its inspector and closes the
  catalog. The name/objective, worker explanation and advanced connections are
  expandable rather than repeated instructions. Unavailable actions remain disabled
  and keep their provider reason in the button's accessible description/tooltip.
  Add only catalog-enabled node kinds, edit typed fields and choose labeled
  destinations under `Conexiones avanzadas`. The SVG is decorative; actual cards are
  buttons and an equivalent expandable ordered list exposes all connections.
  The editor prevents cyclic target choices and reports unreachable nodes before save.
  Adding inserts a step before the final node; a condition initially routes both
  branches there until explicitly reconnected. Order cards with `Ordenar`.
- **Programación**: ISO days 1–7 (Monday–Sunday), Colombia timezone, start/end
  interval without overnight windows, daily action limit 1–100 and verified-reply
  stop policy. These settings remain part of the draft until saved.
- **Clientes e historial**: select at most 50 existing workspace contacts; no new
  customer fields or sample customers are inserted. Social conversations are
  explicit run metadata, never inferred from a phone. Each recipient's conversation
  is selected separately for each sender account. A single run can contain Facebook,
  Instagram and WhatsApp nodes without sharing their recipient identities.
  Preparation is additionally limited to 10 external actions: audience size times
  the number of WhatsApp/social-message/call nodes. This is separate from daily limits.

### Canvas navigation

- Drag the background, use the wheel, or scroll with two trackpad fingers to pan.
  Ctrl/Cmd + wheel (including trackpad pinch events) zooms around the pointer.
  Buttons offer 10–200% zoom, 100% reset and fit-to-content. `Ampliar lienzo`
  increases the editing height without entering a modal or changing the draft.
- Drag a card to move it with a 10-unit snap. A move is local until pointer release;
  cancellation discards the preview. Positions use the existing document fields
  and are saved only through `Guardar borrador`. Pan/zoom never dirty the draft.
- With the canvas focused: arrows pan, +/− zoom, 0 resets and 1 fits. On a card,
  Alt + arrows moves it; Alt + Shift + arrows uses larger increments. Enter/Space
  opens the inspector. The expandable step list remains an equivalent selection
  and connection-navigation surface.
- At narrow widths, the requested panel overlays the canvas instead of shrinking
  the graph into a tiny column. Both panels have labeled close controls. The catalog
  focuses its search on opening; Escape closes it and restores its trigger.

These controls do not add node kinds, activation authority or provider capability.
They do not change the cycle/reachability, audience, consent or execution checks.

Provider identity selectors use only normalized `/options` records. Existing saved
values not present in the current options remain visibly unverified, not connected.
A `zernio_window_verification_required` conversation can be selected conditionally;
preparation must prove its current inbound window. All other unavailable thread
reasons remain disabled. Provider options and template text are not cached to local
storage. Template body and positional parameters are visible when actually returned;
missing body evidence is disclosed rather than invented.

## Save, review and activate are separate

Saving a draft and preparing a review never send, call or execute a CRM action.
Preparation requires the saved version, explicit audience and outreach consent.
The native review dialog lists server-frozen recipients and action descriptions,
plus the matching saved schedule. A second exact-scope checkbox gates activation.
Activation is also blocked for expired reviews, unsaved drafts and unavailable
workers. Every draft/audience/binding change invalidates the visible review.

Version conflicts preserve the local draft and offer explicit replacement from the
server. Navigation and browser unload warn before discarding unsaved changes.
An ambiguous activation response disables resubmission and asks the operator to
refresh server history instead of repeating an outbound authorization.

Pause/stop prevent new steps, not already-dispatched external work. Stop requires a
terminal-scope confirmation and cannot undo prior results. History displays only
server events, recipient status and counts; submission is not delivery, an answered
call or a sale. Unknown results are held, never offered as replayable actions.
History refresh is explicit and does not overwrite the open draft.

## Verification

`node --test tests/workflow-ui.test.mjs` exercises pure immutable editing,
cycle/reachability checks, exact audience/bindings, fail-closed activation and the
separate user-facing stages. `npm run typecheck` checks integration with the shell.
Browser checks must use the parent's synthetic local API fixture only, never
production contacts or paid messaging providers. The intended viewport coverage is
320/390/768/1440 px plus keyboard and modal focus checks. Automated source/unit checks
alone do not certify visual or WCAG conformance.

`node tests/fixtures/workflow-preview.mjs` opens a loopback-only synthetic preview
on port 4336 (override with `PORT`). It bundles the actual editor using the installed
Next.js webpack and TypeScript, has no real contacts or provider credentials, and
rejects every attempted write. Stop it with SIGINT/SIGTERM to remove its temporary
bundle. It is a manual browser fixture, not a production route or an automated E2E
test. Unit tests additionally exercise anchored zoom, negative-position framing,
bounded movement, pointer panning/dragging and progressive panel visibility.

## Reviewed multichannel replies

Facebook and Instagram steps require an unchecked-by-default ownership consent.
Changing their sender account or platform clears it. Preparation repeats the vendor's
automatic ownership recovery/resend consequence alongside the exact message and
recipient. This permits replies in a verified 24-hour inbound window, not cold DMs.
WhatsApp free text still requires that window; initiating outreach requires a supported
approved Meta template, not an unapproved local campaign draft.

`Clientes e historial` offers a separate selector and options refresh per sender
account. Only selected contacts and accounts used by the current document enter
`channel_bindings`; legacy preparation clients remain supported.

Retell remains an actual call step, but the integration still has no verified +57
route. Its inspector and review preflight say so and block a mixed run containing
a +57 recipient and call step. Remove the call to review messages alone, or separately
provision and verify a supported telephony route. No local test proves live carrier
coverage or authorizes paid calls.

For an isolated multichannel UI preview, run
`MULTICHANNEL=1 PORT=4341 node tests/fixtures/workflow-preview.mjs`. It uses one
synthetic contact and three fake channels. Only its fixed options POST is read-only;
all save/prepare/activate writes remain rejected. No provider is contacted.
