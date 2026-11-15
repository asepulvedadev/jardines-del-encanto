# Public domain and canonical CRM origin

Current origin: `https://jardinesdelencanto.site` (CRM cutover authorized and
completed November 15, 2026). The DNS/certificate setup below dates to November 11.

The owner authorized Hostinger DNS changes and project-only VPS configuration via
the existing administrator identity. The public landing is served at
`https://jardinesdelencanto.site`. HTTP and HTTPS `www` redirect to this apex.

## DNS and certificate

- Hostinger `A @`: changed from `2.57.91.91` to `2.24.111.40`.
- Apex TTL: changed from 50 to 60 seconds, the editor's minimum accepted value.
- Existing `CNAME www -> jardinesdelencanto.site`, TTL 300, retained unchanged.
- Nameservers remain `atlas.dns-parking.com` / `hyperion.dns-parking.com`.
- No other records, mail, DNSSEC, registration, renewal or privacy settings changed.
- The existing Certbot account issued `jardines-domain` for apex and `www` using
  the existing ACME webroot. Certificate expiry: 2027-02-09; `certbot.timer` active.
  Its renewal hook validates Nginx and reloads it without a restart.

Initial recursive NXDOMAIN answers outlived the new registration's TLD delegation.
Authoritative Hostinger and `.site` responses, then Cloudflare/Google recursive
answers, resolved the expected address before completion. Do not reset nameservers
or submit repeated certificate orders to work around a negative DNS cache.

## Current scope and security — November 15, 2026

The branded domain now serves `/login`, `/crm` and the existing Next API gateways.
Both web and API use the exact `CRM_ORIGIN=https://jardinesdelencanto.site`.
The root-owned Compose policy pins it explicitly for both services; the private API
runtime environment was changed on that line only. Future provisioning uses the
same origin. Do not rerun database provisioning for this cutover.

The original November 11 setup deliberately kept CRM on the preview hostname,
redirected branded private routes there, and adapted Origin for public capture.
That arrangement caused the owner's reported old-domain login behavior and is now
superseded. The current branded vhost performs **no Origin rewriting**. Existing
session authentication, strict Origin comparison, CSRF checks and API allowlists
remain authoritative. Public registration keeps its exact-origin guard and strips
Cookie, Authorization and X-CSRF-Token before forwarding. Unknown API routes still
fail in the application allowlist, not through direct backend exposure.

The legacy hostname redirects GET/HEAD documents, including login and CRM paths,
to the fixed branded HTTPS origin, preserving the path and query. Legacy private
API requests return 403; document POSTs return 405 rather than replaying passwords
across domains. The one existing signed Zernio webhook route remains proxied on
its old URL, with unchanged raw-body signature checks. No webhook registration,
provider tokens, OAuth grants, credentials, DNS or certificates were changed; no
database records were directly edited. New provider authorization flows derive their callback from the new
CRM origin; a flow already in progress at cutover may need to be started again.

Cookies remain Secure, HttpOnly and host-only, without a broad Domain attribute.
Users must sign in again on the branded domain; old-host cookies are not copied.
Private routes remain noindex. Query strings and referrers stay out of access logs;
upstream error logging is suppressed for the CRM callback documents on the branded
vhost. The app, API and database ports remain private.

The existing release `76811cdc800d3f8d1cbd33ef400378553e697aec` and its exact image
IDs were retained. Only `jardines-web-1` and `jardines-api-1` were recreated to apply
the origin; their readiness checks passed. Database and auxiliary project container
IDs remained unchanged. No build, pull, release activation, database migration or
pending local Plantillas feature was published. Nginx was validated before a reload,
not restarted. The operation held the existing project deployment lock.

## Current cutover recovery

Root-only checkpoint: `/srv/jardines-del-encanto/login-domain-bxqwbk6m` (mode 0700).
Its mode-0600 originals and manifest cover exactly:

- `/etc/nginx/sites-available/jardines-domain.conf`
- `/etc/nginx/sites-available/jardines-preview.conf`
- `/srv/jardines-del-encanto/crm.compose.yaml`
- `/srv/jardines-del-encanto/secrets/crm-runtime.env`

The runtime backup contains secrets and must remain on the host; never print or
export it. The manifest records original modes, hashes, release, Compose overlay
paths and before/after project container identities. Rollback must acquire the same
`deploy.lock`, confirm no newer release or independent policy change intervened,
restore these four files with their original modes, recreate **only web/API** using
the recorded image release and overlays (`--no-deps --no-build --pull never`), wait
for health, validate `nginx -t`, then reload Nginx. Do not use `compose down`, touch
volumes, reset sessions, rotate credentials or reverse database migrations.

Observed cutover checks: 5 local Nginx policy tests and 8 live HTTPS domain tests
passed; 224 local CRM gateway tests, 4 provisioning tests and the merged voice
isolation policy test passed. Live checks exercised canonical login
HTML, protected anonymous CRM/session, exact-Origin login rejection, public form
validation without lead creation, legacy safe redirects and rejected POSTs,
HTTP/www canonical redirects, unchanged release and byte-identical hero media.
The browser opened the **old login link** and visibly landed on the branded login
form without TLS exceptions. No real password was entered, no successful login or
provider reauthorization was attempted, and no lead was created. Actual signed-in
use remains for the owner to confirm with their existing credentials.

## Original November 11 recovery and verification (historical)

The remaining checkpoint notes describe the initial alias setup, not a current
rollback recipe. Use the November 15 checkpoint above for the CRM cutover.

Root-only checkpoint: `/srv/jardines-del-encanto/domain-setup-3ogg0w8d`, containing
the before manifest, prior DNS values, bootstrap and final HTTPS policies. A first
staging-script attempt failed before installing any vhost; the corrected attempt
created this checkpoint and completed normal validation/reload.

Only `/etc/nginx/sites-available/jardines-domain.conf` and its matching enabled
symlink were added. Existing vhost content hashes and all container identities
remained unchanged. One existing Jardines Hermes bridge transitioned from never
started to started during setup; no Docker mutation was issued by this domain
operation. Sibling container start metadata was unchanged. The existing application
release `4d78857eefd40866b572edd2714a4ab753ea1848` was retained.

Before any future policy edit, preserve the current project vhost; validate
`nginx -t` before reload and restore that project file on validation failure.
Do not modify shared Nginx files, sibling vhosts, Docker, firewall, or CRM secrets.
DNS reversal restores only the apex A value from the manifest, using a valid TTL;
do not reset the whole zone. Keep the working certificate and preview available.

Run current non-mutating acceptance checks against the canonical policy:

```sh
python3 -m unittest discover -s tests -p test_nginx_policy.py -v
DOMAIN_BASE_URL=https://jardinesdelencanto.site \
  DOMAIN_EXPECTED_RELEASE=76811cdc800d3f8d1cbd33ef400378553e697aec \
  node --test tests/domain.test.mjs
LANDING_BASE_URL=https://jardinesdelencanto.site npm run test:web
```

The original domain checks covered valid TLS, canonical redirects, complete HTML/media bytes,
strict Origin rejection, then-unchanged preview behavior, private-API separation and
public form validation. They deliberately use invalid form data and create no
registration. Browser web checks separately exercise the shared modal and hero on
desktop/mobile. Physical devices and all ISP caches are not certified.

Original November 11 acceptance: 2/2 policy tests, 6/6 public-domain tests and 25/25
browser-enabled web tests passed. No valid registration was submitted. Chromium
and HTTPS clients loaded the branded domain without certificate exceptions.
