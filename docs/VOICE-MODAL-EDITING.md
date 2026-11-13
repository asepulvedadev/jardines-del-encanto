# Safe direct and modal editing

This change replaces root configure/replace checkboxes with ordinary editing:
large direct prompt/greeting fields and grouped configuration rows opening native
field dialogs. It does not authorize provider writes, credential access or publication.

Existing-agent editing now composes these safe field dialogs inside the wide
[agent studio](VOICE-AGENT-STUDIO.md). Creation and standalone instructions retain
the focused form described below.

## Complete snapshot contract

`VoiceAgentEditor` retains its existing interface and adds optional
`completeFields?: string[]` and `blockedFields?: Record<string, string>`.
The parent obtains these from the editor snapshot response. The full safe record
is separate from the bounded inventory cache and must not be reconstructed from it.

Only roots explicitly marked complete may initialize existing editable values.
Metadata is necessary but insufficient: `voiceHydrateField` validates the entire
original root against the actual pinned schema before producing a native draft.
It handles actual nullable, union, array, object and dictionary values, rejects
unknown fixed properties, preserves every accepted child, and fails closed for
private keys, credential-bearing URLs, prototype keys and mismatched scalar types.
Blocked metadata overrides completeness. A blocked root never falls back to cached
partial content. Known-absent complete roots start blank; untouched blank dialogs
never produce implicit empty writes. New resources may start blank without metadata.

Existing partial snapshots remain read-only, with an explanation that the complete
configuration must be loaded. Clipped prompts and incomplete complex structures
are never editable prefills. Invalid original roots remain unavailable rather than
silently dropping unrecognized children and calling the remainder complete.

## Editing behavior

- Instructions mode has a large **Prompt del agente** textarea and **Saludo inicial**
  textarea. Complete safe strings are directly editable; there is no replacement
  checkbox. Identical restored text is omitted from the final patch.
- Clearing complete text is a deliberate edit, validated by the pinned string
  schema. **Vaciar prompt**, **Dejar sin instrucciones**, **Esperar a la persona** and
  **Generar saludo dinámico** are explicit local actions; null remains available
  only where the pinned schema permits it. Empty strings and null are not omissions.
- Agent name and voice remain simple controls. Voice options display real loaded
  names; exact manual identifiers are in closed disclosures. Technical IDs remain
  exact payload values rather than user-facing labels.
- Other options are grouped rows with a readable current value, **Editar**, modified
  status and **Deshacer cambio** where applicable. There are no duplicate root
  controls for the prompt/greeting or simple core fields.
- **Editar** opens a native child `dialog` containing only that field's native
  controls. Complete current configuration is hydrated, not rewritten from an
  incomplete summary. Branch changes remain explicit actual schema choices.
- The child owns a cloned pending draft. **Cancelar** and Escape discard it and
  restore focus to the row's opener. **Aplicar al borrador** validates and updates
  local parent draft state only. It never calls the provider or creates a proposal.
- Applying an unchanged complete object/array is omitted through deep structural
  comparison, ignoring object-key ordering but preserving meaningful array order.
- The existing review action remains the only proposal callback. Its safety metadata
  is enforced again in `voiceEditorArguments`, so manually forged edits cannot
  bypass missing/blocked completeness. Legacy public helper calls remain compatible
  when the new optional safety argument is omitted.

## Keyboard and pending locks

The child dialog is inside the parent form but contains no nested form. All local
actions explicitly use `type="button"`. Enter in native inputs/selects prevents
implicit parent submission and stops propagation; textarea Enter retains normal
newline editing while stopping parent keyboard shortcuts. Escape stops propagation
and handles native cancellation locally. Parent dialogs remain open and their draft
state is preserved. Disabled/pending state locks modal apply/cancel/open operations.

Native `showModal()` supplies top-layer focus containment. A retained opener ref
restores focus after local close. The parent still runs actual browser verification;
fake-hook tests are not a claim of measured accessibility or browser visual approval.

## Reused interfaces

- `voiceSchemaPatch` remains the single payload builder. Its optional fourth
  `completeFields` argument enables unchanged complete-complex omission.
- New pure `voiceHydrateField` returns `{ editable, draft?, reason?, reasonCode? }`.
- `VoiceSchemaEditor` adds the same optional completeness/blocked props while
  preserving existing draft/callback/catalogue props.
- `voiceEditorArguments` adds optional seventh safety metadata after native drafts.
- Existing URL credential normalization, schema enum/range checks, private-field
  blocking, alternate response-engine creation, modern model configuration and
  version/identity preservation are retained.
- CSS extends the already imported `voice-editor.css`; there is no new dependency.

All four pinned root inventories remain intact (60 create-agent, 59 update-agent,
20 create-LLM, 20 update-LLM; 80 distinct roots and 203 distinct property names).
Fields represented directly are excluded only from duplicate row rendering, not
from the inventory or safe payload contract. The broader API/dashboard differences
remain documented in `VOICE-EDITOR.md` by the parent task.

## Verification and limits

Observed RED: the new complete-hydration test failed before the helper existed.
Legacy checkbox-specific tests were rewritten to assert the replacement modal/direct
editing requirements, while retaining unchanged payload, no-auto-write, credential,
engine, union, array/object and failure recovery coverage. Focused tests also cover
complete prompt edits/clears, blocked/partial fallback, modal open/edit/cancel/apply,
focus restoration, local Escape, Enter submission prevention, known-absent no-op,
required validation, pending locks and prototype-key rejection.

Worker checks: four focused editor/model test files, 36 passing; TypeScript check
passed. The parent owns the full suite/build, real browser nested-dialog proof and
all remote/provider decisions. No production browser, owner draft, provider,
database, microphone or network operation was touched by this worker.
