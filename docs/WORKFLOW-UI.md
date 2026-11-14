# Sequence workspace UI

`Secuencias` follows `Voz` in the existing CRM sidebar. It is a local administrative
workspace; no credential, provider, deployment or remote activation is implied.
The shared API and execution authority contract is in `WORKFLOWS.md`.

## Interaction

- **Constructor**: choose an existing versioned draft or create a new definition.
  Add only catalog-enabled node kinds, select a card, edit typed fields and choose
  labeled destinations in the inspector. The SVG is decorative; actual cards are
  buttons and an equivalent expandable ordered list exposes all connections.
  The editor prevents cyclic target choices and reports unreachable nodes before save.
  Adding inserts a step before the final node; a condition initially routes both
  branches there until explicitly reconnected. Order cards with `Ordenar pasos`.
- **Programación**: ISO days 1–7 (Monday–Sunday), Colombia timezone, start/end
  interval without overnight windows, daily action limit 1–100 and verified-reply
  stop policy. These settings remain part of the draft until saved.
- **Clientes e historial**: select at most 50 existing workspace contacts; no new
  customer fields or sample customers are inserted. Social conversations are
  explicit run metadata, never inferred from a phone. One binding per recipient
  requires all social-message nodes in that run to use the same account/platform.
  Preparation is additionally limited to 10 external actions: audience size times
  the number of WhatsApp/social-message/call nodes. This is separate from daily limits.

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
