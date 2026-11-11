# Public search visibility — 2026-11-11

The owner authorized SEO/GEO work and confirmed the audience: buyers who live in
Bogotá and Soacha considering lots physically located in Acacías, Meta. This is
not authorization to invent local offices, move the project in metadata, promise
rankings, publish investment returns, or change CRM/provider origins.

## Implemented foundation

- Only the homepage and `/lotes-acacias-desde-bogota-soacha` opt into indexing.
  The application root retains `noindex` as a safe default; CRM/login metadata
  and private API/health response headers remain `noindex, nofollow`.
- The public-domain Nginx policy defaults to `noindex`, with explicit exceptions
  for those public pages, robots, sitemap and public media. The original preview
  keeps its blanket noindex header. No private paths enter the sitemap.
- Public metadata uses the verified branded HTTPS origin, distinct canonicals,
  Spanish titles/descriptions, real-image Open Graph and Twitter cards, and
  snippet/image preview settings. Next may serialize the homepage canonical
  without a trailing slash; URL normalization treats it as the same root URL.
- `robots.txt` allows public crawling and disallows CRM, login, API and health.
  It does not block assets required for rendering and is not access control.
- The sitemap contains exactly two canonical public URLs. No fabricated
  last-modified timestamps, city clones, hidden landing pages or private routes.
- One linked, server-rendered buyer guide addresses the actual audience's
  questions: project location, informed starting price, lot option, financing
  boundaries, preparing a visit, documentation questions, progress and interest
  registration versus reservation. No travel time, deed/legal status, interest
  rate, down payment, construction completion or return is invented.
- JSON-LD describes Organization, WebSite, WebPage and the real Acacías Place,
  with stable IDs, known telephone, country and region. It is escaped before
  inline rendering. No fake addresses, coordinates, ratings, local branches,
  availability, SearchAction, FAQ rich-result claims or unsupported offer terms.
- Important answers and facts are in visible HTML, not only JSON-LD, video, 3D,
  modal-only content or an AI-specific file. Existing media and consent-based
  registration behavior remain unchanged. No analytics SDK or dependency added.

The guide intentionally serves both audiences in one useful page rather than
creating near-identical Bogotá/Soacha doorway pages. Public UI keeps the existing
brand, typography and mobile behavior, with a restrained editorial reading layout.

## Verification and publication

`tests/seo.test.mjs` verifies public/private indexing, canonicals/social metadata,
useful geography-specific HTML, exact sitemap scope and factual JSON-LD. The
homepage check failed against the previous compiled preview before implementation.
An initial assertion expected a trailing slash that Next normalizes away; it now
compares parsed URL identity rather than changing valid canonical output.

Observed pre-publication checks: Node24 optimized build/TypeScript passed,31/31
browser-enabled web checks passed,53/53 CRM gateway checks passed and3/3 Nginx
policy checks passed. Guide screenshots at390px and1440px were visually reviewed;
the browser test also covered320px and768px. No physical-device or search-ranking
result is implied. The administrator policy checkpoint is
`/srv/jardines-del-encanto/seo-setup-8ph0t2lx`; its candidate was staged until
the application deployment succeeded, then activated after release `a4f9f56`.

Public acceptance passed31/31 browser-enabled web tests,6/6 domain/origin checks
and Googlebot-identified requests for both indexable pages. The preview still
returned noindex. Nineteen other vhost hashes and22 sibling container identities/
start times were unchanged. No registration was submitted. The first public guide
browser test clicked its destination while `document.readyState` was `loading`;
after explicitly waiting for native navigation's load state, all four widths
passed with zero page errors. This was test navigation synchronization, not an
application/form rewrite.

Run Node24 build, browser-enabled `test:web`, CRM gateway checks, and the Nginx
policy tests. Browser-check the guide at320/390/768/1440px, navigation back to the
project and its existing modal, and the absence of horizontal overflow/page errors.

Publishing requires both the verified main-branch application deployment and an
administrator-installed public-domain policy; CI does not replace root-owned
Nginx policy. Keep the original vhost and sibling metadata checkpoint. Validate
`nginx -t`, reload (not restart), then check actual public HTTP headers and HTML,
Googlebot responses, assets, robots, sitemap, and unchanged preview/private noindex.
Do not weaken authentication or lift indexing on the preview to solve a canonical
or crawler issue. No customer data is needed for these checks.

## Measurement and remaining owner-controlled steps

This implementation makes pages technically eligible for discovery; it is not
proof that Google indexed them, ranked them, or that an AI system cited them.
Do not promise first positions or a specific indexation time.

Verify the branded property in Google Search Console with the owner's chosen
Google account, submit `/sitemap.xml`, inspect both public URLs and track actual
query/page impressions, clicks and registrations. Search Console ownership or
DNS verification tokens are not inferred, invented or installed by this change.
Authenticated access and token-specific DNS changes need explicit authorization.
No existing account data or baseline metrics were available in this task.

Track buyer-intent queries about lots in Acacías/the Llano from Bogotá and Soacha,
not a false promise of lots physically in those cities. Further content should
come from real buyer questions, current project evidence and measured queries.
Any Google Business Profile must use an actual verified eligible business
location; no fictitious Bogotá/Soacha branches or purchased backlink campaign.

## Primary references checked on 2026-11-11

- [Google AI features and websites](https://developers.google.com/search/docs/appearance/ai-features):
  ordinary SEO foundations, indexability and useful visible content remain relevant;
  there is no special AI file/schema requirement or guaranteed inclusion.
- [Google spam policies](https://developers.google.com/search/docs/essentials/spam-policies):
  avoid doorway/location clones and manipulative content.
- [Structured data guidelines](https://developers.google.com/search/docs/appearance/structured-data/sd-policies):
  markup must reflect visible, relevant and non-misleading content.
- [Next metadata](https://nextjs.org/docs/app/api-reference/functions/generate-metadata),
  [robots](https://nextjs.org/docs/app/api-reference/file-conventions/metadata/robots),
  [sitemap](https://nextjs.org/docs/app/api-reference/file-conventions/metadata/sitemap),
  [JSON-LD](https://nextjs.org/docs/app/guides/json-ld): verified against16.4.5 docs,
  compatible with this project's16.4.6 build.
