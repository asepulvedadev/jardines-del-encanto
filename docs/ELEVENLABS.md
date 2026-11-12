# ElevenLabs: shared CRM and Sara voice provider

Implementation contract for the owner's request to share ElevenLabs across the CRM
and Hermes/Sara. Runtime installation is administrator-authorized; provider
activation still requires a separately configured key and explicit enablement. Existing OpenAI
voice-note transcription remains unchanged.

## Boundaries

The browser uses the authenticated CRM BFF. Sara uses the existing single
`jardines_app` broker tool. Neither receives a vendor key. A dedicated private
`voice-gateway` stores the key and talks only to `https://api.elevenlabs.io`.
There is no generic URL, HTTP, shell, MCP or self-programming capability.
All paid operations are exact, expiring human-approved proposals. Calls additionally
require an explicit recipient-consent checkbox in the approval, not model input.
Ambiguous dispatch is consumed and never retried automatically. Connection changes
invalidate pending proposals. Session credentials never enter chat, audit or DB.

## Shared interfaces (v1)

Gateway: HTTP on port 8092, fixed `http://voice-gateway:8092` (loopback allowed only
for local development). All routes except `/health/live` require a constant-time
validated `Authorization: Bearer ...` from `ELEVENLABS_GATEWAY_TOKEN_FILE`.
The token is a project-only service secret, NOT the ElevenLabs key. API uses the
same token file. Gateway private directory: `ELEVENLABS_STATE_DIR`, default
`/var/lib/jardines-elevenlabs`. Missing service token fails closed.

Gateway JSON routes:

- `GET /state`: `{configured, verified, revision, key_suffix, defaults:{voice_id,model_id,agent_id,phone_number_id}}`.
- `POST /configure`: `{revision,api_key?,defaults?}`. Optional key means retain
  current key. Verify new key with the vendor before atomically saving; no secret
  echo. Defaults are bounded fixed ID strings. Revision starts at 0.
- `POST /disconnect`: `{revision}`. Remove key/defaults, increase revision.
- `POST /catalog`: `{revision}`. Return `{revision,voices:[{id,name}],models:[{id,name}],agents:[{id,name}],phone_numbers:[{id,name}],limited,errors:[catalog_name]}`.
  Bound each catalog to 50 items, explicit partial permission errors. No raw vendor
  objects, URLs, account metadata or key data.
- `POST /execute`: `{id,revision,operation,arguments}`. UUID id is the proposal ID.
  Reserve durably before vendor I/O, reject duplicates even after uncertain failure.
  Supported operations: `tts`, `stt`, `agent_session`, `outbound_call`.
  TTS arguments `{text,voice_id,model_id}`; max1500 characters, fixed
  `mp3_22050_32`, max2MiB audio. Result `{status:'completed',mime_type:'audio/mpeg',data_base64}`.
  STT arguments `{data_base64,mime_type}` from an owned validated audio attachment
  only (max512KiB), fixed `scribe_v2`, bounded transcript16000 chars.
  Result `{status:'completed',text}`.
  Agent session arguments `{agent_id}`, fixed WebRTC token endpoint; gateway keeps
  token in volatile memory for at most60 seconds, returns only `{status:'ready'}`.
  Outbound call arguments `{agent_id,phone_number_id,to_number}`; Twilio endpoint
  only, E.164 recipient. No recording opt-in. Result sanitized
  `{status:'completed',conversation_id?,call_id?}`; vendor `success:false` is failure.
- `POST /sessions/{id}/claim`: `{revision}`. One-shot WebRTC material
  `{token,conversation_id?}`; expiry/revision checked; never logged or persisted.

CRM API (all authenticated admin, CSRF for mutations, no-store):

- `GET /crm/voice/settings`: gateway sanitized state + `enabled` boolean from
  control connection. Missing gateway returns a sanitized unavailable state.
- `POST /crm/voice/settings`: gateway configure body; never audit request/key.
- `POST /crm/voice/disconnect`: `{revision}`.
- `POST /crm/voice/catalog`: `{revision}`. Display labels are clipped to120
  characters consistently across the gateway/API boundary; IDs stay unchanged.
- `POST /crm/voice/attachments`: `{filename,mime_type,data_base64}`. Stage validated
  owned audio up to512KiB without triggering OpenAI or a paid provider operation;
  return `{attachment_id,filename,mime_type,size}` for an STT proposal.
- `POST /crm/voice/sessions/{proposal_id}/claim`: `{}`; requires approved owned
  session-bound `voice.execute` agent_session proposal, live connection/revision.
  This endpoint alone returns one-shot material; never accessible to broker.
- `GET /crm/voice/artifacts/{id}/content`: owned generated audio, max2MiB,
  attachment disposition, nosniff/sandbox, not a vendor URL.

Broker additions (also available to the app via existing `/crm/hermes/actions`):

- `voice.catalog` arguments `{}`: sanitized state, cached bounded catalog if
  present, and operation schemas; read only, no paid provider operation.
- `voice.execute` arguments `{operation,arguments}`: validate against a strict
  per-operation model before proposal persistence. TTS uses explicit catalog
  voice/model IDs; STT `{attachment_id}` uses existing owned audio. Agent session
  `{agent_id}`. Call `{agent_id,phone_number_id,contact_id,expected_phone}`; verify
  current contact phone exactly at proposal and again at approval. Do not add
  customer fields. Never permit raw audio, credentials or arbitrary numbers in
  broker arguments. Freeze provider revision and control connection version.

Paid dispatch uses the broker's external reserve/commit pattern outside DB
transactions. `resolve(..., consent_confirmed=False)` and optional strict boolean
`consent_confirmed` in the human approve payload preserve existing callers.
Outbound calls require `True`; reject has no side effect. TTS persists private
`crm.voice_artifacts` and returns only `{status,artifact_id,content_path}`. STT
returns text. Session returns only `{status:'ready',session_id:proposal_id}`.
All failures after reservation return `external_outcome_unconfirmed,retryable:false`.
One owner is limited to100 generated artifacts /25MiB; no automatic deletion.

## UI

Add ElevenLabs to Settings > Conexiones with icon, edit and on/off controls.
Editor: password input (never populated), connection status, voice/model/agent/
phone defaults, catalog refresh, disconnect confirmation, compact capability labels.
A small voice workspace lets the human draft TTS, transcribe an uploaded audio,
start an agent session, or draft a call to an existing CRM contact. Submission
creates a proposal first. The same proposal UI serves Sara actions. Render owned
TTS audio; session start requires a separate explicit click and microphone consent.
Use the official SDK, stop/end on close/unmount, handle denied permission and stale
async start, cap browser session duration to5 minutes. This client timer is NOT a
vendor billing/security guarantee. Never label an ElevenLabs agent as Hermes;
Sara remains Hermes and can orchestrate approved voice operations through broker.

## Coverage and limits

This first adapter covers catalog, TTS, STT, private browser agent sessions and
Twilio outbound-call requests. ElevenLabs agent and phone provisioning stay in
ElevenLabs. Voice cloning, music, dubbing, sound effects, SIP and campaign automation
are NOT implemented. A configured key alone does not mean those features work.
No customer outreach, recording, paid generation, mic access or provider test is
performed automatically. Existing CRM auth and model selection remain unchanged.

## Verification and rollout

Use fake vendor responses only for automated tests. Test auth/CSRF, fixed hosts,
no redirects/proxy inheritance, bounded responses, secret redaction, stale revision,
once-only dispatch, exact recipient consent, owner-only audio/session claims,
manifest size and runtime allowlist. A production rollout must install root-owned
gateway policy/token/storage, update both Hermes policy services and migrations,
back up existing project state, and check sibling isolation. No deployment is
part of this local change. Key storage requires protected/encrypted backups; do
not include private gateway state in repository archives.

## Primary references

- [Authentication](https://elevenlabs.io/docs/api-reference/authentication)
- [Text to speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
- [Speech to text](https://elevenlabs.io/docs/api-reference/speech-to-text/convert)
- [Voice search](https://elevenlabs.io/docs/api-reference/voices/search)
- [WebRTC token](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get-webrtc-token)
- [Twilio outbound call](https://elevenlabs.io/docs/eleven-agents/api-reference/integrations/twilio/outbound-call)
- [JavaScript SDK](https://elevenlabs.io/docs/eleven-agents/libraries/java-script)

## Administrator activation checklist (not executed)

1. Review this release, the additive SQL migration and root-owned gateway modules.
   Retain the previous healthy release and an isolated database backup. Do not
   reuse another project's key, token, volume, network or port.
2. Install gateway policy under the project's root-owned policy directory. The
   root gate automatically appends the installed fixed overlay for CRM releases,
   including recovery and rollback. Never replace the base Compose file or attach
   the API to public egress. Install prerequisites before the overlay activation
   marker, and explicitly start the optional gateway once.
3. Generate a new project service token outside the repository with a private
   file mode readable only by the gateway/API runtime UID. Mount it read-only
   into those two services. It is not a vendor API key. Initialize the dedicated
   private volume as the gateway UID, mode0700. Do not expose the gateway port.
4. Install the updated `operator_protocol.py` into BOTH the operator-provider
   and Hermes bridge policy mounts, plus the reviewed `operator.py` prompt.
   Recreate both services together. Old runtime policies reject the new action
   names; never call that a provider outage or silently enable native tools.
5. Apply migration010 with the existing migrator. Recreate only this project's
   services with the reviewed overlay. Check anonymous401, CSRF, missing-key
   status, disabled connection and unchanged sibling container/vhost metadata.
6. The administrator enters a newly issued least-privilege ElevenLabs key in
   Settings > Conexiones > ElevenLabs over HTTPS. Include user-read for key
   verification and only the voice/model/agent/phone scopes actually needed.
   Refresh catalogs, select defaults, and explicitly enable the connection.
   No paid request is needed to verify configuration/catalog permissions.
7. A real generation, microphone session or recipient call is a separate manual
   test with explicit consent and an acknowledged vendor charge. This code's
   fake-provider tests do not prove live account quota, telephony readiness,
   call compliance or actual audio quality.

The overlay-aware deployment gate retains the gateway network/token during CRM
recreation and refreshes only an already-running gateway. Gateway installation
and gate changes require administrator authorization and review. Before production use, decide artifact retention, encrypted off-host
backup of DB/audio, and whether to back up or instead reissue the provider key.
Never publish gateway state or transient session credentials in support bundles.
Disconnect removes the locally stored provider key; it does not revoke the key in
ElevenLabs or terminate a provider conversation/call already started.

## Initial pre-release verification

- Production build, TypeScript, Ruff, changed-file Prettier and whitespace checks pass.
- API suite:231 passed, including34 voice cases and5 actual API-to-private-gateway
  HTTP probes using a fake vendor. Existing TestClient deprecation warning remains.
- Web suite:78 passed, including9 deterministic fake-SDK lifecycle cases.
- Runtime/infrastructure suite:105 passed,1 skipped because its explicitly pinned
  Hermes container fixture was not enabled. This is not a live model/provider test.
- Synthetic browser checks at390/1440 confirm no automatic paid execution, empty
  password readback, separate call consent and no horizontal overflow.
- Independent verification caught a gateway/API label-length mismatch. The shared
  boundary now preserves IDs and clips display labels to120; the HTTP regression
  and independent targeted recheck pass. Pending-start disconnect and nested
  collapse cleanup also have deterministic regressions.
- No real key, microphone, paid operation, customer call, remote mutation, commit,
  push or production deployment was performed for this feature.

Private local evidence lives in the ignored `.local/verification/elevenlabs/`.
Real provider quota, audio quality, telephony readiness and live SDK microphone
behavior remain unverified until separately consented activation tests.
