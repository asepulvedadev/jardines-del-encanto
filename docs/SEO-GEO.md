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


## Brand, sharing and entity upgrade — 2026-11-16

The owner requested stronger SEO/GEO, correct brand icons and a professional
information card when sharing a link. The current update remains local until
publication is separately authorized. It does not change indexable route scope,
private robots defaults, authentication, DNS or the root-owned Nginx policy.

- The home and buyer guide explicitly publish a 1200×630 PNG social card,
  with absolute branded URLs, dimensions, MIME type, descriptive alt and large
  Twitter card metadata. The versioned image URL replaces the old raw aerial
  WebP reference. It is not an event poster and has no expiring event date.
- The card uses the original white SVG lockup, an owner-supplied real gate
  photograph, Plus Jakarta Sans and the existing forest palette. Starting price,
  dimensions and financing are owner-supplied facts visible on the landing.
  No render, generated building, testimonial or unsupported claim was added.
- Browser icons use the original SVG's exact existing emblem, not a new mark.
  A multi-resolution ICO and square PNGs support browser/search/Apple clients.
  Organization markup uses a separate full-lockup 512×512 PNG on white.
- All assets live under `/media/`, which is already public in the deployed
  allowlist. Putting a favicon at another root route without updating the host
  policy would retain its default noindex header. No broader indexing exception
  or private route change is needed for the chosen paths.
- Metadata inheritance preserves the root noindex default and explicitly opts in
  only the two existing public pages. Organization logo/contact, an accurate
  ImageObject and a guide-only BreadcrumbList enrich the linked entity graph.
  The guide breadcrumb matches the visible `Inicio → Guía para compradores` path.
- Visible introductory copy answers what the project is, where the lots are and
  what the informed lot/financing option is. Bogotá and Soacha remain buyer
  audiences, not invented project locations or business offices.
- The two-page sitemap now includes only photographs visible on their respective
  pages. No fabricated last-modified dates, new doorway pages, coordinates,
  ratings, SearchAction or FAQ rich-result claims were introduced.

Rebuild assets with `node ops/media/build-social-assets.mjs` after `npm ci`.
It uses Sharp already provided by the locked Next dependency tree, the committed
original SVG/photo and local font. No AI image service, stock download, additional
runtime dependency or analytics script is involved. If the commercial facts
change, update the card source text, regenerate it and version its metadata URL.

Checks include server-rendered social tags for Googlebot, Facebook's share crawler
and Twitterbot; PNG/ICO types and dimensions; entity graph links; exact public
sitemap scope and unchanged private noindex behavior. Actual platform preview
caches and Google indexing/rankings are not controlled or guaranteed by these tests.
Search Console ownership/submission and any external share-debugger refresh still
require the owner's authorized account/session; none was accessed here.

Primary guidance checked on 2026-11-16:
- [Google AI features](https://developers.google.com/search/docs/appearance/ai-features)
  and [AI optimization](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
- [Organization](https://developers.google.com/search/docs/appearance/structured-data/organization),
  [breadcrumbs](https://developers.google.com/search/docs/appearance/structured-data/breadcrumb)
  and [image SEO](https://developers.google.com/search/docs/appearance/google-images)
- [Next metadata](https://nextjs.org/docs/app/api-reference/functions/generate-metadata),
  [icons](https://nextjs.org/docs/app/api-reference/file-conventions/metadata/app-icons)
  and [social images](https://nextjs.org/docs/app/api-reference/file-conventions/metadata/opengraph-image)

Context7 lookup was unavailable due to its monthly quota; official framework
pages supplied the documentation fallback. No special AI file/schema is required
for Google AI features, and eligibility is not an inclusion/ranking guarantee.
