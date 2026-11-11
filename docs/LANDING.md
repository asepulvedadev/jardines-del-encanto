# Landing page: content and local verification

The public landing is implemented in `apps/web`. The owner authorized publication,
VPS deployment and a temporary HTTPS preview on 2026-11-10. The later branded-domain
SEO authorization enables only approved public pages; see `SEO-GEO.md`. Deployment
and preview operations are documented in `DEPLOY.md`.
`DESIGN.md` remains the shared visual contract. UI copy uses professional `es-CO`.

## Verified local redesign — 2026-11-11

The current owner request moves the architectural video into the hero, uses heavier
self-hosted Plus Jakarta Sans on the public landing only, adds a launch-price header
and transparent repeating 24-hour clock, strengthens WhatsApp calls to action,
recomposes the real-photo gallery and adds reduced-motion-aware entrance/reveal
feedback. The CRM retains Manrope and its existing behavior.

The clock uses one shared midnight-to-midnight Colombia cycle, without visitor
identifiers or localStorage. The owner requested removing the explanatory paragraph;
the daily-cycle label and the location/sales eyebrow above the hero were also
removed in a later annotated request. The timer retains its accessible name,
without a price-expiration or stock deadline claim. All “Quiero mi cupo” buttons
open the same registration modal described below; other explicitly named contact
links continue to open WhatsApp.
Neither path reserves property or charges the visitor.

The Montecarlo reference was inspected locally for the promotion cycle and native
SVG interactions. Its 48-hour cycle is not copied: Jardines uses the requested 24
hours. The block/lot SVG explorer is reconstructed from this project's actual
CAD/PDF vector data; no Montecarlo lot geometry, statuses or property claims are reused.
The original PDF stays as a source asset, not the public interface's download action.
All 1,568 source lot occurrences have independent SVG contours across 55 parsed
block identifiers. Printed measurements and source anomalies are retained; this is
not live inventory or a new survey. See `MASTERPLAN.md` for extraction evidence.

Plus Jakarta Sans comes from Google Fonts' `ofl/plusjakartasans` distribution, with
its SIL OFL license alongside the font (trailing whitespace normalized). No runtime font CDN was added.

The owner subsequently authorized production deployment on 2026-11-11. Publication
uses the existing main-branch CI/deployment gate described in `DEPLOY.md`. A local
preview or successful push alone is not evidence of a healthy production release.

## Optional cinematic / 3D hero — 2026-11-11

The owner approved the “Del plano al lugar” concept for local implementation and
preview. This change does not publish or deploy anything. `HeroExperience` replaces
the old hero-only player; the full architectural film remains available elsewhere.
The subsequent owner revision removes decorative headings, slogans, duplicate
explore actions and instructions from both media views. Keep only view/player/3D
controls over the media, with the factual illustrative-media notice outside it.
On mobile/stacked layouts the media comes first, followed by the headline, offer
and contact actions; desktop retains copy left and media right. The media is a
single instance, first in document order, positioned with named grid areas.

- The initial view uses `hero-loop.mp4`: an approximately sixteen-second edit.
  It retains the entrance/lot views at source seconds 5.8–15.8 and appends the
  ecological paths and children's park at seconds 30–36.5. A 0.6-second crossfade
  joins the excerpts; a 0.8-second crossfade back to source seconds 5–5.8 closes
  the loop. Source footage and its baked-in annotations remain illustrative,
  with no new UI text overlays. The edit is
  re-encoded as silent 848 × 478 H.264 at 24 fps with fast-start metadata. It is
  approximately 4.1 MB, versus the original film's approximately 8.6 MB.
- `hero-poster.webp` is the frame at source second 5.8, not a generated image.
  Native poster behavior and explicit play/pause controls preserve a static view.
- Desktop playback respects reduced motion, data-saving signals and document
  visibility, and pauses outside the viewport. Mobile starts only on request.
  A deliberate pause or view switch can interrupt a pending `play()` promise;
  its `AbortError` is not a broken-media state and must not disable playback.
- “Maqueta 3D” loads Three.js and the scene on demand. No
  renderer, WebGL context or 3D render loop is started in the initial film view.
- The scene uses existing PDF-derived block paths from `masterplan-data.json`.
  Its shallow depth and rectangular display plinth are conceptual presentation,
  not measured heights, terrain, a parcel boundary or real-time availability.
  No source lot identifiers, anomalies, coordinates or measurements are changed.
- Mouse/touch rotation, keyboard arrows, zoom buttons, Home/reset and a native
  block selector offer complementary navigation. Wheel scrolling and pinch zoom
  remain available to the page. Frames are rendered only on interaction, resize
  or a bounded camera transition. Geometry, shadow targets, controls, observers
  and the WebGL context are released when leaving the 3D view.
- Unsupported/lost WebGL shows the original plan preview and a link to the
  existing accessible 2D explorer. Video failure retains the poster and 3D/2D paths.

Run the HTTP and source-regression suite against a local preview:

```sh
npm run dev --workspace=apps/web -- --hostname 127.0.0.1 --port 4317
# In a second terminal:
npm run test:web
```

The opt-in browser checks use an existing Playwright installation; set
`HERO_PLAYWRIGHT_MODULE` to its resolvable module name or absolute `index.mjs`.
Optionally set `HERO_CHROMIUM_PATH` for an installed Chromium executable:

```sh
HERO_PLAYWRIGHT_MODULE=playwright node --test tests/hero.test.mjs
```

The browser checks cover deferred loading, actual keyboard rendering, block
selection, view teardown/re-entry, 320/390/768/1440px overflow, reduced-motion
media requests and both unsupported and lost WebGL. They do not certify all
assistive technologies or physical-device performance.

Local verification of this implementation: Node.js 24 typecheck and optimized
build passed; 22/22 web tests passed with browser checks enabled against the
standalone preview, and 26/26 CRM gateway tests passed. Chromium software-WebGL
checks and rendered screenshots covered 320, 390, 768 and 1440px layouts.
Physical mobile devices and Safari were not tested. No publication was performed.

The owner subsequently authorized publication of this hero on2026-11-11. The
existing main-branch workflow verified and deployed release6744752. External
checks found a host proxy temporary-directory ownership mismatch that truncated
large responses, despite passing container health. The administrator-authorized
project-only Nginx policy repair is documented in `DEPLOY.md`. All23 public web
checks then passed, including browser interactions and complete hero asset bytes.

## Approved content and boundaries

The owner supplied the offer and contact on 2026-11-10:

- Lots from COP 13,000,000, with a stated 7 × 14 m option (98 m²).
- Financing up to 24 months; no invented down payment, interest or installment amounts.
- Acacías, Meta; no invented coordinates, travel times or street address.
- WhatsApp and telephone: +57 300 834 8478.
- Project amenities, water/electricity and 8 m gravel/compacted roads with concrete curbs.

The amenities describe the owner's project information, not a certification that all
facilities are completed. The page asks visitors to confirm construction progress,
service delivery, price, financing terms and lot documentation with the adviser.
The supplied PDF is a static reference, not live inventory. Its paved-road annotation
is not repeated: current owner information describes gravel/compacted roads.

Contact actions open WhatsApp with a prefilled message or the phone dialer. There is
no analytics script or AI sales assistant. The amenities-section registration modal
now stores consented name/phone leads and a persistent registration code in the CRM;
see `LANDING-REGISTRATION.md` for its behavior and local verification.
The footer explains the WhatsApp handoff; it is not a substitute for a future CRM's
privacy policy and consent implementation.

## Media provenance

All project visuals come from owner-supplied files; no synthetic property photography
or external stock image was added. Original machine-specific source paths are not
embedded in application code.

| Public asset stem | Owner input | Use |
| --- | --- | --- |
| `aerial` | Photo ending `b5666ff3-8b52-4d20-b5e3-ed45328c89d6.jpg` | Lead real-photo gallery tile |
| `neighborhood` | Photo ending `765d5ac2-c81d-4a7b-b106-51381988d6f8.jpg` | Gallery aerial |
| `entrance` | Photo ending `0639fd29-3bdb-48dd-963b-e831a163da76.jpg` | Elevated entrance |
| `gate` | Photo ending `e3ca2187-5867-4674-a385-8511aa7b3f76.jpg` | Entrance detail |
| `plano-jardines-del-encanto.pdf` | `PLANO JARDINES NUEVO.pdf` | Unchanged vector extraction source |
| `masterplan.webp` | First page of that PDF | Upright, rotated 270° preview |
| `recorrido-arquitectonico.mp4` | `WhatsApp Video 2026-11-09 at 6.23.09 PM.mp4` | Architectural visualization, approximately 40 seconds |
| `film-poster.webp` | Frame at 3 seconds of that video | Clearly labeled illustrative cover |

Photos were auto-oriented and encoded to 960/1920 px-wide WebP variants, without
object removal or generative alteration. The video was remuxed with fast-start metadata;
its original audio and video streams were not re-encoded. It is **an architectural
render**, not evidence of completed construction. The hero caption explicitly states this.
The full-film player is initially muted and has native controls; the hero uses
the custom controls described above. Desktop autoplay is
conditional; mobile and reduced-motion visitors start it explicitly. It pauses
when offscreen or when the document becomes hidden. No speech transcription or captions were supplied;
full audiovisual accessibility has not been certified.

The logo poster is a visual reference, not a transparent logo asset. The header uses
an accessible plain-text project name until approved original artwork is supplied.
Plus Jakarta Sans (public landing) and Manrope (CRM) are self-hosted, with their
SIL Open Font Licenses beside the font files.

## Implementation notes

- The page is server-rendered; menu/gallery/video, the daily timer and SVG explorer
  use client state. Only the explicit registration submission persists customer data;
  merely opening, dismissing or exploring the landing creates no lead.
- Responsive photographs are encoded ahead of time. `ProjectPhoto` uses `picture`
  sources and unoptimized Next Image output to avoid writing an image cache inside
  the production read-only filesystem.
- The standalone Docker image must copy `apps/web/public` as well as `.next/static`.
- The photo viewer uses a native dialog with named controls and Escape dismissal.
  The hero video uses native playback/fullscreen controls and a visible disclaimer.
  Desktop autoplay is muted and gated by screen size, reduced motion, connection
  hints and visibility. Mobile/data-saving/reduced-motion visitors start playback
  themselves. Video pauses offscreen or when the document is hidden.
- Approved public pages may index on the branded domain; CRM/private routes and
  the preview remain noindex under the policy in `SEO-GEO.md`.

## Checks

Use Node 24, install the existing lockfile with `npm ci`, then:

```sh
npm run dev --workspace=apps/web -- --hostname 127.0.0.1 --port 4317
# In another terminal:
npm run typecheck
npm run test:web
python3 -m unittest discover -s tests -p 'test_*.py'
```

`LANDING_BASE_URL` can point the HTTP tests at a local production container.
The HTTP suite verifies supplied content/contact, all media endpoints, the existing
health contract and security headers. Browser checks cover responsive reflow, menu,
gallery, FAQ, playback and dialog focus. A successful check is not a WCAG certification.

Before permanent-domain launch: obtain the original logo, confirm commercial terms and exact
location, review media/publication permissions, choose the domain, and explicitly
authorize the final-domain cutover. This document does not expand remote authorization.

### Historical baseline results — 2026-11-10

- Baseline content test failed before implementation; all three HTTP tests pass after it.
- Node 24 production build and TypeScript checks pass, as does the Docker image build.
- Existing deployment tests: 10 pass. Existing API tests: 4 pass; Ruff passes.
  The API test run reports an existing Starlette/httpx deprecation warning.
- Browser checks pass at 320, 390, 768 and 1440 px: no horizontal overflow or page
  errors, all images decode, menu links/Escape work, gallery navigation and focus
  return work, FAQ expands, and all six WhatsApp links use the owner's number.
- The video is not requested before interaction; explicit playback succeeds with
  approximately 40 seconds duration, and closing the dialog pauses it.
- Independent packaging verification confirms media, font and application chunks
  return 200 from the nonroot/read-only container, with dropped capabilities and
  no-new-privileges. Container filesystem diff remains empty after requests.
- Readiness against the backend/database was not reverified: the isolated web preview
  intentionally has no backend attached. No full accessibility certification was run.

Historical standalone preview: `http://127.0.0.1:4318`, container
`jardines-landing-local`. Stop it when no longer needed with
`docker stop jardines-landing-local`; it exposes no public-interface port.

### Current observed results — 2026-11-11

- Local Node 24 production Docker build and TypeScript checks pass. Only the local
  web container was recreated; the API and PostgreSQL volumes were not changed.
- Four HTTP landing checks and ten clock/source-geometry checks pass. Two fresh
  source-PDF extractions produce byte-identical generated JSON and SVG.
- Browser checks pass at 320, 390, 640, 768, 800, 900, 1024 and 1440 px without
  horizontal overflow. Phone/tablet menus, gallery navigation/Escape/focus return,
  local font, hydrated timer and reduced-motion presentation are verified.
- The hero video loads only on explicit mobile playback; desktop error fallback
  and offscreen pause are verified. No audiovisual accessibility certification
  or new captions/transcription were performed.
- Browser SVG checks verify 55 block groups, 1,568 actual parcel paths and no
  unresolved markers. Block controls, lot selectors, printed data, source
  anomalies, WhatsApp links, keyboard navigation, zoom/reset and touch pan work.
- Current local preview: `http://127.0.0.1:4321/`, container
  `jardines-crm-local-web-1`. This redesign has not been pushed or deployed to the VPS.
