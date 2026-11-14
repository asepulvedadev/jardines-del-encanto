# Sara IA chat UI

Sara IA is the existing project Hermes operator presented as a dedicated light,
forest-green, Manrope workspace. It does not introduce another agent, a live call,
TTS, browser speech recognition or a provider credential store.

## Composition and state

`SaraPanel({csrf,onChanged})` fills the parent CRM flex layout.
Saved conversation history and messages come only from private server routes. A named
native history dialog supports search across loaded conversations and cursor paging,
without a permanent second navigation rail. A compact toolbar exposes history,
one-click new chat, title editing and refresh. Skills management remains only in
Settings → Customizations. On first use an
empty server list creates one untitled conversation through the existing guarded
route. The user does not need to fill a title form before writing.
Message pages arrive chronologically; older pages prepend without duplicates.
Stale conversation pages cannot erase a newly created conversation or newer title.

Draft text and accepted attachment metadata are retained separately per conversation
in component memory, never local/session storage. Selection changes cancel history
requests and local recording/preview resources. History responses have generation
and selected-conversation guards; late turn results update only their original
conversation. Reload restores server history, not unsent local drafts or files.

Each explicit turn gets one `crypto.randomUUID()` request ID. Ambiguous and pending
responses remain visible and block another turn in that conversation. Comprobar envío
resubmits the exact same ID and payload, not a new provider execution ID. There is no
automatic provider retry. Acknowledged user/assistant messages and execution results
come from the server; the UI never fabricates a saved message or assistant reply.

## Immediate send feedback and confirmed activity

Submission immediately renders a local outgoing bubble and clears the composer;
its “Enviando…” label is not a saved-message acknowledgement. The original draft
and attachments remain in memory for recovery. A successful confirmation clears
only the matching restored draft, never edits made afterward. History includes each
message's stable `request_id`, so a lost acknowledgement can reconcile the exact
local bubble without content matching or duplicate rows.

While the selected conversation has a sending turn, the browser makes one
nonoverlapping, abortable progress GET every 1.8 seconds (first check after 300 ms).
The fixed owner-authenticated endpoint is
`GET /crm/sara/conversations/{conversation_id}/messages/{request_id}/progress`;
the web gateway exposes the same path under `/api/crm`. It accepts no query strings
or writes, never settles a turn and never starts or retries Hermes. Missing messages
return 404 until persisted. Progress reads do not acquire run/conversation locks.
Polling stops on selection change, unmount or POST settlement. An unavailable
progress check is disclosed without replaying the submission.

Progress returns only the owned user message, persisted run phase and at most 12
committed tool activities with static Spanish labels and completed/proposal/failed
outcomes. Unknown/custom actions use a generic label. Activities are a stable set,
not a chronological trace: call IDs do not encode execution order. Arguments,
results, credentials, internal prompts and model reasoning are not progress output.
A prepared proposal remains explicitly subject to human approval. No synthetic
step timer, token animation or word-by-word response is used; the final answer still
arrives through the existing synchronous, idempotent turn response.

The owner requested the personal Hermes chat in the local `asepulvedadev` project
as the reference. Its public `app/static/index.html`, `style.css`, `app.js` and
`activity.js` establish one centered chat column, left-aligned welcome, modal
history, icon controls and grouped activity. Adapt structure and interactions, not
its black/orange theme, privileged configuration screens, streaming protocol,
model switching or live dictation. The reference project is read-only and unchanged.
Sara retains professional Spanish, Manrope, Jardines green/light tokens and the
existing typed API, model restrictions and approval authority.

Enter submits once; Shift+Enter preserves multiline input and an active IME does
not submit. Recording/permission acquisition blocks submission even through the
keyboard. The one file picker accepts existing supported documents and audio;
selected audio goes to local preview, never straight to the transcription service.

Existing exact proposal/results components are reused. Confirmed results are grouped
in a collapsed activity section; pending exact proposals stay outside it. A historical proposal with
`resolvable:false` renders original arguments and an unavailable/expired/history
label, without approval/rejection controls. Successful actions followed by failed CRM
refresh display a separate warning rather than suggesting a repeated mutation.

## Skills and files

Typing `$` at the start of a token opens an inline, server-backed skills picker
above the composer, outside its clipped attachment/preview scroller.
Names/descriptions filter as the user types; inactive skills are labelled and cannot
be selected. Arrow keys move through usable skills, Enter/Tab or a click inserts a
plain `$[Name]` mention without sending, and Escape closes the picker. IME does not
select or send. The picker reloads on each opening, ignores late closed-menu responses
and has loading/error/empty states. Mentions do not grant permissions or replay
instructions; effective project skills remain bounded guidance in the next broker
claim. No toolbar Skills icon or duplicate management modal remains.

History rows expose a named delete button and a separate native confirmation dialog.
Cancel and Escape are non-destructive; a pending delete cannot be double-submitted or
silently dismissed. The UI updates only after a server acknowledgement (or a 404
confirming an already absent loaded conversation on retry), preserves failures, and
removes deleted conversation drafts/cache entries. Active/uncertain sends and uploads
block local deletion; the server independently rejects active turns. Pagination is
refreshed after deletion, and stale list responses cannot resurrect deleted rows.

Documents support UTF-8 TXT/MD/CSV and text PDF through the fixed private upload API.
The client checks supported MIME/extension combinations, 512 KiB per file and four
composer attachments; the server remains authoritative for magic, extraction, owner
quota and permissions. Uploads use bounded JSON/base64 with independent CSRF/session
protection. Extracts and filenames render as plain React text, never HTML.

Private original downloads and audio playback fetch only the fixed owned content
route, reject unexpected content types, bound streamed bytes and use temporary Blob
URLs. URLs and in-flight playback fetches are cleaned up on navigation/unmount.
History labels audio text as an extract; the upload response supplies the fuller
transcript for review before explicit message submission.

## Voice notes

Voice capability is server-owned. When unavailable, recording and audio upload stay
disabled with a concise reason; text and document use remain available. Browser
capture requires an explicit click in a secure context and a supported WebM/Ogg/MP4
MediaRecorder format. Unsupported capture falls back to compatible audio upload.

Capture is local, bounded to 60 seconds and 512 KiB. Stop, cancel, size/error exits,
conversation change, pending permission cancellation and unmount all release tracks.
A recording or uploaded audio first becomes a local player preview. Usar nota is a
separate explicit upload/transcription action. A transcription failure retains that
preview for review/discard or an explicit retry. The resulting transcript appears in
the composer before the independent Enviar action. No microphone opens on mount.

## Observed verification

- Initial source regressions: three RED, then GREEN.
- Eleven focused source, TSX rendering, MIME/base64, history merge and fake-media
  tests passed. These include historical approval exclusion, escaped message text,
  stopped tracks, oversized capture cancellation, pending-permission cancellation
  and the 60-second automatic stop.
- Worktree TypeScript checks and the final production build passed. Private API
  integration and native Hermes history are tested separately; no live paid
  provider or production end-to-end claim is made.
- A loopback API fixture and actual CRM/Sara entry exercised per-conversation drafts,
  rename/create, server history across reload, cursor paging/search, chronological
  prepend, same-ID ambiguous reconciliation, delayed-reply isolation, exact approval,
  skills preview/Escape focus and management opening the real customization tab.
- Document/audio fixtures exercised preview before upload, transcription-unavailable
  retention and explicit retry, transcript review before send, private download and
  playback, and Blob URL revocation after navigation.
- Browser fake MediaRecorder performed three explicit starts and three track stops
  across stop, conversation change and component unmount. No real microphone or paid
  provider was used. Voice-unavailable state disabled both recording/audio upload.
- At 390×900 and 1440×900 the panel reached the available bottom edge without
  horizontal overflow; the composer remained inside the dedicated chat layout.

Screenshots and final test logs are retained in the ignored local directory
`.local/verification/sara-ia/`; temporary fixture servers and browser are stopped,
and disposable scripts/media are removed after verification. The intentional
ambiguous-turn/transcription fixture503 responses and unsupported background social
fixture404 responses are not live service failures. Real microphone permissions,
provider transcription, other browser engines and production deployment are outside
this local UI proof.

## Personal-assistant refinement — local only

The 2026-11-11 owner revision replaces the permanent history column with a modal,
centers the transcript/composer, enlarges the left-aligned welcome, groups confirmed
activity and reduces repeated text to labeled icon controls. The reference's live
voice and streaming features are not copied or simulated. Existing Hermes/API,
session/CSRF guards, pending-action approval and server data formats are unchanged.
The reference repository's pre-existing edits and the primary checkout's concurrent
domain work remain untouched. This refinement is in the attached worktree on
`codex/sara-chat-refinement`; no commit, push or production deployment is included.

Regression evidence: three new composition/interaction tests were observed RED
before implementation and GREEN afterward. A further focused CSS regression caught
double composer focus boundaries and the activity summary's overridden target size;
its fix retains one visible compound-control focus indicator and a44px summary.
The browser fixture independently exercised first-use creation under StrictMode,
one-click new chat, modal focus, paging, per-chat drafts, IME/keyboard submission,
recording guards, ambiguous request identity and explicit audio review/upload/send.
No real microphone, model inference, transcription or action execution was invoked.

Final refinement checks: production build and TypeScript passed; all57 CRM gateway,
settings, OAuth and Sara checks passed (15 focused Sara tests). Browser fixtures
showed no horizontal overflow at320/390px and verified the desktop1440px composition.
The targeted final style probe confirmed no inner textarea outline, a visible outer
composer focus border/shadow, a44px activity summary and history focus restoration.
Updated screenshots/probe logs are retained in ignored
`.local/verification/sara-reference/`. Temporary browsers/fixture servers are stopped
and disposable scripts/media removed. API, database, production, microphone and
provider services were not contacted or changed by this UI refinement.

## Refinement production authorization — 2026-11-11

The owner subsequently requested “despliegalo”, authorizing publication through the
existing GitHub Actions/VPS gate. Preserve the newer public-domain/SEO commits from
main and the installed Hermes policy, credentials and data. Preflight confirmed the
existing production `/crm` response denied microphone access globally. A narrow
CRM-only `Permissions-Policy` override must allow same-origin microphone capture;
public pages keep camera, microphone and geolocation denied. This enables the
already-requested explicit voice-note control, not automatic capture, live calls,
provider tests or a broader origin policy.

The focused permission-policy regression was observed RED before the override and
GREEN afterward. Independent source review found no auth/origin/authority expansion.
The built Next HTTP server returned `microphone=(self)` on `/crm` and its namespace,
while `/`, `/login`, `/crm-other` and `/health` retained complete microphone denial;
camera and geolocation stayed denied on every probe. No getUserMedia call was made.
Merged public-domain/SEO source retained its current routes and CRM separation.
Final local checks: production build, TypeScript and58 CRM/UI/gateway tests passed;
merged public web checks passed25 tests with six opt-in browser checks skipped.

### Current revision verification

The `$` picker and confirmed conversation deletion were verified with a real local
Next UI and synthetic private API responses at 390×844 and 1440×1000. This caught a
clipped absolute picker whose pointer events reached the transcript; the picker now
occupies its own bounded flex row above the composer. Keyboard and mouse selection
insert a mention without posting a message. Injected deletion409/500 preserve state;
404 retries remove stale rows. Cancel, Escape, focus restoration, one DELETE under
double activation, selected/nonselected/last deletion, draft cleanup, stale-list
filtering and Settings-only skills management were observed. No real provider,
customer account or microphone was used. Final option-scroll and destructive-hover
polish has type/unit coverage but was not separately browser-retested.
