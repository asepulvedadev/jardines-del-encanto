# Retell-style agent studio and focused editors

## User workflow

In **Voz → Agentes**, both **Editar agente** and **Prompt del agente** open the
wide [agent studio](VOICE-AGENT-STUDIO.md): prompt/model/voice/language on the left,
settings accordions in the middle, and audio/LLM test preparation on the right.
Main tabs expose agent configuration, before/during/after-call workflow and
simulation cases/history operations. Focused field modals remain available within
each accordion. Creation and standalone LLM editing retain their focused forms.

The saved agent and its linked Retell-LLM instructions are read completely and
validated independently, including identity and pinned version. Switching views and
opening inner dialogs preserve local drafts. Complete safe text is directly
editable; unavailable/private/partial roots fail closed. Opening, editing and
applying to a local draft never writes to Retell. Final exact proposals require
approval; agent and instructions remain separate versioned resources, not an atomic
save. Confirmed configuration changes invalidate the studio snapshots until reload.

## Complete values versus partial inventories

Ordinary provider results and inventories remain bounded partial views. They must
never be copied into an editable prompt or complex configuration. The dedicated
`POST /crm/retell/editor` read returns only complete safe roots and explicit
`complete_fields` / `blocked_fields` metadata. The editor enables full-value
hydration only for proven complete fields; blocked/incomplete values cannot become
replacement drafts. Full editor records stay in the modal, not the inventory cache.

Private headers, credentials, unsafe URLs, unsupported shapes and over-limit roots
are blocked as a whole, not stripped or shortened and then labelled complete.
Known absent, null and empty values remain distinct. Editing a complete root still
requires schema validation and sends only changed fields. Destructive empty/null
changes must remain explicit and visible in the exact approval summary.

See [editor snapshots](RETELL-EDITOR-SNAPSHOTS.md) for the fixed read protocol,
privacy rules, limits and administrator deployment requirement, and
[modal editing](VOICE-MODAL-EDITING.md) for component behavior and focused tests.

## Schema coverage

The source of truth is the pinned `ops/retell/schemas.json`, not remembered options
or settings copied from another account:

| Endpoint          | Request-body root properties |
| ----------------- | ---------------------------: |
| `createAgent`     |                           60 |
| `updateAgent`     |                           59 |
| `createRetellLLM` |                           20 |
| `updateRetellLLM` |                           20 |

The combined contract has 80 distinct root names and 203 distinct property names.
Native controls cover objects, arrays, dictionaries, discriminated unions,
nullables, enums, booleans, numbers and text. Unknown/private fields remain rejected.
Core convenience controls and modal controls share the existing payload builder.
Modern `model_config` makes ignored legacy model settings unavailable. Unrelated
edits preserve the response engine; explicit alternate-engine creation remains
separate from prompt editing.

## Reference and boundaries

Retell's real editor sections were observed read-only. The bounded REA investigation
analyzed its public `77c9b39b4244a2fd.js` asset without executing bootstrap code;
analysis was partial and does not establish complete dashboard parity. No vendor
implementation, private account prompt or credential was copied.

This configuration UI does not claim Retell's visual conversation-flow graph
editor, dashboard waveform/audio preview or billing UI. Simulation and publication
use existing reviewed operation forms, not proprietary-dashboard parity.
A flow reference is not a graph editor. No live paid or mutating provider test is
implied by local fixtures and deterministic tests.

## Verification and deployment

Focused tests cover hydration, dirty-only patches, actual schema constraints,
identity/version linkage, private/incomplete-field blocking, local dialog edits,
explicit review and stale-response/duplicate-click handling. Browser fixtures use
synthetic records and no provider credentials.

This feature requires the reviewed project Retell gateway's new fixed editor-read
handler as well as the application release. Normal CI never replaces root-owned
policy files. A future administrator-authorized deployment must install/restart
only that project gateway module through the documented scoped procedure, retaining
its existing isolation and a recoverable copy. Local implementation does not itself
authorize or perform that production update.
