# Private landing analytics

Status: implementation prepared locally. **The VPS analytics service is not installed or
activated by this change. No production visits have been collected.** Publishing the
application alone does not activate the separate analytics stack or installed policy.

## Data contract and boundaries

The CRM dashboard reads aggregates from a separately hosted Umami 3.5.0 service.
The application collector is the only public collection interface; do not publish the
Umami UI, raw API, PostgreSQL port, API key, or administrator credentials.

- Record approved public-page views and named CTA interactions only. Never collect CRM,
  login, preview, health, authenticated operator activity, form contents, names, phone
  numbers, chat, audio, exact user identifiers, DOM recordings or session replays.
- Strip arbitrary URL queries, fragments and campaigns. Accept only normalized source
  categories; do not forward arbitrary UTM/campaign strings or full referrer URLs.
- Raw visitor IPs are not retained by the application analytics collector; Umami uses
  its normal privacy-preserving visitor/session estimation. Do not add identify calls.
- Visitors are estimates, not exact people. A WhatsApp click is not a sent message.
  The CRM registration figure comes from distinct registered CRM clients in the selected
  period, not from successful click events. It is not person-level attribution.
- Umami replay and heatmap capture are explicitly disabled on the website at bootstrap.
  Do not add the generic Umami script to the CRM or enable session recording.
- Ordinary application security/access logs are a separate operational concern; do not
  describe this integration as disabling all server logs.

## Architecture and isolation

`ops/analytics/compose.yaml` is **source policy**, not an automatically executable release
attachment. The fixed Compose project is `jardines-analytics`. The pinned Umami image
joins the already installed external `jardines_app` network, and a new internal
`analytics_data` network. Its `analytics-db` is PostgreSQL 17 with its own named volume,
`jardines_analytics` database and database role; it never uses the CRM database.

Both services run non-root, with read-only root filesystems, dropped capabilities,
no-new-privileges, bounded writable tmpfs, memory/CPU/process caps and bounded logs.
Neither service publishes a port. An explicit maintenance override publishes only
`127.0.0.1:14320`, never `0.0.0.0`. Its separate temporary `maintenance` bridge
is non-internal and joins only Umami: Docker does not publish a host port when every
attached network is internal. PostgreSQL stays only on `analytics_data`; the existing
`jardines_app` policy remains unchanged. Remove the maintenance bridge after setup.
Ordinary app traffic stays on the private Docker network.

The image digest is fixed to the reviewed Umami 3.5.0 release. PostgreSQL uses the same
pinned 17-alpine digest already used by this project, with a separate service and volume.
`COLLECT_API_ENDPOINT` must remain unset: upstream startup otherwise rewrites a file in
`public/`, incompatible with a read-only root filesystem. This integration does not need
that generic tracker rewrite. Telemetry and Next telemetry are disabled.

### Credentials and environment

Use a dedicated directory outside Git and release trees, owned by the operating user
and mode **0700**; every file inside must be mode **0600**. The setup helper rejects
unsafe modes, symlinks and unexpected preexisting files rather than changing them.
No actual credentials or generated environment files belong in this repository.

| Private file | Consumer | Contents |
| --- | --- | --- |
| `db_password` | operator checkpoint | Original random dedicated database password |
| `db.env` | analytics PostgreSQL | Same `POSTGRES_PASSWORD`, read by Docker from the owner-only file |
| `server.env` | Umami only | Dedicated `DATABASE_URL`, random `APP_SECRET`, 64-hex `TWO_FACTOR_ENCRYPTION_KEY` |
| `collector.env` | Next.js server only | `UMAMI_ENABLED=1`, `UMAMI_BASE_URL=http://umami:3000`, `UMAMI_WEBSITE_ID=<generated UUID>`, `UMAMI_TRUST_PROXY=1` |
| `client.env` | Python API only | Same configuration plus `UMAMI_API_KEY=<reader bearer key>` |
| `state.json` | operator helper only | Versioned setup checkpoint, entity IDs, passwords and key; never mount into web/API |
| `.setup.lock` | operator helper only | Local advisory lock, not an application credential |

The PostgreSQL password uses an owner-only `env_file`, read by Docker itself. A bind-mounted
0600 file owned by the host operator is not readable by container UID 70; never fix this
by making secrets world-readable. Preparation can reconstruct a missing `db.env` from
the same existing private `db_password`, without rotating credentials or touching data.

No `NEXT_PUBLIC_` secret exists. `UMAMI_TRUST_PROXY=1` is valid only when the existing
trusted ingress overwrites client-IP headers; preserve that ingress boundary. Do not
forward an arbitrary browser-supplied IP. Inspect the collector's current implementation
and the installed ingress policy before activation.

The native long-lived API key belongs to a global `view-only` service account, which is
only `team-view-only` in an **admin-owned team**. The website belongs to that team.
A personal-owned website is not sufficient: upstream 3.5.0 allows personal owners to
update/delete their website without checking the global view-only permission. The helper
verifies the reader key can GET this website and receives 401/403 on a no-op POST update
before writing the key into `client.env`. No admin key is mounted into the CRM.

## Local disposable verification

These commands create a new local analytics instance, not production. Obtain authorization
before any remote installation or transfer. Run from the checked-out repository.

```sh
umask 077
SCRATCH=$(mktemp -d /tmp/jardines-analytics.XXXXXX)
export ANALYTICS_SECRETS_DIR="$SCRATCH/secrets"
python3 ops/analytics/bootstrap.py prepare --fresh-instance \
  --secrets-dir "$ANALYTICS_SECRETS_DIR"
docker compose -f ops/analytics/compose.yaml -f ops/analytics/local.compose.yaml \
  config --quiet
docker compose -f ops/analytics/compose.yaml -f ops/analytics/local.compose.yaml \
  up -d --wait --wait-timeout 180
python3 ops/analytics/bootstrap.py bootstrap --fresh-instance \
  --secrets-dir "$ANALYTICS_SECRETS_DIR" --base-url http://127.0.0.1:14320
```

`local.compose.yaml` replaces the external network with `jardines-analytics-local_app`
and names the project `jardines-analytics-local`. That new local-only bridge is
non-internal so Docker can publish the loopback test port; it is not the production
application network. It does not join or restart any
existing CRM, analytics or unrelated application container. Port 14320 must be free;
do not stop another service to claim it. The helper bypasses ambient HTTP proxies,
refuses redirects and only accepts the explicit `http://127.0.0.1:14320` destination.
It does not inspect SSH agents, remote hosts or browser sessions.

For local application verification, load `collector.env` into the local Next server
and `client.env` into the local Python API, replacing `http://umami:3000` with the explicit
local loopback endpoint for processes outside Docker. Keep those overrides in ignored
local files; do not change production source defaults. Use synthetic traffic and an
empty CRM fixture. Never submit actual clients, credentials or phone numbers.

When the owner no longer needs this disposable instance, stop it with the same two
Compose files. `down` preserves the volume. Removing its named volume is destructive:
confirm the exact `jardines-analytics-local` project and obtain consent before using
`down --volumes`. Keep private checkpoint paths available until the run is complete.

## Authorized VPS installation and rollout (not executed)

1. Back up the existing CRM independently and capture the installed root-owned deployment
   policy and running container identities without exposing secrets. Verify capacity and
   the existing `jardines_app` network. Do not modify sibling applications.
2. An authorized root operator installs the reviewed analytics files to a separate
   root-owned policy directory, for example `/srv/jardines-del-encanto/analytics-policy/`.
   Create `/srv/jardines-del-encanto/secrets/analytics` privately. Run `prepare` there
   using the explicit `--fresh-instance` flag **only for a new analytics database**.
3. Export `ANALYTICS_SECRETS_DIR` pointing to that private directory. Validate the
   installed base Compose file with `config --quiet` (never dump resolved secrets).
   Start only that new stack using the installed base plus `admin.compose.yaml`,
   then run `bootstrap` against the explicit loopback endpoint. It rotates the default
   admin password before creating the reader, team, website and bearer key.
4. Inspect setup success using counts/status only. Confirm GET access works and write
   access is denied for the reader. Enable administrator 2FA through the loopback-only
   UI if desired; its encryption key is already provisioned. Keep this administrative
   access separate from CRM users. Remove the maintenance override from the analytics
   runtime after setup; recreate only Umami to remove the loopback port mapping and
   temporary maintenance-network attachment. Do not change the existing application
   network or restart PostgreSQL to make maintenance access work.
5. Install the reviewed `client.compose.yaml` as a **root-owned CRM policy overlay**.
   Preserve the existing `crm-runtime.env` alongside the new analytics client file.
   Explicitly update the installed root-owned deployment invocation to include this
   overlay and `ANALYTICS_SECRETS_DIR`. The project release gate uses installed policy,
   **not arbitrary source Compose files from the release**. This change intentionally
   does not modify `ops/deploy.py`, its installed counterpart, or any deployment gate.
6. Deploy the application using the established Jardines release gate. Restart/recreate
   only the web and API services that need the new environment. Verify public collection
   is allowed only on approved pages, private pages never collect, the authenticated CRM
   shows live aggregates and failures show unavailable status rather than fabricated zero.
7. Check one synthetic page view and CTA through the public collector, then the CRM
   dashboard and reader API. Verify no form values, phone numbers, full query strings,
   arbitrary campaign names, raw client identifiers or message contents reached Umami.
   Record the rollout timestamp: historical visits cannot be reconstructed.

There is no automatic VPS activation, account creation or database initialization on
an application commit. The installation/installed-policy update is a separate explicitly
authorized operational action. Never attach the existing CRM database volume here.

### Pause and failure handling

Set `UMAMI_ENABLED=0` in **both** private `collector.env` and `client.env` and recreate
only their web/API consumers through the installed policy. This stops collection and
marks analytics unavailable without deleting metrics. Stopping the analytics stack
also preserves its volume. Do not replace the Umami database or key to fix an HTTP error.

The helper is fresh-instance setup only. A completed checkpoint is a no-op on rerun.
Before each mutating API operation it records `pending`, and does not replay an uncertain
operation after failure, timeout or lost response. Never delete `state.json` to retry.

For an uncertain checkpoint, an authorized operator uses the private generated admin
password to inspect the isolated Umami instance through the loopback UI/API, then
reconciles **that same** checkpoint:

- `password`: try the generated password first. If it works, mark the step done and
  clear `pending`; do not attempt another default-password rotation.
- `reader`: inspect the predetermined `reader_id` and verify the exact username and
  `view-only` role before marking done. Do not create another account.
- `team`: inspect the one exact team `Jardines landing analytics`, owned by the admin;
  put its ID into `team_id` and mark done. The create endpoint returns the transaction
  array `[Team, TeamUser]`, not a single object; the helper checks both entries and the
  owner role before advancing. If no team exists, only after confirming
  absence may the operator clear pending to permit that single creation.
- `membership`, `website`, `privacy`: inspect the exact checkpoint IDs, team membership,
  domain and disabled replay settings. Mark done only if the requested state is present;
  otherwise establish absence/failure before explicitly permitting a retry.
- `key`: plaintext is returned once. If the key is absent from `state.json`, revoke the
  exact `Jardines CRM aggregate reader` key in the reader account, verify revocation,
  then clear pending to create one replacement. Never leave an orphaned active key.

Manual checkpoint reconciliation is sensitive administration: preserve mode 0600,
make a private backup first, do not put passwords in shell argv/history/logs, and never
copy an administrator bearer token to `client.env`. Concurrent helper runs are refused
by a private nonblocking advisory lock. Incomplete preparation also stops; restore the
original private files rather than generating a new database password over existing data.

## Backup, restore and retention

Back up analytics separately from CRM. With the installed analytics Compose policy,
run `exec -T analytics-db pg_dump -U jardines_analytics -d jardines_analytics -Fc` into
an owner-only backup file, and capture exit status before accepting the artifact. Encrypt
and restrict the backup destination. Separately back up all private environment/checkpoint
files, especially `APP_SECRET`, 2FA encryption key and API key; do not include them in
public release archives. Never print the resolved Compose configuration to logs.

Test restore into a **new isolated analytics database/volume**, not the active volume and
not the CRM database. Stop writes, take a fresh backup, restore with `pg_restore` using
the matching pinned PostgreSQL tools and isolated analytics credentials, then validate
website IDs, reader permissions and aggregates. A restore can resurrect a revoked API
key: re-verify keys and 2FA configuration before enabling collector/client consumers.
Do not run `down --volumes` or overwrite an active database as a recovery shortcut.

There is no automatic data-deletion timer in this change. Agree the retention period
with the owner before production activation; a suggested operational review interval is
90 days, not an implemented expiry promise. For cleanup, back up first, review Umami's
current deletion/reset tools on the isolated restore, and obtain explicit authorization
for the exact website/date scope. Do not run raw guessed cascade SQL or delete the
shared PostgreSQL volume. Deleting a website or resetting analytics is irreversible
without a verified backup and may invalidate the configured website ID.

## Verification and upstream contracts

Offline: `python3 -m unittest discover -s tests -p test_analytics_ops.py -v` covers private
file modes, stable setup, uncertain-key replay refusal, readonly account wiring,
loopback destination validation and isolated/pinned Compose policy. Compose configuration
validation and a real local-image startup remain separate runtime checks; unit tests do
not prove deployment or historical data collection.

Verified against official v3.5.0 source on 2026-11-16:

- [Native API keys](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/me/api-keys/route.ts)
  and [key enablement and blocked management routes](https://github.com/umami-software/umami/blob/v3.5.0/src/lib/api-key.ts).
- [Password rotation](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/me/password/route.ts)
  and [login](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/auth/login/route.ts).
- [User creation](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/users/route.ts),
  [team creation](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/teams/route.ts)
  and [team membership](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/teams/%5BteamId%5D/users/route.ts).
- [Website creation](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/websites/route.ts),
  [permission checks](https://github.com/umami-software/umami/blob/v3.5.0/src/permissions/website.ts)
  and [replay input schema](https://github.com/umami-software/umami/blob/v3.5.0/src/app/api/websites/request-schema.ts).
- [Read-only startup considerations](https://github.com/umami-software/umami/blob/v3.5.0/scripts/update-tracker.js)
  and [2FA key format](https://github.com/umami-software/umami/blob/v3.5.0/src/lib/two-factor/crypto.ts).

The bootstrap contract also follows the direct Prisma query responses: `createTeam`
returns `[Team, TeamUser]`, membership creation returns a single `TeamUser`, website
creation/update return a website object, and API-key creation returns metadata plus the
one-time plaintext `key`. Unexpected team/key shapes stop with the pending checkpoint
preserved; CLI errors suppress Python tracebacks and raw response bodies.

- [Team transaction response](https://github.com/umami-software/umami/blob/v3.5.0/src/queries/prisma/team.ts).
- [Membership response](https://github.com/umami-software/umami/blob/v3.5.0/src/queries/prisma/teamUser.ts).
- [API-key metadata response](https://github.com/umami-software/umami/blob/v3.5.0/src/queries/prisma/apiKey.ts).

### Observed local verification — 2026-11-16

A disposable pinned Umami 3.5.0 and PostgreSQL17 stack started healthy with this policy.
The fresh-instance bootstrap rotated the default administrator password, created the
team-owned website and restricted reporting account, and verified that its API key
could read but not update the website. The real startup exposed two operational issues
that are now covered by regression tests: owner-only mounted secrets were unreadable
by PostgreSQL UID 70 (use Docker-read `db.env`), and Docker did not publish the loopback
port while all attached networks were internal (use the separate maintenance bridge).
The actual team-creation transaction-array response is also pinned by regression tests;
a confirmed existing team was reconciled without repeating its creation.

Synthetic local page views and CTA clicks passed through the application's same-origin
collector into real Umami, then returned through the shared dashboard/Sara reporting
service for 1, 7 and 30 days. The registration SQL boundary used an isolated empty fixture;
no real customer database, external ad account or production statistics were used.
This proves the collector/provider adapter contract, not production collection or
historical traffic. Live production activation remains pending.
