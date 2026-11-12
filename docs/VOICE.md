# Voice workspace

The CRM sidebar includes **Voz**, backed by the existing shared Retell connection and
Sara/Hermes action broker. Provider credentials remain in **Configuraciones → Conexiones**;
the workspace does not handle keys.

## Resource workflow

- Agents: approved inventory reads, native create/edit forms, linked instructions,
  voice selection, versions, publication, deletion and browser-call preparation.
- Voices, calls, phone numbers, knowledge and tests have dedicated resource views.
- The additional tools selector provides language models/instructions, conversation
  flows, chat/SMS, Retell contacts, applications and the complete reviewed catalogue.
- Every reviewed operation remains accessible through **Todas las funciones**, including
  complex JSON arguments, pagination, batch operations, analysis and advanced settings.
  The five multipart-dependent operations remain disabled; new vendor endpoints require
  review. This does not claim complete parity with dashboard-only Retell features.

Opening Voz automatically loads the eleven fixed resource inventories through the
administrator-only `POST /crm/retell/inventory` endpoint. Tabs share that snapshot;
there is no per-section load/approval step. A short actor/session-scoped cache bounds
repeated requests; failures are isolated by resource. Narrow resource detail reads use
`POST /crm/retell/read`. See `VOICE-INVENTORY.md` for the fixed allowlist and limits.

This explicit automatic-read exception never auto-approves generic `retell.execute`.
Other catalogue operations keep their existing broker policy. Mutations, paid operations
and destructive actions retain exact proposals, explicit consent and recipient guards.
Voz renders readable values/reviews by default; raw payloads are in closed technical
details. Advanced JSON remains an explicit power-user choice rather than the main editor.

`GET /crm/retell/results` restores only bounded, sanitized, approved read results for the
current administrator **and session**, with the current enabled connection preference
revision. See `VOICE-RESULTS.md`. A fresh login has no previous-session approved snapshots; automatic reads obtain new data.
Resource lists are partial snapshots, not authoritative totals or live synchronization.
Results can contain at most 50 items and clipped text; advanced operations support
explicit pagination. The shared cache is invalidated by completed writes; external changes appear on the next synchronization.

## Safe forms

Native agent and Retell LLM editors derive fields and constraints from the reviewed
schema. New agents require an explicit voice and response-engine ID. Creating
instructions and creating an agent are separate approved actions, never an implicit
chained write. Other engine types are preserved when changing unrelated fields.

Editing sends only changed fields and known identity/version. Existing prompts and
greetings are read-only partial previews. Replacing them requires an explicit switch
and a blank full replacement draft; the cached fragment is never silently resent.
Advanced configuration is available through the reviewed operation editor.

Confirmed result callbacks update the resource view without redispatching the write, then refresh only the fixed read inventories. Failed view
refreshes do not turn a completed provider operation into a retry. Browser-call setup
reuses the existing one-shot session component; microphone access and billing require
explicit user actions. No voice preview is fetched automatically.

## Verification

- `npm run test:crm:gateway`
- `npm run typecheck`
- `npm run build`
- API tests through the guarded loopback-only CRM test runner; run database suites serially.
- Browser proof uses a loopback fixture with clearly labeled synthetic resources, never
  real calls, microphone access, provider writes or customer records.

This feature does not change the Retell registry, gateway, migrations or execution policy.
Deployment is a separate authorized operation.
