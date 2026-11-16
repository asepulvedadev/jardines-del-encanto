# Sara private image concepts

Sara queues one private PNG concept per request. This is local implementation, not a
claim of deployment, provider account eligibility, actual generation or visual fidelity.

## Fixed contract

- `images.catalog` returns five versioned approved originals: white and transparent
  logo PNGs, plus aerial, entrance and gate WebP photographs. The poster is not a logo.
- `images.generate`: `request_id` UUID, `prompt` (1–2000 characters), `reference_ids`
  (0–3 unique catalog IDs), `size` (`1024x1024`, `1536x1024`, `1024x1536`).
- The backend fixes `gpt-image-2.5-flare`, one image, low quality and PNG output.
  No caller-supplied models, URLs, paths, uploaded files or output destinations.
- Daily cap: five jobs per owner in a rolling 24-hour window. Reusing an owner's
  request UUID with the same arguments returns the receipt; changed arguments conflict.
- Brand instructions preserve supplied logo geometry and colors, forest `#062619`
  and leaf `#507010`. Generated images are concepts, never property evidence or proof
  of facts. Prompt instructions cannot guarantee pixel-perfect logos; human review
  remains necessary before publication. No automatic publishing or public hosting.

## API and worker integration

Register `app.images.routes.router`. Its `/crm/images` routes are session-protected;
POST additionally inherits origin and CSRF enforcement from `security.session`.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/crm/images/catalog` | Approved asset metadata and generation limits |
| GET | `/crm/images/assets/{asset_id}/content` | Approved original bytes, fixed IDs only |
| POST | `/crm/images` | Queue a concept, HTTP 202 |
| GET | `/crm/images/{uuid}` | Owner-scoped status and receipt |
| GET | `/crm/images/{uuid}/content` | Owner-scoped completed PNG bytes |

Mount only exact corresponding web gateway routes. Web receipts use
`/api/crm/images/{uuid}/content`; bytes remain authenticated with private/no-store
responses. `SaraImageResult` polls queued/processing receipts at bounded intervals,
then fetches and previews bounded same-origin image bytes through an object URL.
Stopping polling never changes the persisted job state or submits another generation.

Apply `014_sara_images.sql` explicitly with the existing migration runner, not startup.
Its user FK cascades and its private application-role grants follow the CRM boundary.
Start/stop `app.images.worker` with application lifespan and explicitly set
`CRM_IMAGES_WORKER_ENABLED=1`. Web enqueue is an explicit authenticated human action;
agent dispatch must separately enforce its caller role and current image capability.

The worker commits a unique `processing` claim before calling the bridge once. It
holds no database transaction across model I/O. Claims abandoned for 180 seconds
become terminal `unknown`; provider/transport uncertainty also becomes `unknown`.
Neither worker startup nor polling replays processing, unknown, failed or completed
jobs. Queue claims recheck enabled owner, Hermes connection and reference hashes.

## Private provider boundary

Slow image I/O uses two dedicated processes and never the synchronous text
`hermes-bridge` / `operator-provider` servers. Their tools, SDK registries, signal
handlers, paths and networks retain their previous behavior; there is no global
`ThreadingHTTPServer` conversion.

| Service | Role | Exact endpoints | Networks | Secret |
| --- | --- | --- | --- | --- |
| `image-bridge:8082` | `IMAGE_ROLE=bridge` | GET `/health`, POST `/generate-image` | application + internal images | None |
| `image-provider:8083` | `IMAGE_ROLE=provider` | GET `/health`, POST `/images/generate` | internal images + egress | Existing OpenAI key |

Both run the existing digest-pinned Hermes Python image, non-root, read-only, with
all capabilities dropped, no new privileges, bounded memory/CPU/PIDs and no host
ports. The image bridge has no provider module, secret or egress-network mount.
The provider has no application-network membership. No new credential is created:
the existing private proxy/network boundary is preserved. Only the image-provider
imports the image generator and receives the approved originals in a read-only bind
with `create_host_path:false`. Existing text services no longer mount image policy
or brand assets and reject the former image endpoints.

The application helper `app.images.bridge.generate(payload)` selects only
`HERMES_IMAGE_BRIDGE_URL`, defaulting to `http://image-bridge:8082`. The only other
accepted value is a canonical HTTP loopback host and explicit port for offline
fixtures. Paths, userinfo, query strings, fragments, alternate service ports,
external URLs and fallback to `HERMES_BRIDGE_URL` are denied. The private bridge
resolves/pins its fixed image-provider endpoint at startup; neither hop follows
redirects, ambient proxies or caller-supplied destinations.

The dedicated frame permits 4 MiB of request JSON and 12 MiB of response JSON;
PNG output is limited to 8 MiB. Only `{prompt, reference_images, size}` is forwarded.
Each reference is `{id, mime_type, data_base64}`. `operator_images.validate_request`
rechecks the original ID, MIME type and SHA256 against the mounted manifest before
creating the fixed upstream request. `operator_images.generate` performs at most
one HTTPS call and returns only `{ok:true, data_base64, mime_type:'image/png'}` or a
sanitized failure. Vendor error text is never forwarded.

Header parsing and body reads have five-second budgets. Main-thread signal
budgets cover 100 seconds in image-provider and 105 seconds in image-bridge;
the generator keeps its own 90-second upstream bound. Independent watchdogs force
process exit at the total budget plus one second if a nested vendor signal timer
would extend it. Compose may restart that image process; the durable job remains
unknown and is never automatically regenerated. The API bridge allows 110 seconds.
These are process-level image limits, not new timeouts or threads in chat services.
Both health endpoints report local role/liveness only: they never read a secret,
check account model access or contact OpenAI. Health checks may wait while their
own image process is busy; text health and replies remain independent.

### Activation prerequisites

1. Copy the reviewed `image_server.py` and `operator_images.py` policy files to the
   dedicated project runtime directory with their existing protocol/audio helpers.
2. Copy `apps/api/app/images/brand` unchanged to the root-owned approved brand
   directory, or explicitly set `HERMES_BRAND_ASSETS_DIR` to that directory.
   A missing bind source fails closed; no empty directory is auto-created.
3. Validate `ops/hermes/operator.compose.yaml`, preserve the existing OpenAI secret
   path and application network, then explicitly activate/recreate this project's
   image-provider and image-bridge services alongside the unchanged chat services.
4. Use the API default image endpoint or explicitly configure
   `HERMES_IMAGE_BRIDGE_URL=http://image-bridge:8082`; enable the image worker only
   after the reviewed services and original assets are present. Applying the schema,
   production activation, actual paid generation and owner PNG retrieval remain
   separately authorized deployment checks, not inferred from local tests.

Upstream uses `POST https://api.openai.com/v1/images/edits` with JSON
`images:[{image_url:'data:…;base64,…'}]` when references exist, otherwise
`/v1/images/generations`. There are no follow-up URL downloads. The provider and API
verify PNG signature, chunk checksums/structure, requested dimensions and the 8-MiB
output limit; the image transport additionally checks signature, dimensions and size. This is bounded structural validation, not a full image decoder.

Official OpenAI documentation fetched on 2026-11-15:
[image edits](https://developers.openai.com/api/reference/resources/images/methods/edit),
[image generation guide](https://developers.openai.com/api/docs/guides/image-generation).

## Verification

Deterministic tests use fixture PNGs and mocked network/transactions; no real OpenAI
request, charge, secret read or remote deployment is authorized by these tests.

```sh
apps/api/.venv/bin/python -m pytest tests/test_image_isolation.py tests/test_sara_transport.py tests/test_hermes_images.py -q
apps/api/.venv/bin/python -m pytest apps/api/tests/test_sara_images.py -q -k 'not database'
HERMES_OPENAI_SECRET_FILE=/tmp/not-a-real-secret docker compose -f ops/hermes/operator.compose.yaml config --quiet
```

The isolation regression runs real image-provider and image-bridge HTTPServers in
separate loopback child processes, keeping SIGALRM on each main thread. While a fake
image generation is blocked, the existing text provider still answers actual health
and valid text POST requests. A separate signal-deadline test bounds a slow fake;
no deadline guards are disabled to make threaded fixtures pass. Compose checks use
a nonexistent dummy secret pathname and do not read actual keys or start containers.

Real PostgreSQL checks must use the guarded isolated test harness and run serially
with other CRM fixtures, which reset users with cascading truncation. Visual/browser
review and paid generation are separate verification steps, not inferred from mocks.

## Compose verification portability

The brand bind mount keeps an explicit `create_host_path: false` in the authored
policy. Some Compose versions omit false boolean values in normalized JSON; the
isolation regression checks both the explicit policy and normalized false/omitted
representations, while still rejecting `true`. This does not change runtime policy.
