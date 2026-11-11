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
