# Retell editor reference investigation

Inspected on 2026-11-12 at the owner's request. The authenticated Retell editor was
viewed without changing an agent, publishing, running tests, copying credentials,
or retaining private prompts. Only control labels and public script URLs were recorded.

## Evidence

- The live editor exposes separate model/language controls, first-message behavior,
  functions, knowledge/memory, speech, transcription, call settings, security/fallback,
  post-call extraction/memory, webhooks and MCP settings. Workflow and simulation are
  separate surfaces. These observations guide grouping, not execution permissions.
- REA `analyze_javascript_application` inspected the actual public editor asset
  `77c9b39b4244a2fd.js` (587144 bytes), acquired without cookies or authorization headers
  from an already-observed `dashboard.retellai.com/_next/static/chunks/` URL.
- REA parent Evidence: `ev_a42c62250477cbee2b1513ed7e32d30f2db6bb6a9f2a52b1f654c1976fe19d88`.
  Public artifact digest: `565516c5c7933b3b58bbf579487a4dda082e4f7013327d2d0e7f759d9e66700d`.
  The selected source parsed successfully and was never executed. Semantic analysis
  was bounded to5000 nodes and remains partial;17 other inventoried public assets
  were not analyzed. This is not a claim to reconstruct Retell's complete internals.
- Live REA CDP discovery found no Retell target in the locally exposed debug browser;
  the owner's actual tab was inspected through the existing Codex browser connection,
  then REA performed offline analysis of the public asset. No other page was navigated.

## Implementation boundary

The reviewed API schemas, not inferred vendor internals, govern writable fields.
The existing limited form covered only seven agent scalars. The expanded editor
accounts for the published create/update agent and Retell LLM properties, grouped like
the observed editor. Native controls handle nested objects, collections, choices,
nullable values and validation; secret-bearing controls remain blocked.

Existing snapshots may be clipped. A complex or long-text replacement must be explicit
and complete, never a silently resubmitted cached fragment. Credentials stay in their
approved connection or provider settings. Dashboard-only, newly unreviewed and multipart
features must not be presented as active merely because Retell displays them.

No Retell source code is copied into the application. The app preserves Jardines'
professional Spanish, light CRM design, approval policy and existing shared provider.
