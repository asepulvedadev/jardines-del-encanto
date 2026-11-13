# Retell-style agent studio

The owner supplied a Retell editor screenshot and requested matching agent-editing
structure, then asked to inspect every tab. This local extension replaces the
existing-agent stacked form with one wide studio. Creation and standalone LLM
resources retain their existing focused editors. No vendor source, private prompt,
customer content, credentials or account-specific integration URL is copied.

## Reference inspection

The owner's already-open Retell editor was inspected read-only through visible UI.
Only navigation, accordion expansion and cancellation were used. No configuration
was changed, published or submitted, and no paid test or microphone was started.

Observed surfaces and their local counterparts:

| Retell surface                  | Local studio                                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Agent                           | Three columns: prompt/model/voice/language, settings accordion, audio/LLM test preparation                                            |
| Functions                       | General tools, legacy states and pre/post-session functions                                                                           |
| Knowledge Base & Memory         | Handbook, knowledge references and retrieval configuration                                                                            |
| Speech settings                 | Background sound, timing/responsiveness, interruptions, expressive voice and pronunciation controls                                   |
| Realtime transcription settings | Denoising, mode/provider configuration, vocabulary and boosted keywords                                                               |
| Call settings                   | Voicemail/IVR/screening, keypad, silence and duration settings                                                                        |
| Security & fallback settings    | Storage/retention, PII, guardrails, DNC, signed URLs, fallback voices and dynamic variables                                           |
| Post call extraction            | Extraction schema and analysis model                                                                                                  |
| Post call memory settings       | Contact memory configuration                                                                                                          |
| Webhook settings                | URL, timeout and event selection                                                                                                      |
| MCPs                            | MCP server configuration, subject to private-field blocking                                                                           |
| Workflow                        | Before/during/after-call configuration, reusing the same local drafts                                                                 |
| Simulation / Test Cases         | Automatic engine-scoped case reads; create/detail/edit/delete and batch preparation through existing operation forms                  |
| Batch Testing History           | Existing batch/run query operations, requiring their exact inputs; not an invented history table                                      |
| Test Audio / Test LLM           | Saved-agent/version context with explicit operation review; existing audio runtime only after approval and explicit microphone action |

The studio groups all 59 update-agent roots and all 20 update-LLM roots exactly once
in the configuration map. Core fields also have convenience controls; all controls
reuse the same snapshot validation and dirty-only payload helpers. The additional
advanced accordion preserves remaining engine/version/legacy-model options.

## Editing and execution boundaries

Opening either **Editar agente** or **Prompt del agente** reads the complete saved
agent, resolves its saved Retell-LLM engine and pinned version, and reads the complete
linked instructions. Snapshots are separate from inventory/cache. Unavailable,
private, partial or unsupported instructions never become editable replacement text;
safe agent settings remain available and non-LLM engines are not converted.

Two independent draft bags represent the two versioned resources. Switching main
tabs, opening field modals, and opening the inner operation/review dialog preserve
those drafts. Cancelling an individual setting discards only its pending edit.

**Revisar cambios** validates both payloads before creating proposals and sends only
changed roots. Agent and LLM updates are not atomic: up to two exact proposals each
require approval and may succeed independently. A preparation failure keeps received
proposals visible and retains the draft, without automatic retries or claims that
anything was saved. Confirmed configuration mutations mark snapshots stale; explicit
reload is required before further editing/testing. Publication is a separate
operation and is unavailable while local drafts exist.

The test panel explicitly uses the saved agent/version, not an unsaved prompt.
Audio and LLM test buttons prepare a friendly exact approval summary without a
JSON argument editor. Audio, playground and batch operations consume credits and retain existing approval
and consent boundaries. Merely opening or switching a tab never starts them. No
second voice SDK/runtime is introduced.

## Deliberate limits

This is not complete proprietary-dashboard parity. No cost/latency/token estimates
are invented. The workflow is a structured before/during/after configuration view,
not Retell's conversation-flow graph editor. The LLM panel prepares the existing
playground operation; it is not an unapproved auto-streaming chat. Importing arbitrary
vendor test-case files, AI-assisted editing and public share/environment management
are not added without corresponding reviewed API support. Private authorization
headers and secrets remain managed directly in Retell.

The complete-editor gateway installation prerequisite in
[RETELL-EDITOR-SNAPSHOTS.md](RETELL-EDITOR-SNAPSHOTS.md) still applies. This unit does
not publish, commit, deploy, change dependencies or modify root-owned gateway policy.
