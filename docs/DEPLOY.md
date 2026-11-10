# Quick deployment and recovery

## Normal deployment

Push reviewed changes to `main`. The `Verify and deploy` workflow runs tests and a
complete Docker smoke test, then sends `deploy <commit-SHA>` through a constrained
SSH key. The host fetches that public repository, verifies the current main tip,
builds the two images and checks the database/API/web readiness chain.

No runner is installed on the VPS. The personal administrator key is not uploaded to
GitHub. Only the dedicated CI private key is stored in the production environment.

## Preview before a domain is chosen

Use the owner's explicitly authorized administrator SSH identity:

```sh
ssh -F /dev/null -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o StrictHostKeyChecking=yes -L 13400:127.0.0.1:13400 root@VPS_HOST
# In a browser on the same computer: http://localhost:13400
```

Production intentionally has no public vhost yet. Do not open port 13400 to the internet.

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
No schema migrations are installed in this foundation.

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
taken before deployments when a current release exists. No backup is automatically
deleted. Monitor disk usage; define retention and encrypted off-host storage before
collecting real customer data. A backup is not a verified restore until tested.

Restore into a **new isolated database**, never directly into live production:
verify its checksum and `gzip -t`, create an empty recovery DB, stream the SQL through
`psql -v ON_ERROR_STOP=1`, inspect its contents and only then plan a controlled switch.
Production restoration is destructive and needs separate explicit authorization.

## Hermes (installed, not activated)

```sh
docker compose -f /srv/jardines-del-encanto/hermes.compose.yaml run --rm hermes --version
```

The pinned upstream image and state mount are project-specific. Networking is disabled;
there is no exposed port, Docker socket, host workspace mount or borrowed provider key.
Selecting an AI provider, adding credentials, enabling egress and configuring the CRM
tool API is a later authorized step. The image is not a functioning sales assistant yet.

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
