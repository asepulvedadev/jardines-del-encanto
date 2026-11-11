# Quick deployment and recovery

## Normal deployment

Push reviewed changes to `main`. The `Verify and deploy` workflow runs tests and a
complete Docker smoke test, then sends `deploy <commit-SHA>` through a constrained
SSH key. The host fetches that public repository, verifies the current main tip,
builds the two images and checks the database/API/web readiness chain.

No runner is installed on the VPS. The personal administrator key is not uploaded to
GitHub. Only the dedicated CI private key is stored in the production environment.

## Temporary HTTPS preview

Preview hostname: `jardines.2.24.111.40.sslip.io`, proxying through the project-specific
Nginx vhost to `127.0.0.1:13400`. The application, API and database ports stay private.
Search indexing is disabled in page metadata and the preview response header. This
is a public test URL, not access control; do not expose private CRM data here.
The hostname depends on the external [sslip.io DNS service](https://sslip.io/) and
should be replaced with the owner's domain before permanent launch.

### Private tunnel fallback

Use the owner's explicitly authorized administrator SSH identity:

```sh
ssh -F /dev/null -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -L 13400:127.0.0.1:13400 root@VPS_HOST
# In a browser on the same computer: http://localhost:13400
```

Do not open port 13400 to the internet. The preview uses only the existing Nginx
listeners on 80/443, with a separate vhost; it does not replace a default/sibling vhost.

## Manual deploy or rollback

As the authorized administrator on the server:

```sh
sudo /usr/local/libexec/jardines-deploy 'deploy FULL_40_CHARACTER_COMMIT_SHA'
sudo /usr/local/libexec/jardines-deploy 'rollback PREVIOUS_HEALTHY_40_CHARACTER_SHA'
```

Replace the uppercase placeholders with lowercase hexadecimal Git SHAs. `deploy`
accepts only the current fetched `main` tip, preventing queued stale jobs from
replacing a newer release. `rollback` accepts only a release
previously marked healthy on this host. Images and release directories are retained.
Concurrent manual and CI deployments share a host lock.

The current release is `/srv/jardines-del-encanto/current`. A failed activation restores
the previous application images; a failed first deployment stops only this project's
web/API, keeping its database. Rollback does not restore or reverse database migrations.
CRM deployments run checksum-checked, transactional migrations explicitly using a
short-lived maintenance container before application activation. Runtime never receives
the migration or PostgreSQL bootstrap credential. Rollback does not reverse migrations.
Root-owned `crm-releases/<SHA>` markers select `crm.compose.yaml` for CRM releases;
older healthy images retain the original `compose.yaml`, including during recovery.

## CRM production policy (one-time administrator installation)

The owner authorized the CRM release, dedicated database credentials and root-owned policy
upgrade. The verified administrator connection uses the existing local Ed25519 identity
with **`root@2.24.111.40`**, not the workstation's default username. Normal deployments
still use GitHub Actions and its restricted key; never upload the administrator key.

Review the files, transfer them through that authorized session into a private staging
directory, and install only this project's policy:

```sh
install -m 0600 crm.compose.yaml /srv/jardines-del-encanto/crm.compose.yaml
install -m 0755 deploy.py /usr/local/libexec/jardines-deploy
install -m 0755 backup.sh /usr/local/libexec/jardines-backup
python3 crm-provision.py
```

Do not overwrite legacy `compose.yaml`, rerun general provisioning with another CI key,
restart Docker/Nginx, or remove volumes. Retain private copies of the previous gate and
backup policy. Provisioning creates only `jardines_crm`, `jardines_crm_migrator` and
`jardines_crm_app` in the existing project PostgreSQL container. Secrets are generated
once in the root-only project secrets directory, never printed, committed or implicitly
rotated. Existing unmanaged roles/databases are rejected, not adopted. Maintenance alone
reads `crm-migration.env`; the API reads only `crm-runtime.env` with restricted grants.

Copy only the owner's local administrator username and Argon2 verifier for initial access,
not contacts or sessions. Never reset existing administrators. Verify HTTPS login/logout,
protected CRM redirects, database grants, landing health, logical backup/recovery and
unchanged sibling containers/vhosts. Rotate the chat-disclosed initial password through
authorized maintenance before handling sensitive customer data; no password-change UI
exists yet. Zernio configuration UI is included, but provider credentials/accounts are
not copied or activated. Hermes remains separately managed.

## Status and backups

```sh
export RELEASE=$(cat /srv/jardines-del-encanto/current)
docker compose -p jardines -f /srv/jardines-del-encanto/compose.yaml ps
curl --fail http://127.0.0.1:13400/health/ready
systemctl list-timers jardines-backup.timer
sudo /usr/local/libexec/jardines-backup
```

Backups are compressed SQL with SHA-256 checksums in the project's root-only `backups/`
directory, scheduled daily at 08:30 UTC plus up to 15 minutes jitter. They are also
taken before deployments when a current release exists. The dedicated CRM database also
receives its own `.crm.sql.gz` dump and checksum when present. No backup is automatically
deleted. Monitor disk usage; define retention and encrypted off-host storage before
collecting real customer data. A backup is not a verified restore until tested.

Restore into a **new isolated database**, never directly into live production:
verify its checksum and `gzip -t`, create an empty recovery DB, stream the SQL through
`psql -v ON_ERROR_STOP=1`, inspect its contents and only then plan a controlled switch.
Production restoration is destructive and needs separate explicit authorization.

## Hermes (offline baseline and optional provider activation)

```sh
docker compose -f /srv/jardines-del-encanto/hermes.compose.yaml run --rm hermes --version
```

The baseline pinned upstream image and state mount are project-specific. Networking is disabled;
there is no exposed port, Docker socket, host workspace mount or borrowed provider key.
The owner separately authorized provider-only activation using `ops/hermes/compose.yaml`.
See [HERMES.md](HERMES.md) for the isolated OpenAI proxy, administrator-only invocation,
verification and shutdown. The baseline above remains offline. Neither policy enables
WhatsApp, CRM tools or autonomous sales actions; those need separate authorization.

## Application operator release — administrator only

The owner authorized production deployment of the shared settings/Hermes feature on
2026-11-11. Keep the existing text-only profile unchanged. The additional policy is
`ops/hermes/operator.compose.yaml`, with its three Python modules installed together
under `/srv/jardines-del-encanto/hermes-operator/`. The folder is root-owned0700;
modules are0644 for non-root bind-mounted readers and Compose is0600. Mount
`operator.py` as `/policy/hermes_operator.py`, not its original basename, to avoid
shadowing the Python standard library.

Before activation, retain the current release, a logical backup, the previous
root-owned CRM policy and sibling-container/vhost metadata in a private deployment
checkpoint. Install the reviewed CRM policy's fixed `HERMES_BRIDGE_URL` environment
entry without changing its networks or exposing API/bridge ports. The operator uses
only the existing project credential file; do not print, rotate or copy its contents.

Push the verified release to main and observe the existing GitHub Actions deployment.
The gate performs backup, migrations005/006 and application health checks. Then start
only this project's additional operator stack using its root-owned policy. The shared
`jardines_app` network must remain internal. Check credential/provider readiness,
fixed model, private broker reachability and public auth boundaries before enabling
the persisted Hermes connection preference. Health does not prove live model quota.
Do not activate Zernio accounts, broad MCP tools, native plugins or sibling services.

If operator verification fails, stop only its two services and leave the normal CRM
available. If the application release fails, use the existing deployment gate's
previous healthy SHA; rollback does not reverse additive database migrations. Recheck
sibling container IDs and Nginx configuration hashes after all operations. Future
operator policy changes still need administrator review/install: CI never overwrites
root-owned policy or receives the provider credential.

The bridge pins its private peer IPs during startup. After replacing or rolling back
the API, the root-owned gate restarts only an already-running Hermes bridge so it
resolves the new API address. It never starts a stopped/uninstalled operator, restarts
the provider, or fails an otherwise healthy CRM because the optional refresh failed.

## Bootstrap / policy changes — administrator only

1. Create an empty public repository at the owner/repository path specified in
   `ops/deploy.py`; review the initial source before publishing.
2. Generate an exclusive Ed25519 CI key outside the checkout. Upload **only its public
   key** and the reviewed `ops/` directory over the authorized administrator SSH session.
3. Run `bash ops/provision.sh /path/to/ci-key.pub`. It creates only project resources:
   directories, a restricted user/key, one sudo rule, root-owned runtime files, and a
   project-specific backup timer. It does not install host packages or restart services.
4. Create GitHub environment `production`, restricted to `main`. Set environment secrets
   `VPS_HOST`, `VPS_DEPLOY_KEY`, `VPS_KNOWN_HOSTS`. Obtain the host public key through
   the already verified administrator session, **not** an unauthenticated `ssh-keyscan`.
5. Dispatch the workflow on `main`, observe all jobs, then verify the server's readiness
   and the pre-existing services. Confirm a real deployment before claiming CI/CD works.

Root-owned `compose.yaml`, gate and backup policy are **not** automatically overwritten
from the repository. Administrators review and install any changes explicitly. This
prevents the CI key from changing mounts, privilege flags or unrelated host paths.
Do not rerun provisioning with a different key without planning rotation and testing it.
The project's BuildKit worker uses its own cache and capped CPU/memory/PIDs; the gate
refuses builds when its actual resource policy is missing. Release extraction is staged
and atomically promoted, so failed extraction cannot poison the next retry.

Never run global Docker prune, `down --volumes` on the VPS, change the shared Nginx
configuration globally, restart Docker, or reuse another project's database/secrets.

## Preview vhost installation — authorized administrator only

The root-owned Nginx preview policy is intentionally separate from CI releases.
Templates are in `ops/nginx/`; CI must not install privileged host policy.

HTTPS response buffering uses `/var/lib/nginx/jardines-proxy`, not the shared
`/var/lib/nginx/proxy`. Before installing the HTTPS template, create this dedicated
directory with mode0700 and the actual Nginx worker's user/group (currently
`www-data:www-data`). Never recursively change ownership of the shared directory.
Keep normal bounded memory buffering and disk spill for slow clients; monitor
temporary disk usage. This policy applies only to the Jardines HTTPS server.

On 2026-11-11, the application returned all 643758 HTML bytes directly, but public
HTTPS stopped near 64 KiB. Project errors showed `Permission denied` when workers
running as `www-data` tried to spill responses into the shared directory owned by
`nobody` with mode0700. Running `nginx -t` also changed the shared base directory's
owner to `www-data`, temporarily restoring full responses before the policy edit.
The dedicated path removes this site's reliance on that shared ownership side
effect; do not present the validation side effect as an application-code fix.
Preserve a root-only project-vhost backup, validate `nginx -t`, then reload rather
than restart Nginx. Verify full GET bodies, not merely HEAD/health responses:
HTML length must match its declared length, and hero media bytes must match the
release assets. The web regression suite now checks this explicitly.

The repair passed all23 public web checks, including browser3D/mobile/fallback
cases and exact media bytes. A rate-limited128KiB/s download also delivered all
4118060 hero-video bytes; the original8586020-byte film remained intact.
The Python suite ran69 tests:68 passed and the opt-in pinned-Hermes fixture was
skipped. Eighteen sibling vhost content hashes and all29 container identities/start
times were unchanged. The root-only rollback checkpoint is
`/srv/jardines-del-encanto/proxy-fix-wdwb_fx3`.

1. Record sibling container IDs, vhost checksums and HTTP status baselines. Verify
   DNS resolves to the VPS and `nginx -t` passes before making changes.
2. Create `/var/www/jardines-acme/.well-known/acme-challenge`. Install only
   `jardines-preview-http.conf` as `/etc/nginx/sites-available/jardines-preview.conf`
   and link that exact file into `sites-enabled`. Do not overwrite an existing vhost.
3. Run `nginx -t`, then `systemctl reload nginx` (never restart it). Validate an
   HTTP-01 test file externally before requesting the certificate.
4. Use the installed Certbot webroot plugin, without its Nginx auto-editor:

   ```sh
   certbot certonly --webroot -w /var/www/jardines-acme \
     --cert-name jardines-preview -d jardines.2.24.111.40.sslip.io \
     --non-interactive --agree-tos --register-unsafely-without-email \
     --deploy-hook '/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx'
   ```

   Use a verified owner email instead of the no-email flag when one is supplied.
   Never invent an address. The existing `certbot.timer` must remain active; inspect
   the project certificate expiry and renewal hook without exposing account secrets.

5. Replace only this project's bootstrap vhost with `jardines-preview.conf`. Test
   with `nginx -t` before reloading. If the test fails, restore the previous project
   file and do not reload. Existing workers continue serving sibling projects.
6. Verify valid HTTPS, HTTP-to-HTTPS redirect, `/health/ready`, media/video/PDF and
   the expected release. Recheck sibling vhost checksums, containers and statuses.

To remove the preview, remove only its enabled symlink after confirming the path,
run `nginx -t`, then reload. Do not alter sibling vhosts, shared firewall/SSH settings
or application port bindings. Certificate removal requires a separate deliberate
cleanup; renewal failure must not trigger broad host changes.

## Zernio OAuth production activation — owner authorized

The owner explicitly authorized moving only the local Jardines Zernio grant to
this project's VPS on 2026-11-11. This is not a general credential-copy operation.
Keep `accounts:read`; do not reuse an MCP token as a REST API key or request new
write scopes. Accounts visible through this grant are observations, not proof of
project/profile ownership or permission to send/publish.

Before enabling the production flag:

1. Record the healthy release, sibling container IDs/start times and other vhost
   hashes; retain root-only copies of the project policy/gate/vhost and a logical
   backup. Do not use a negated Docker label filter as evidence of sibling state.
2. Install the reviewed project Nginx template. Its access log excludes query and
   referrer; exact `/crm` errors are discarded because upstream errors can contain
   OAuth query strings. Run `nginx -t`, reload (not restart), then verify synthetic
   callback markers do not enter access/error logs. Preserve other vhosts.
3. Install `ops/zernio/egress.py` root-owned0644 beneath the root-only directory
   `/srv/jardines-del-encanto/zernio-policy/`. Install the reviewed root-owned CRM
   Compose/gate. Start only the explicitly authorized `zernio-egress` service with
   the current API release image. It has no host ports, credentials or DB mounts;
   only this relay receives external networking. API remains on internal app/data.
4. Deploy the verified release through existing GitHub Actions. API's fixed
   `ZERNIO_HTTPS_PROXY=http://zernio-egress:8080` preserves TLS to the vendor.
   The gate refreshes a running relay onto the release image, never starts a relay
   intentionally left stopped, and keeps optional failures separate from CRM health.
5. Stream only allowlisted durable grant fields from the known local project API
   through the authorized encrypted SSH stdin into the production API container.
   `ops/zernio/migrate_grant.py` validates the bounded JSON, locks private storage,
   refuses an existing grant/pending authorization, and discards pending verifier,
   session/actor, observations and old verification. No plaintext token file, shell
   token argument, CI secret, log or terminal output is permitted. Do not run this
   importer through an application endpoint, Hermes or an arbitrary-code adapter.
6. Perform the exact read-only MCP probe. Verify channel counts/platforms without
   printing identities or tokens; verify the UI refresh and Hermes catalog reflect
   the effective state. Do not disconnect/reconnect WhatsApp or send test messages.

A moved refresh grant must not be refreshed concurrently from two environments.
Hold the source configuration lock and park its grant as needing authorization
BEFORE export, retaining the original only in the source process for a confirmed
pre-import refusal. A successful/uncertain import followed by a failed probe leaves
the source parked: the destination might already have rotated the refresh token.
Only successful destination verification retires the matching local grant. Never
restore an old source token after a possible destination refresh or remove a newer
replacement grant. Retain a failure as unverified and preserve recoverable state.
A vendor revocation requires fresh owner authorization, not fabricated connectivity.
Root-owned policies are not updated by CI; retain their checkpoint for rollback.

## Sara IA rollout — not activated by local implementation

The Sara IA source change does not authorize deployment, credential access, paid
transcription calls or changes to the shared VPS. Obtain a separately scoped
production authorization before running these steps. See [SARA-IA.md](SARA-IA.md)
and [SARA-RUNTIME.md](SARA-RUNTIME.md) for the protocol and verified local checks.

1. Back up the project database and record the release and sibling-service
   baseline. Deploy migration007 additively through the existing migrator; do not
   rewrite earlier migrations. Attachment bytes are private PostgreSQL bytea and
   belong in the same backup. Retain the forward schema when rolling application
   code back; do not drop conversation or attachment tables.
2. Review/install the new operator source and audio helper into this project's
   existing root-owned policy directory. Apply the reviewed operator Compose
   mounts and restart only its provider/bridge as authorized. Existing CI cannot
   replace these root-owned policies. Keep the legacy text-only profile intact.
3. Verify explicit `history_available=true` through the upgraded provider and
   bridge before accepting Sara chat traffic. An old runtime must leave Sara
   unavailable rather than silently losing conversation context. Confirm the
   installed pinned Hermes SDK accepts the bounded conversation-history shape.
4. Keep voice disabled by default. Only a separately authorized enablement sets
   `HERMES_TRANSCRIPTION_ENABLED=1` at the operator-provider. Keep credentials in
   that isolated boundary; never add provider keys to the API, Next.js, GitHub
   repository or browser. Test capability health without sending customer audio.
5. Verify private owner/session/CSRF enforcement, a text turn, history after
   relogin, file download isolation and session-bound approval behavior. Any real
   transcription test is a paid external data transfer requiring explicit scope.
   Recheck sibling services and the existing OAuth flow after deployment.

Text turns can outlive the current public proxy read timeout. Preserve request
UUIDs and recover the stored run after an ambiguous timeout; never retry with a
new UUID automatically. A future timeout adjustment is project-vhost-only and
requires its own reviewed configuration change. The existing1MiB proxy body cap
accommodates Sara's768KiB JSON upload limit. Reassess the fixed transcription
model before its documented February26,2027 deprecation; do not silently switch it.
