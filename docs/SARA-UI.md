# Sara IA chat UI

Sara IA is the existing project Hermes operator presented as a dedicated light,
forest-green, Manrope workspace. It does not introduce another agent, a live call,
TTS, browser speech recognition or a provider credential store.

## Composition and state

`SaraPanel({csrf,onChanged,onManageSkills?})` fills the parent CRM flex layout.
Conversation history and messages come only from private server routes. The sidebar
supports creation, renaming, search across loaded conversations, and cursor paging.
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

Existing exact proposal/results components are reused. A historical proposal with
`resolvable:false` renders original arguments and an unavailable/expired/history
label, without approval/rejection controls. Successful actions followed by failed CRM
refresh display a separate warning rather than suggesting a repeated mutation.

## Skills and files

The named native skills dialog loads the application registry, exposes search and
plain-text instruction previews, and restores focus with Escape. Gestionar skills
calls the parent's actual settings/customization entry point.

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
