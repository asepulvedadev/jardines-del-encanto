# Landing page: content and local verification

The public landing is implemented in `apps/web`. The owner authorized publication,
VPS deployment and a temporary HTTPS preview on 2026-11-10. Search indexing remains
disabled. Deployment and preview operations are documented in `DEPLOY.md`.
`DESIGN.md` remains the shared visual contract. UI copy uses professional `es-CO`.

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
no lead form, database write, analytics script or AI sales assistant in this landing.
The footer explains the WhatsApp handoff; it is not a substitute for a future CRM's
privacy policy and consent implementation.

## Media provenance

All project visuals come from owner-supplied files; no synthetic property photography
or external stock image was added. Original machine-specific source paths are not
embedded in application code.

| Public asset stem | Owner input | Use |
| --- | --- | --- |
| `aerial` | Photo ending `b5666ff3-8b52-4d20-b5e3-ed45328c89d6.jpg` | Hero aerial |
| `neighborhood` | Photo ending `765d5ac2-c81d-4a7b-b106-51381988d6f8.jpg` | Gallery aerial |
| `entrance` | Photo ending `0639fd29-3bdb-48dd-963b-e831a163da76.jpg` | Elevated entrance |
| `gate` | Photo ending `e3ca2187-5867-4674-a385-8511aa7b3f76.jpg` | Entrance detail |
| `plano-jardines-del-encanto.pdf` | `PLANO JARDINES NUEVO.pdf` | Unchanged downloadable original |
| `masterplan.webp` | First page of that PDF | Upright, rotated 270° preview |
| `recorrido-arquitectonico.mp4` | `WhatsApp Video 2026-11-09 at 6.23.09 PM.mp4` | Architectural visualization, approximately 40 seconds |
| `film-poster.webp` | Frame at 3 seconds of that video | Clearly labeled illustrative cover |

Photos were auto-oriented and encoded to 960/1920 px-wide WebP variants, without
object removal or generative alteration. The video was remuxed with fast-start metadata;
its original audio and video streams were not re-encoded. It is **an architectural
render**, not evidence of completed construction. Both the section and player say so.
The player starts only on explicit interaction, is initially muted, has native controls
and pauses when its dialog closes. No speech transcription or captions were supplied;
full audiovisual accessibility has not been certified.

The logo poster is a visual reference, not a transparent logo asset. The header uses
an accessible plain-text project name until approved original artwork is supplied.
Manrope is self-hosted, with its SIL Open Font License beside the font file.

## Implementation notes

- The page is server-rendered; only menu/gallery/video interactions need client state.
- Responsive photographs are encoded ahead of time. `ProjectPhoto` uses `picture`
  sources and unoptimized Next Image output to avoid writing an image cache inside
  the production read-only filesystem.
- The standalone Docker image must copy `apps/web/public` as well as `.next/static`.
- Photo and video viewers use native dialogs, named controls and Escape dismissal.
- Search indexing stays disabled until a production domain and publication are approved.

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

### Observed local results — 2026-11-10

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

Local production preview: `http://127.0.0.1:4318`, container
`jardines-landing-local`. Stop it when no longer needed with
`docker stop jardines-landing-local`; it exposes no public-interface port.
