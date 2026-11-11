# Sara IA: persistent Hermes workspace

Sara IA is the product name of the existing Jardines Hermes operator, not a second
agent. Owner scope: Dashboard navigation, a dedicated chat, conversations/history,
project skills, documents and voice notes. No live call, TTS, external account
activation, production changes or deployment is authorized by this implementation.

## Shared implementation contract

All routes below are administrator-only under `/crm/sara`, using existing session,
Origin and CSRF checks. Owners can only access their own conversations/files.
JSON bodies only; no provider key, arbitrary URL, shell or native plugin access.
Existing `/crm/hermes/*`, proposals and social/OAuth flows stay compatible.

| Route                           | Request                                                  | Response                                                                                                           |
| ------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| GET status                      | none                                                     | `{available,enabled,model,tools_count,voice_available}`                                                            |
| GET conversations               | `?before=<optional UUID>`                                | `{conversations:[{id,title,created_at,updated_at}],next_cursor}`; 30 per page                                      |
| POST conversations              | `{title?:string}`                                        | conversation object                                                                                                |
| PATCH conversations/:id         | `{title:string}`                                         | conversation object                                                                                                |
| GET conversations/:id/messages  | `?before=<optional UUID>`                                | `{messages:[Message],next_cursor}`; 50 chronologically ordered from latest page                                    |
| POST conversations/:id/messages | `{request_id:UUID,message:string,attachment_ids:UUID[]}` | `{user_message,assistant_message,state}`; assistant message nullable; state completed, pending or failed           |
| GET skills                      | none                                                     | `{skills:[{id,name,description,content,enabled,effective}]}` from application registry, not invented global skills |
| POST attachments                | `{filename,mime_type,data_base64}`                       | Attachment metadata including extracted text/transcript                                                            |
| GET attachments/:id/content     | none                                                     | private bounded binary, safe attachment Content-Disposition; no HTML inline                                        |

Message: `{id,role:"user"|"assistant",content,created_at,state:"completed"|"pending"|"failed",attachments:Attachment[],results:object[],proposals:Proposal[]}`.
Attachment: `{id,filename,mime_type,size,kind:"document"|"audio",text,created_at}`.
Use `crypto.randomUUID()` request IDs; retrying the same ID MUST NOT trigger a new
provider run. One active turn per conversation, database-serialized with bounded
lease/recovery. A failed turn remains visible; never fabricate an assistant reply.
History survives logout. Existing proposals remain bound to the initiating live
session: histories do not gain authority to approve old proposals.

## Hermes context and private boundaries

Migration007 adds owned conversation/message/file tables and optional
`crm.hermes_runs.history jsonb NOT NULL DEFAULT '[]'`. Do not rewrite old migrations.
Extend broker.issue with optional `history=None`, preserving old calls. A claim
includes optional `history` only when nonempty: at most8 user/assistant text messages,
4096 chars each,16000 total. No historical tools, bearer identities or approval
replay. Runtime validates this shape and passes it to Hermes conversation_history.
Legacy claims retain their exact shape. User prompt stays <=8000 chars including
bounded, explicitly untrusted document excerpts; chat text <=4000 chars.
Runtime/provider accept <=8000-char user content (existing Chat already accepts8000).
Persona identifies as Sara IA while preserving all tool/approval/paging safeguards.

## Attachments and voice notes

Max512KiB decoded per file,4 attachments per message,25MiB/100 files per owner.
Store bytes privately in PostgreSQL (backups include them), never public static or
host paths. Bounded JSON/base64 uploads <=768KiB. Support UTF-8 TXT/MD/CSV, text PDFs
and recorded/uploaded WebM/Ogg/MP3/WAV/MP4 audio. Validate extensions, MIME and magic;
no archives, executable/HTML/SVG or remote fetch. PDF extraction: pypdf in a bounded
child process with memory/CPU/wall limits; reject encrypted/scanned/oversized inputs
honestly. Excerpts are data, never instructions; full original stays downloadable.

No browser SpeechRecognition service, live-call or TTS. MediaRecorder records only
on explicit click, max60 seconds; preview/discard before upload, stop tracks and
revoke object URLs on every exit. Server transcribes via the existing isolated
credential boundary, never exposing credentials to API or browser. `/transcribe`
bridge -> fixed `/audio/transcriptions` provider adapter -> fixed verified-TLS
OpenAI `/v1/audio/transcriptions`, model `gpt-4o-mini-transcribe`, Spanish language,
JSON result only. No redirects/retries or caller-selected models/hosts; bounded
request/response and rate limits; no audio/transcript/token logs. Gate transcription
with `HERMES_TRANSCRIPTION_ENABLED=1` at operator-provider. Health propagates
`history_available` and `transcription_available`; unavailable recording/upload must remain honestly labelled.
Sara status requires explicit `history_available=true` from the upgraded bridge and
provider; an older root-owned runtime must not advertise full Sara chat readiness.
New provider/helper source is installed root-owned only during a separately authorized
deployment. Keep legacy text-only Hermes profile unchanged.

Sources: [Hermes conversation history](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/guides/python-library.md),
[OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text).
The transcription alias has a published future deprecation; reassess before February2027.

## Delivery and checks

Worktree-only implementation. Preserve concurrent landing work; no Git commits,
pushes, SSH, provider/remote credential access or Engram writes (runtime identity
unavailable). Existing local test-database credentials are consumed only in memory
for the guarded isolated database, never printed or copied into the worktree.
Tests use fake provider/media only and guarded `jardines_crm_test`; reserve that DB
before a suite. Verify actor isolation, CSRF/body bounds, idempotency, lease races,
history/attachments context, session-bound proposals, stale UI state, accessible
390/1440 layouts, recording cleanup and disabled voice capability. No paid calls.

## Local implementation status

Source baseline79d5d08; dedicated branch `codex/sara-ia` in the attached managed
worktree. PostgreSQL files use bytea to stay inside private project backups; pypdf7.0.1
is the only new API dependency, with existing locked requirements hashes regenerated.
API/UI/isolated-runtime units are implemented independently against this contract.
No production activation is implied; migration007 and reviewed operator source
(including the new audio helper) require a separately authorized deployment.

The independent bounded audit found an audio-upload pause bypass: the first
implementation checked runtime voice health but not the shared connection switch.
The corrected endpoint reuses `control.require_connections` before any private
bridge probe/request, then requires explicit Boolean readiness for text history
and voice. Paused audio is rejected without external calls or stored audio;
ordinary document upload remains available. Seven public-API regression cases
cover paused, unavailable and truthy-substitute capabilities (six RED before the
fix, all seven GREEN afterward).

### Final observed checks

- Full API suite: **167 passed**, using only `jardines_crm_test`; one existing
  Starlette TestClient deprecation warning. Migration007 was applied to that
  isolated database only, not the local application or production database.
- CRM gateway/navigation/UI regression suite: **53 passed**.
- Infrastructure/runtime Python suite: **79 tests, 78 passed, one opt-in pinned
  image test skipped**. The separate cached pinned-image integration passed
  **14/14**, including genuine native Hermes history and typed tool execution,
  using fake upstream/broker fixtures and no external network.
- Public landing HTTP/source regressions: **19 passed, four optional browser
  tests skipped**. An initial invocation lacked its required local server and
  failed fetches; rerunning against the dedicated built loopback server passed.
- Production build, TypeScript, Ruff and scoped formatting/whitespace checks
  passed. Final audio authorization recheck independently confirmed no remaining
  blocker, including false/missing/truthy capabilities and paused document use.
- Browser fixtures checked the actual CRM entry at 390×900 and 1440×900,
  conversation/draft/pagination recovery, skills, private files and explicit
  voice preview/transcription/send with fake MediaRecorder and no real microphone.

Not verified: live provider inference/transcription, real microphone permissions,
other browser engines, production schema/runtime installation or a public release.
Voice remains off until separately authorized runtime installation/enablement.
No Git commit, push or deployment was performed. Evidence screenshots and logs
are retained locally in ignored `.local/verification/sara-ia/`.

## Production deployment authorization — 2026-11-11

The owner subsequently requested “despliegalo”. This authorizes publishing and
releasing this feature through the existing GitHub Actions workflow to the existing
Jardines VPS (2.24.111.40), with the existing administrator Ed25519 identity for
project-only root-owned operator policy installation. Preserve the newer landing
release4830a039 and all sibling projects. Include migration007 and the installed
Hermes history/audio helpers; enable the delivered voice-note capability using the
existing isolated provider key mount without reading, rotating or copying its
contents. Do not perform paid inference/transcription tests or transfer customer
files/audio. Record checkpoint, actual release, health and remaining live-provider
limitations after deployment. Existing sections above describe the local stage.
