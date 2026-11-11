# Public domain setup — 2026-11-11

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

## Scope and security

`ops/nginx/jardines-domain-http.conf` is the HTTP-only bootstrap. The installed
`ops/nginx/jardines-domain.conf` is a separate root-owned vhost with its own logs.
It reuses only the project's existing loopback application and proxy temp directory.
Logs exclude query strings and referrers. The preview vhost remains untouched.
The initial domain setup kept indexing disabled. The owner's subsequent SEO/GEO
authorization enables only approved public pages; see `SEO-GEO.md` for the
default-noindex Nginx allowlist and application metadata policy.

The app's current CRM origin and provider callbacks remain on the existing preview.
`/crm`, `/crm/…` and `/login` redirect there; private `/api/…` paths return 404 on
the public alias. Migrating CRM authentication or provider redirect URIs is separate
work, not an implicit consequence of serving the landing on a branded hostname.

Only exact `/api/landing/registrations` adapts the Origin header. Nginx first
requires the exact incoming `https://jardinesdelencanto.site` Origin, then supplies
the existing trusted origin to the unchanged Next public gateway. Missing, null,
foreign, preview-origin and suffix-spoofed origins are rejected before forwarding.
Cookie, authorization and CSRF headers are removed on this public route. No
global origin rewrite, wildcard acceptance, application environment change or
private-API origin expansion was introduced. Gateway JSON, size, consent,
validation, throttling and response sanitization remain unchanged.

This edge adapter avoids an application rollout or disrupting existing CRM/Sara/
provider sessions. It deliberately depends on the fixed current CRM origin; a
future CRM-origin migration must update and reverify this explicit mapping.

## Recovery and verification

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

Run explicit non-mutating acceptance checks:

```sh
python3 -m unittest discover -s tests -p test_nginx_policy.py -v
DOMAIN_BASE_URL=https://jardinesdelencanto.site \
  DOMAIN_EXPECTED_RELEASE=4d78857eefd40866b572edd2714a4ab753ea1848 \
  node --test tests/domain.test.mjs
LANDING_BASE_URL=https://jardinesdelencanto.site npm run test:web
```

The domain checks cover valid TLS, canonical redirects, complete HTML/media bytes,
strict Origin rejection, unchanged preview behavior, private-API separation and
public form validation. They deliberately use invalid form data and create no
registration. Browser web checks separately exercise the shared modal and hero on
desktop/mobile. Physical devices and all ISP caches are not certified.

Observed acceptance: 2/2 policy tests, 6/6 explicit public-domain tests and25/25
browser-enabled web tests passed. No valid registration was submitted. Chromium
and HTTPS clients loaded the branded domain without certificate exceptions.
