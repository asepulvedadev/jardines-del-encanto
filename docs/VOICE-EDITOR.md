# Native Retell configuration editor

The Voice workspace exposes the reviewed API configuration contract, not a copy of
Retell's private dashboard implementation. Reference section names were observed
read-only by the parent task in Retell's actual editor. Its REA investigation
analyzed the public `77c9b39b4244a2fd.js` bundle (587,144 bytes) without executing its
bootstrap; the analysis was partial and does not establish complete dashboard parity.
No reference code, private account data or private prompt content was copied.

## Coverage

The source of truth is the pinned `ops/retell/schemas.json`, not remembered provider
options or values extracted from an unrelated account:

| Endpoint          | Editable request-body properties | Native inventory paths |
| ----------------- | -------------------------------: | ---------------------: |
| `createAgent`     |                               60 |                     60 |
| `updateAgent`     |                               59 |                     59 |
| `createRetellLLM` |                               20 |                     20 |
| `updateRetellLLM` |                               20 |                     20 |

There are 80 distinct top-level names across these endpoints and 203 distinct
property names in the combined update schemas, including the envelope. No root
properties are excluded from the complete native inventory. Convenience core fields
remain above it; selecting an explicit complete native replacement hides its
corresponding convenience control. The complete inventory therefore includes the
nullable and union alternatives the simpler convenience controls cannot express.
All pinned property names have Spanish labels. Provider identifiers remain exact
values; schema descriptions are available as quoted source text in closed
“Referencia del proveedor” disclosures. Raw JSON and field keys are not shown by
default.

Sections mirror the verified tasks in the provider editor: agent/model/instructions,
functions, knowledge and memory, speech, realtime transcription, call settings,
security/fallback, post-call extraction, post-call memory, webhooks and MCP servers.
Search matches Spanish labels, technical names, sections and the pinned schema.
Native controls include booleans, actual enum selects, bounded numeric inputs,
text, full multiline text, nullable values, repeated arrays, objects, explicitly
named dictionaries and explicit union branches. Required discriminator constants
are seeded from singleton enums, not invented defaults. Switching union branches
starts a blank replacement draft. Additional fields are permitted only where the
pinned schema explicitly permits a dictionary or a free-form object.

Examples of real supported controls:

- Pause before speaking: `begin_message_delay_ms`.
- Who speaks first: `start_speaker`, with actual provider enum values.
- Dynamic first message: explicitly replace `begin_message` with `null`.
- Empty first message: explicitly replace it with an empty string to wait for the user.
- Agent handbook: `handbook_config`.
- Complete model configuration: `model_config`, including cascading, speech-to-speech
  and duplex branches and their real model enums.
- Alternate agent engine: explicit complete `response_engine` replacement supports
  Retell LLM, conversation-flow references and custom LLM websocket references.

## Partial snapshots and review

All saved provider snapshots are partial. Strings may be clipped at 2,000 characters;
arrays and objects may also be bounded. Existing complex configuration, URLs and
long-text fields are read-only previews. Editing requires an explicit full
replacement and a blank draft. Neither the visible fragment nor hidden cached
children are ever copied into that draft. Null and empty-list replacements are
explicit, potentially destructive values and are not treated as omitted changes.

Primitive scalar changes are compared by parsed value. Unchanged values and disabled
drafts are omitted. Agent/LLM identity and valid known version are retained outside
the request body. Unrelated edits never change a response engine. Complete model
replacement bypasses the simpler model/temperature controls; explicit alternate
engine creation does not require a Retell-LLM identifier. New agents still require
an explicit nonempty name and voice.

Legacy model fields remain editable for legacy configurations. When `model_config`
exists, `model`, `backup_model`, `model_high_priority`, `model_temperature`,
`model_ultrafast` and `s2s_model` are visibly unavailable and rejected by the builder:
Retell ignores those legacy fields in that context. This prevents an apparently
successful but ineffective edit.

The editor only emits a proposal through its existing `onSubmit` callback. It does
not perform network requests, approvals, vendor calls, paid tests, recording or
microphone access. The parent owns hydration and the exact external approval UI.
Drafts survive proposal errors and the handoff is single-flight. The workspace must
continue to key each editor by kind, resource identity and version.

## Intentionally blocked private fields

No root editable property is a credential field. Nine distinct declared nested
paths are blocked rather than collecting or transmitting private header values:

- Agent `pre_session_tools[].headers` and `post_session_tools[].headers`.
- Instructions `general_tools[].headers` and `general_tools[].custom_sip_headers`.
- Instructions `general_tools[].destination.destination.headers`.
- Instructions `mcps[].headers`.
- Instructions `states[].tools[].headers` and
  `states[].tools[].custom_sip_headers`.
- Instructions `states[].tools[].destination.destination.headers`.

These fields remain visible as unavailable notices directing the owner to Retell.
This restriction also applies to sensitive dictionary keys such as authorization,
passwords, secrets, API/access/private keys, tokens and signatures. Unknown root or
fixed-object properties are rejected; dictionary names cannot bypass the policy.
URL userinfo and private query parameters are rejected. Credential-bearing URLs are
not retained in native input drafts and are hidden in partial previews. Preview
rendering recursively hides private-keyed children. Private configuration cannot be
round-tripped through a JSON fallback, because this editor has no JSON fallback.

## Not claimed

The four configuration endpoints do not provide Retell's visual conversation-flow
graph editor, dashboard waveform/audio preview, simulation UI, account billing,
publishing/deployment workflow or private credential authorization UI. A field that
references a conversation flow is not a graph editor. Dedicated operations elsewhere
in the workspace may support related API actions, but this editor does not fabricate
those capabilities or claim every dashboard feature is available locally.

## Verification

Deterministic focused tests use the actual pinned schemas and rendered fake-hook
controls. They verify inventory/rendered root counts, primitive/complex/array/object/
union payloads, nullable values, required fields/enums/ranges, omitted unchanged
values, complete replacements, preserved engines, alternate engine creation,
credential blocking, private URL rejection, searching, review failures and
single-flight handoff. Missing-module RED was observed before implementing both new
modules. No provider or database calls are part of these checks.

The parent imports `apps/web/app/crm/voice-editor.css`, runs the full integration
suite/build and verifies real browser layout with synthetic fixtures. Worker checks
do not by themselves establish visual approval, measured accessibility or live
provider end-to-end behavior.
