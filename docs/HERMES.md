# Jardines Hermes: provider-only activation

## Scope

The owner authorized the project's isolated Hermes on `2.24.111.40`, using the
administrator's existing Ed25519 SSH identity and an owner-supplied OpenAI key.
This enables **on-demand text inference only**, not a messaging gateway, public chat
endpoint, CRM integration, autonomous sales agent or scheduled job.

Current model: `gpt-6-luna`, using Chat Completions with `reasoning_effort: none`.
This preserves the previous direct-response workload and its token/call limits. The upstream Hermes image remains pinned
at the digest in `ops/hermes/compose.yaml`; do not silently update it.

## Credential and execution boundaries

- Root-only host parent: `/srv/jardines-del-encanto/secrets/`.
- Credential: `hermes-openai.key`, mode `0400`, container reader UID/GID `1000:1000`.
  Only the provider container mounts this file. Neither Hermes nor Docker environment
  metadata contains the actual key. Host root/Docker administrators can still read it.
- A dedicated internal Docker network connects Hermes only to the credential-injecting
  provider. Only that provider also joins its dedicated egress bridge.
- The provider forwards only `POST /v1/chat/completions` to the fixed HTTPS OpenAI host;
  it does not follow redirects or accept arbitrary URLs, models, tools, files or images.
- Requests: 64 KiB body, text messages only, 512 output tokens maximum, six upstream
  attempts/minute and one attempt per invocation identifier (retained for five minutes).
  These are operational limits, **not an account-level monthly spending cap**. Set a
  project budget/alerts in OpenAI separately. Identifiers are not authentication and
  do not replace network isolation; only administrator-launched workloads join this network.
- The wrapper uses 128 output tokens, one turn, no tools, no fallback provider,
  no memory/context loading, and an ephemeral home. Its subprocess audit guard also
  blocks initialization probes; its socket guard allows only the private provider.
- Non-root processes, read-only roots, dropped capabilities, no-new-privileges,
  resource/PID/log caps and temporary filesystems. No public ports, host workspace,
  CRM/database credentials, SSH keys, Docker socket or persistent conversation mounts.
- The image's supervisor entrypoint is bypassed: no gateway, dashboard, cron dispatcher
  or messaging adapter is started. One idle provider service remains running.
- Provider logs contain only status codes and allowlisted error categories, not keys,
  authorization headers, request bodies or conversation text.

Docker and Python audit hooks are not a VM/security boundary against a compromised
host, native extension or trusted administrator. Keep the provider small and the
shared daemon private. This setup intentionally does not give the agent operational tools.

## Administrator operations

Runtime policy is independent from application CI deployments:

- `/srv/jardines-del-encanto/hermes-active.compose.yaml`
- `/srv/jardines-del-encanto/hermes-policy/{provider.py,assistant.py}`
- `/srv/jardines-del-encanto/hermes-run`

After reviewing `ops/hermes/`, install those files using the explicitly authorized
administrator connection. Keep the policy directory root-owned/mode `0700`; Python
files must be readable inside the non-root containers (`0644`). Install the Compose
policy as `0600` and wrapper as `0700`. Never put a credential in an archive, shell
argument, heredoc, GitHub secret for application CI, frontend bundle or repository.
Send it through hidden stdin to create the exclusive secret file, then set its ownership
and mode as above. Do not overwrite an existing credential silently.

Run locally **on the server as its authorized administrator**:

```sh
printf 'Responde exactamente: HERMES_JARDINES_OK\n' | /srv/jardines-del-encanto/hermes-run
```

Each manual invocation may incur OpenAI charges and sends its prompt to OpenAI.
Never use customer information until a separate CRM/data-processing authorization.
The wrapper accepts 1–4096 characters on stdin and returns bounded JSON. A successful
activation requires `ok: true` and the expected response; a healthy proxy alone does
not prove the key, model entitlement or billing works.

Inspect only sanitized diagnostics:

```sh
docker compose -f /srv/jardines-del-encanto/hermes-active.compose.yaml ps
docker compose -f /srv/jardines-del-encanto/hermes-active.compose.yaml logs --tail 20 provider
```

Disable outbound inference without changing the website or deleting secrets/state:

```sh
docker compose -f /srv/jardines-del-encanto/hermes-active.compose.yaml stop provider
```

A subsequent invocation of the wrapper starts the provider again. To revoke access,
rotate/revoke the key in OpenAI and update the protected server file through an
explicitly authorized administrator session. Restart only this project's provider.
A key pasted into chat should be rotated; no automatic revocation is performed.

## Verification

Local deterministic tests (no provider credentials or paid calls):

```sh
python3 -m unittest discover -s tests -p 'test_hermes_provider.py'
python3 -m unittest discover -s tests -p 'test_*.py'
docker compose -f ops/hermes/compose.yaml config --quiet
```

Activation evidence and remaining limitations are recorded below after the live probe.

### Live activation — 2026-11-10

The authorized VPS returned:

```json
{"ok": true, "model": "gpt-4.1-mini", "tools": 0, "api_calls": 1, "response": "HERMES_JARDINES_OK"}
```

The real smoke turn succeeded through Hermes and the private provider. Earlier
compatibility probes were rejected locally before forwarding: the pinned Hermes
runtime supplies a default `reasoning_effort: medium` even on custom routes. The
fixed-model proxy now discards that known default for this non-reasoning model,
with a regression test, and continues rejecting other unexpected request fields.

The agent is not exposed in the CRM UI and has no business knowledge source or
customer data access. Adding those capabilities is a separate implementation.

Final hardened-policy smoke returned the same success after the UDP guard correction.
The combined infrastructure/provider suite passed 20 tests; an independent read-only
verification passed the 10 provider/guard tests, policy hashes, secret metadata,
effective tmpfs mounts and runtime restrictions. Application release/Compose checksums,
readiness and all named application container IDs were unchanged. One baseline random
transient container disappeared during offline inspection; its exact identity was not
retained, so complete transient-inventory preservation is not claimed.

The upstream image declares `/opt/data` as a Docker volume. An explicit tmpfs shadows
that path; inspect effective mounts rather than relying only on Docker's volume listing.
The runtime guard denies UDP/sendmsg/listeners as well as non-provider TCP connections
and subprocesses; the UDP bypass has a regression test.

### Model change — 2026-11-10

The owner requested GPT-6.1 Sol or Luna. GPT-6 Luna (`gpt-6-luna`) was selected
for the current focused text-only workload; no tool permissions, credential mounts,
network access or token/call limits were expanded. The fixed-model proxy emits
`max_completion_tokens` and explicitly sets `reasoning_effort: none`, supported
by Luna, instead of the previous GPT-4.1 Mini parameter normalization. The previous
activation output above is historical evidence, not the current model.

References: [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[GPT-6 migration compatibility](https://developers.openai.com/api/docs/guides/latest-model).

Current-model smoke succeeded on the authorized VPS:

```json
{"ok": true, "model": "gpt-6-luna", "tools": 0, "api_calls": 1, "response": "HERMES_JARDINES_LUNA_OK"}
```

All 20 infrastructure/provider tests passed. Independent verification confirmed deployed
source hashes, unchanged token/call guards, baseline application/container identities,
release/Compose checksums and healthy readiness. No credential rotation, CRM deployment,
new tools or public endpoints were performed during the model change.
