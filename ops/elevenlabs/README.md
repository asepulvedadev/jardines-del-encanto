# Private ElevenLabs gateway

This administrator-installed overlay is intentionally separate from application
releases. It is not an activation script. No key, provider request or paid test is
needed to run the fake-provider unit suite.

## Installation boundary

Review `gateway.py` and the merged root-owned CRM/voice Compose policy before
installation. Saving an API key in the CRM does not install this policy. Only the
API and gateway share the internal `voice` network. The gateway alone has its own
egress network and `jardines_voice_config` volume. No public port is published.
The literal HTTPS host is `api.elevenlabs.io`; bounded DNS workers reject nonpublic
addresses and TLS verifies that literal hostname. The transport neither inherits proxy
environment variables nor follows redirects, and accepts only fixed finite routes.
The separate existing Zernio egress network and Hermes provider remain unchanged.

The administrator must provision:

- Root-owned policy directory `/srv/jardines-del-encanto/elevenlabs-policy` mode0700,
  root-owned reviewed gateway file mode0644, and root-owned overlay mode0600.
- Project-only random gateway token (32–128 URL-safe ASCII characters) at
  `/srv/jardines-del-encanto/secrets/elevenlabs-gateway.token`, readable only by the
  intended UID10001 service processes (mode0400 or0600). Both API and gateway mount
  that token. Never reuse the ElevenLabs key as this internal service token.
- Dedicated named volume `jardines_voice_config`, initialized with its root owned
  by UID/GID10001 and mode0700. Do not mount this volume into the API or Hermes.

The overlay is merged with the fixed project CRM policy, not run as a second
independent stack containing an incomplete `api` service. Preserve existing API
networks while adding `voice`, and retain the existing project Compose name. Verify
merged policy before restart. The gateway uses an already verified application
image selected by `RELEASE`; release code cannot replace the root-owned gateway
policy. The overlay-aware administrator-owned gate appends the installed fixed overlay
for every CRM recreation, including rollback. After readiness it refreshes only an
already-running gateway to the selected release image, never a stopped service.
Initial gateway start remains an explicit administrator operation. Install token,
volume and policy prerequisites before atomically installing this overlay marker;
never downgrade the gate alone while leaving the marker active.

`/health/live` proves only process liveness. Every other route checks the project
service token and fails closed if absent/unreadable. Vendor verification requires
ElevenLabs `GET /v1/user` access; a key lacking that permission is not saved as
verified. Successful account verification does not prove catalogs or paid features
are permitted. Catalog permission/transport failures return named partial errors.

## Private state and operation semantics

The `state.json` journal is0600; the directory is0700. Reads reject symlinks,
nonregular files, wrong ownership/permissions, duplicate JSON keys and oversized
state. CAS updates use a file lock, temporary0600 file, fsync, atomic rename and
parent-directory fsync. The journal stores only the vendor key, revision/defaults,
verification flag and reserved proposal UUIDs; no audio, transcript, recipient,
provider response or session token is persisted here. Keep this volume out of
repository archives and protect/encrypt operational backups. Disk encryption and
backup access policy remain administrator responsibilities.

A validated execution reserves its UUID durably **before** provider I/O. Duplicate
UUIDs remain rejected after errors/restarts; rotation/disconnect retain reservations.
The reservation is the dispatch authorization linearization point: an already
reserved in-flight request may complete during rotation and cannot be unsent.
After reservation, unknown provider results remain `external_outcome_unconfirmed`;
there are no automatic retries. The bounded journal holds10,000 reservations and
fails closed when full; it never silently evicts tombstones. Capacity extension or
archival requires a separately reviewed operational change.

The HTTP server admits at most four concurrent request workers and eight queued
connections. Ingress has an absolute8-second wall deadline and8-second idle
timeout. Metadata fetches do not hold the private-state lock during vendor I/O.
TTS/STT/calls have a25-second
upstream deadline; metadata/token requests have5 seconds each. Catalog retrieval
makes exactly four bounded requests, without following pagination. Each catalog
returns at most50 sanitized ID/name pairs and explicit `limited`/`errors` flags.
Models are restricted to entries explicitly supporting TTS; phone numbers are
restricted to Twilio. Call requests force `call_recording_enabled:false`.

WebRTC material exists only in volatile process memory for at most60 seconds and
is claimed once using the approved proposal UUID and unchanged configuration
revision. Rotation clears material. Restart loses material and does not reopen the
reserved execution. The60-second local handoff expiry is **not** a vendor token
lifetime or session billing limit. The API must perform owner/session/proposal and
connection checks before invoking any gateway operation or session claim.

All HTTP responses are `no-store`; errors are fixed sanitized codes and request
logging is disabled. Private binary results remain between gateway and API; the API
stores owned artifacts and returns only private IDs/paths to Sara.

## Primary endpoint references

- [Account verification](https://elevenlabs.io/docs/api-reference/user/get)
- [Voice catalog](https://elevenlabs.io/docs/api-reference/voices/search)
- [Models](https://elevenlabs.io/docs/api-reference/models/list)
- [Agents](https://elevenlabs.io/docs/eleven-agents/api-reference/agents/list)
- [Phone numbers](https://elevenlabs.io/docs/eleven-agents/api-reference/phone-numbers/list)
- [TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
- [STT](https://elevenlabs.io/docs/api-reference/speech-to-text/convert)
- [WebRTC token](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get-webrtc-token)
- [Twilio outbound](https://elevenlabs.io/docs/eleven-agents/api-reference/integrations/twilio/outbound-call)

Tests: `python3 -m unittest discover -s tests -p 'test_elevenlabs_gateway.py' -v`.
No real key, inference, transcription, microphone or call is used by these tests.
