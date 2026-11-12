# Jardines del Encanto: design system

**Direction:** a calm, landscape-led real-estate brand, with a focused, practical CRM.
**Scope:** the landing page, CRM, AI assistance, forms, transactional screens and future UI.
**Status:** implementation specification v1; not a claim that these interfaces already exist.

## Start here

Use one identity with two densities: spacious public storytelling and compact private work.
Read this file before UI work. Use the project skill in
[`.agents/skills/jardines-ui/SKILL.md`](.agents/skills/jardines-ui/SKILL.md).
The requested spelling [`desing.md`](desing.md) points here; keep this file authoritative.

| Decision | Contract |
| --- | --- |
| Brand | Jardines del Encanto, Acacías, Meta, Colombia |
| Character | Natural, clear, grounded and welcoming; not ornate luxury or generic AI software |
| Theme | Light by default; dark forest is an accent surface, not a dark-only product |
| UI language | Professional Colombian Spanish, `es-CO`; identifiers and technical docs remain English |
| Typography | Plus Jakarta Sans 500–800 for the public landing; Manrope for the CRM; preserve the supplied logo artwork separately |
| Styling | Existing Next.js App Router, TypeScript and Tailwind CSS 4 |
| Primary public action | Proposed: “Agendar una visita”; activate only with a real destination |
| Primary CRM action | The next sales task; AI assists it without taking over the workspace |

## 1. Brand evidence and boundaries

The owner's [reference poster](docs/brand-reference.png) shows dark green lettering,
vegetal green, palms, a serif/script wordmark, landscape photography and blue sky.
Use these as visual evidence, not proof of legal status, lot boundaries, built amenities,
prices, availability or returns. Do not turn the poster into a literal page layout.

Pixel inspection found common dark-logo buckets near `#001808` and sale-lettering buckets
near `#507010`. The tokens below are deliberate UI normalizations of a raster reference,
not certified original brand values. Recheck them when source artwork is supplied.

### Logo

- Preserve the wordmark, palms, leaf, proportions and approved color variants.
- Request the original SVG or transparent high-resolution artwork before public launch.
  The poster is a reference, not a production-ready logo or verified standalone photograph.
- Never imitate its script with a random font or reconstruct the palms with generic icons.
- Use a light, quiet logo area. Do not invert or recolor the mark without an approved variant.
- Reserve clear space of at least half the capital wordmark height around the mark.
  At small sizes, use an approved simplified mark or a plain text project name as a fallback.
  Do not invent a new monogram.

## 2. Color tokens

| Semantic token | Value | Use |
| --- | --- | --- |
| `brand.forest` | `#062619` | Primary buttons, headings, navigation emphasis |
| `brand.forestHover` | `#0C3B28` | Primary hover/pressed surface |
| `brand.leaf` | `#507010` | Links and limited supporting brand accents |
| `brand.leafWash` | `#EEF3E8` | Selected items and subtle brand backgrounds |
| `surface.canvas` | `#F6F7F1` | Main page background |
| `surface.panel` | `#FFFFFF` | Forms, dialogs and dense work surfaces |
| `text.primary` | `#062619` | Primary readable text |
| `text.secondary` | `#526056` | Supporting readable text |
| `text.inverse` | `#FFFFFF` | Readable text on forest surfaces |
| `border.subtle` | `#D9E1D5` | Decorative separators; not the only control boundary |
| `border.control` | `#7B897E` | Input boundaries and meaningful neutral outlines |
| `focus.ring` | `#507010` | Focus ring with a contrasting 2px surface-colored offset |
| `focus.ringInverse` | `#FFFFFF` | Focus ring on dark forest surfaces, with a forest offset |

Keep roughly 80% of the interface neutral, most remaining brand color forest, and leaf
as a restrained accent. This is a composition guide, not a color-usage counter.
Sky blue belongs in truthful photography; do not add it as a competing CTA color.
Avoid purple AI gradients, neon glows, glass panels and gold luxury styling.

### Readable color pairs

Ratios calculated with sRGB relative luminance; values below are rounded for display.
Check actual component states without rounding when testing thresholds.

| Foreground / background | Approximate contrast |
| --- | --- |
| Forest / canvas | 15.01:1 |
| White / forest | 16.17:1 |
| Leaf / white | 5.73:1 |
| Leaf / canvas | 5.32:1 |
| Secondary text / canvas | 6.16:1 |
| Control border / canvas | 3.41:1 |

The existing provisional `#658D24` leaf token only reaches about 3.90:1 on white.
Do not use it for ordinary text or white-label buttons. The landing implementation
uses the normalized `#507010` leaf token.

### Status colors

| Status intent | Text | Background | Proposed example |
| --- | --- | --- | --- |
| Success | `#216E47` | `#EAF5EC` | “Disponible” or a confirmed successful action |
| Caution | `#855708` | `#FFF4DB` | “En reserva” or a review required |
| Error | `#A62B35` | `#FDEBED` | A validation or failed action |
| Neutral | `#526056` | `#F1F3EF` | “Vendido”, archived or inactive information |

These are visual mappings, not authorization to implement reservation/sales rules.
Always include the label; use an icon when helpful. Never encode availability with color
alone. Do not color a legitimately sold lot red as if it were an application error.

## 3. Typography and content

The owner's 2026-11-11 landing revision authorizes a different, heavier typeface:
use self-hosted **Plus Jakarta Sans**, weights 500–800, on the public landing only.
Headlines use 800 and CTA labels use 800. Keep the private CRM on
[Manrope](https://fonts.google.com/specimen/Manrope), weights 400, 500, 600 and 700.
Load a reviewed, licensed font asset through `next/font` or self-hosted `@font-face`;
no runtime font CDN. Both variable families and their SIL Open Font Licenses live in
`apps/web/app/fonts/`. Use a system sans fallback
while loading. The logo's existing serif/script artwork is not a second interface font.

| Role | Mobile | Desktop | Notes |
| --- | --- | --- | --- |
| Landing H1 | 44–65px | 58–80px | Plus Jakarta Sans 800; short, meaningful line breaks |
| Section heading | `text-3xl` | `text-4xl` | Clear hierarchy, no repeated decorative eyebrows |
| CRM page heading | `text-2xl` | `text-3xl` | Keep actions and current task visible |
| Body / forms | `text-base` | `text-base` | 16px inputs, readable spacing |
| Table / supporting text | `text-sm` | `text-sm` | 14px; do not shrink to fit more columns |
| Minor metadata | `text-xs` | `text-xs` | 12px minimum; never essential instructions |

Headings use balanced wrapping; body copy stays near 60–65 characters per line.
Use tabular numerals for amounts and comparable metrics. Format money, dates and phone
numbers for the actual `es-CO` context; include currency and time zone where ambiguous.

Copy should be specific and helpful: “Ver disponibilidad”, “Agendar una visita”,
“Guardar contacto”, “Revisar borrador”. These are proposed labels, not active services.
Avoid inflated claims, fake scarcity, invented testimonials, unverifiable time-to-city
claims, meaningless “AI-powered” slogans and financial promises.

The owner requested a launch-price banner, “Quiero mi cupo” CTA and repeating 24-hour
clock. Use the supplied COP 13 million starting price. Per the owner's follow-up,
show neither the daily-cycle label nor the explanatory reset/expiration paragraph;
keep an accessible name on the timer. Omit the location/sales eyebrow above the hero
headline. Never label this repeating cycle as a price-expiry or stock deadline.
“Quiero mi cupo” opens an information/visit request, never an automatic booking.
All “Quiero mi cupo” buttons (launch banner, hero, amenities, final CTA and mobile
bar) open the same registration modal, never an immediate WhatsApp redirect. The
modal may save explicitly consented name/phone leads and issue
a persistent interest-registration code. It is dismissible and does not reserve
property, collect payment, or promise availability. Other contact links use WhatsApp.

## 4. Space, shape and layout

### Public search visibility

The owner confirmed buyers in Bogotá and Soacha as an audience for the project in
Acacías, Meta. Keep that distinction explicit in visible copy and structured data.
Use a useful shared buyer guide, not duplicated city pages or invented offices.
Only approved public pages on `jardinesdelencanto.site` may index; CRM, login,
APIs and the original preview remain excluded. See `docs/SEO-GEO.md` for policy,
verification and the limits of SEO/GEO claims.

- Spacing scale: 0, 2, 4, 8, 12, 16, 24, 32, 40, 48, 64, 80 and 96px.
- Marketing container: max 1280px; gutters 16px mobile, 24px tablet, 32px desktop.
- Marketing section spacing: 48–64px mobile, 80–96px desktop, adjusted for content.
- CRM page padding: 16px mobile, 24–32px desktop; avoid marketing-sized whitespace.
- Radius scale: 4px small labels, 8px controls, 12px panels, 16px large dialogs.
  Pills are for genuine compact statuses, not every card or CTA.
- Prefer whitespace and subtle dividers to nested cards. Use shadows only for elevation
  such as menus/dialogs, not to outline every dashboard item.
- Use Grid for composition. Meaningful content determines the cell count, not a template.
- Breakpoints: 640, 768, 1024, 1280 and 1536px. Test real intermediate widths as well.
- Reflow at 320px. Do not hide required fields, actions or content to make mobile fit.
  Wide data tables may have a clearly signposted local scroll area.

## 5. Landing-page composition

**Art direction:** generous light surfaces, a quiet forest-green hierarchy and real
landscape imagery. Let the place carry the emotion. Use a deliberate split hero or
wide photograph composition, not a centered SaaS hero with floating dashboard cards.

Proposed sequence, pruned to the approved information available:

1. Restrained header: approved logo, essential section links and one primary CTA.
2. Hero: clear lot-sales/location statement, concise explanation, the supplied
   architectural video with a visible illustrative-media disclaimer, and a primary
   action. The confirmed launch price may appear; no fabricated availability/trust strip.
3. Project overview: a short factual explanation supported by approved media.
4. Location: a verifiable location/map and practical access information when supplied.
5. Lots and project features: a native SVG explorer with source-backed block/lot
   geometry and source dimensions. No live inventory claim or inferred lot availability.
   Source identifier anomalies must stay visible, not be silently corrected.
6. Visit process and factual FAQ: answer genuine objections without inventing guarantees.
7. Final contact/visit CTA and footer with working contact, privacy and legal information.

Repeat the same primary CTA instead of competing with several conversion goals.
A secondary “Ver ubicación” can support it. No dead `#` links, invented contact number
or prechecked consent. A sticky mobile action must not cover content or focused fields.

Do not enforce a testimonial section, benefit number, animated tagline or stock counter
when there is no approved content. The project's truthfulness and accessibility override
generic marketing recipes.

## 6. CRM composition

**Art direction:** the same palette and type, lower visual variance and greater useful
density. No full-bleed photographs, oversized promotional typography or decorative charts.

- Desktop shell: approximately 224px quiet navigation, a 64px header, and a flexible
  content area. Active navigation uses label weight and a clear selected surface.
- Implemented navigation begins with “Dashboard”, then “Sara IA”, followed by
  “Pipeline”, “Clientes” and “Seguimientos”; “Configuraciones” stays at the bottom.
  Show only authorized, implemented modules.
- The home view prioritizes next actions and overdue follow-ups. Metrics must answer
  real questions, not occupy a decorative four-card dashboard row.
- Contact detail: identity, assignment, next action and a readable activity timeline.
  Put editing in a focused panel; keep the user's position after saving.
- Pipeline stages are Nuevo, Contactado and Ganado only. The page heading has no
  duplicate “Nuevo cliente” action; retain the empty-state and Nuevo-column entry points.
- Pipeline: list/table remains usable without drag-and-drop. Any board movement must
  have a keyboard-accessible equivalent and obey server-side workflow rules.
- Inventory: provide a list fallback for plans/maps. Lot selection must expose a textual
  identifier and status, not require recognizing a polygon color.
- At smaller widths, replace the sidebar with a labeled drawer and a single-column
  task flow. A 360–400px supporting panel becomes a full-width sheet.

## 7. Components and states

| Component | Contract |
| --- | --- |
| Primary button | Forest + white, 44–48px target height, 16px semibold, verb-led label |
| Secondary action | White/transparent + forest; readable outline where needed |
| Destructive action | Labeled destructive intent, confirmation proportional to consequence |
| Text link | Leaf + underline on hover/focus; never distinguished by color alone |
| Form field | Persistent label, helpful format hint, 44–48px height, associated inline error |
| Checkbox / switch | Labeled purpose, visible selected/focus/disabled states |
| Table | Clear headers, sorting semantics, row actions and a mobile fallback |
| Dialog / sheet | Accessible name, controlled focus, Escape where safe, focus returned on close |
| Toast / feedback | Supplemental only; important errors remain beside their task |
| Empty state | Explain the absence and the next useful action; no fabricated sample customers |

Design default, hover, active, focus-visible, loading, success, error and disabled states
for every applicable interactive component. Keep button labels stable while loading;
prevent duplicate submissions and preserve entered values after errors.
Distinguish first use, no search results, permission denied, offline, unavailable data
and service error. A decorative skeleton is not the only loading explanation.

Use one icon family: proposed Phosphor, regular weight. Check dependencies and licensing
before adding it; it is not currently installed. Icons supplement labels; critical
actions should not depend on an unexplained icon. Brand artwork is not an icon-library glyph.

## 8. AI-native interaction

AI remains optional, not the default view or an always-open overlay. The owner's
dedicated “Sara IA” navigation opens the existing Hermes operator as a full-height
workspace; contextual actions preserve the current CRM task.

- Distinguish “Borrador de IA”, “Pendiente de revisión”, “Confirmado” and “Error”.
- Show source activity/records and data recency when available; disclose unavailable
  evidence. Do not invent confidence percentages.
- Proposed writes show the target record, exact proposed changes and any real outbound
  recipient. “Aprobar y aplicar” is distinct from “Descartar” or “Editar”.
- Keep generation and committed execution visually separate. Never show success before
  the API confirms the action. Permission checks belong to the API, not a hidden button.
- Provide cancellation, useful failure feedback and recovery without losing the draft.
  Undo is offered only when a backend operation genuinely supports it.
- Public inquiries never expose the private CRM or internal prompts. Customer messages
  and uploaded content are untrusted data, not instructions for the assistant.

This document does not activate Hermes, messaging, autonomous sales or privileged tools.

### Shared settings and Hermes operator

The owner-authorized settings surface is a native modal preserving the current CRM
view. Use three concise tabs: **Redes sociales**, **Conexiones**, **Customizaciones**.
Prefer application icons, short real-state labels, Edit and accessible on/off controls
over explanatory cards. **Conexiones** owns provider applications (Zernio,
ElevenLabs, Sara/Hermes and future application adapters), their authorization,
credentials and provider diagnostics. **Redes sociales** contains only the brand's
social channels connected through Zernio and their synchronization/linking controls.
A channel that needs provider authorization opens Zernio's editor in Conexiones;
keep one persistent callback consumer rather than mounting an OAuth flow per tab.
Customizations filter Skills, Tools, Plugins and Scripts;
creation/editing stays inline and starts disabled until explicitly enabled.

The app and Hermes share the same typed capability registry. Scripts are bounded app
workflows, not arbitrary code; unknown adapters must not appear connected. Hermes
replies, tool results and exact pending action arguments remain distinct from confirmed
execution. Approve/reject controls must show the consequences before a write. A switch
reflects server-confirmed preferences, never proof of provider authorization or health.
Keep one social callback consumer mounted through completion across tabs/modal closing,
scrub callback parameters promptly, and preserve Escape, focus return and small-screen reflow.

### Sara IA chat

Keep the CRM's light canvas, Manrope typography and quiet forest/leaf accents.
Following the owner's personal-assistant reference, use one centered conversation
column (approximately 820px) with a compact icon toolbar, a large left-aligned
welcome and a unified composer. History is a named native modal at every viewport,
not a permanent second sidebar. Preserve the CRM shell and Jardines palette rather
than copying the reference's dark/orange theme. Do not make the whole page
horizontally scroll. Chat prose is plain text, never untrusted rendered HTML.
Group confirmed tool results in a collapsible activity section; keep exact pending
proposal consequences and approval controls separate and visible.

Offer new conversations, title editing, history search and paging, project skills,
documents and voice notes. An uploaded document is data, not agent instructions.
Voice recording requires an explicit click and a local preview/discard step before
upload/transcription; sending is a separate action. This existing text/voice-note
flow never starts a live call or spoken reply automatically. The separately
activated shared voice provider is specified below. Show real unavailable states
instead of a decorative active
microphone or invented skills. Create an untitled conversation directly on first
use or the new-chat action; renaming is secondary, not a prerequisite to writing.
Enter sends, Shift+Enter inserts a line break, and IME composition never sends.
Skills management stays in Settings. Typing `$` in the composer opens a compact,
keyboard-accessible skills picker with truthful enabled/unavailable states; selection
inserts a mention and never submits. History rows offer deletion with a named native
confirmation and explicit irreversible scope. Preserve failed/uncertain operations,
reject active-turn deletion and never undo confirmed business changes implicitly.
One attachment entry accepts supported documents/audio; one recording control
retains the explicit voice-note review flow. Keep drafts and recover ambiguous
submissions with the same request identity rather than generating twice.

## 9. Motion, imagery and optional 3D

Use motion for feedback or a clear state transition: approximately 120–180ms controls
and 180–240ms panels. Prefer CSS opacity/transform changes; respect reduced motion.
No cursor replacement, magnetic buttons, scroll hijacking, autoplay parallax or perpetual
decorative loops. Text and primary actions remain available without animation.

The owner-approved “Del plano al lugar” hero pairs a short excerpt of the supplied
architectural video with an optional interactive 3D masterplan. Load the renderer
only after explicit selection. Reuse the PDF-extracted block/lot geometry; the
presentation plinth and shallow extrusion are illustrative, not terrain, property
boundaries, construction progress or live inventory. Retain a 2D fallback, keyboard
and selection controls, reduced-motion support, and visible media disclaimers.
Per the owner's cleanup revision, show no decorative headings, slogans, duplicate
explore CTA or instruction text over either media view. Keep control labels and
accessible names; place the factual illustrative-media notice outside the stage.
On the stacked/mobile hero, show the media switcher and visual before the copy;
keep desktop copy on the left and media on the right. Use one media instance.

Use original, owner-approved photography with recorded usage rights. Preserve location
truthfulness; never generate nonexistent facilities, property boundaries or an aerial
image presented as evidence. The supplied poster may guide composition but is not a
license to fabricate the project's physical features.

Reserve image dimensions, crop with the subject intact and optimize responsive sizes.
Use short factual alternative text for meaningful images and empty alt for decoration.

The requested `img2threejs` source is a **pending optional candidate**, not a core dependency.
A future 3D entrance/object illustration must have a real purpose, separate approval,
verified assets and a plain static fallback. Clearly label illustrative geometry. Never
infer a cadastral plan or lot measurements from the poster. Do not put WebGL in CRM
tables, forms or essential navigation; load optional 3D only on deliberate demand.

## 10. Accessibility and implementation acceptance

Target WCAG 2.2 AA. This is a target, not a certification of the current placeholder.
Normal text requires 4.5:1 contrast; qualifying large text requires 3:1. Meaningful
control/graphic boundaries require 3:1 against adjacent colors. A subtle decorative
divider is not sufficient as the only visible input boundary.

The project's touch target goal is 44×44px. Do not confuse that goal with WCAG AA's
24×24px minimum and its defined exceptions. Include keyboard access, visible unobscured
focus, semantic headings/landmarks, a skip link, labeled errors, screen-reader feedback,
reduced motion and zoom/reflow checks.

For each future UI delivery:

- [ ] Explain the screen's user task and whether landing or CRM density applies.
- [ ] Use semantic tokens, shared components and approved Spanish copy.
- [ ] Test at 320, 390, 768 and 1440px, including keyboard-only use and zoom.
- [ ] Check actual color pairs in every state; do not infer accessibility from tokens alone.
- [ ] Show loading, empty, error, permission and success behavior relevant to the screen.
- [ ] Verify forms and API-backed effects end to end, not just their visual appearance.
- [ ] Review real browser screenshots with representative, non-sensitive fixtures.
- [ ] Preserve core functionality when images, animation, optional 3D or AI are unavailable.
- [ ] Record measured performance and unresolved issues; do not claim unmeasured success.

No application code, dependencies, server configuration or live deployment is changed
by this specification. Fonts, tokens and components are implemented in a later UI task.

## 11. Sources and rule precedence

Authority: explicit owner requirements and approved assets, then this project contract,
then applicable reviewed project skills, then general local guidance. This resolves
aesthetic defaults; it never overrides safety, permissions or content verification.
Marketing-only advice does not dictate CRM density, workflow or access control.

Trusted inputs used here: the owner's poster/brief, the existing repository plan,
locally installed `design-taste-frontend`, `landing-page-design` and `cognitive-doc-design`.
Their general principles are adapted to this project, not copied as a bundle of
conflicting global defaults.

The five newly requested external repositories are recorded, but **not imported or
approved**, in [the source intake record](docs/DESIGN-SOURCES.md). Their raw skill
instructions were not loaded as project authority. A GitHub commit or license label
is provenance metadata, not an exact-hash security approval.

Primary accessibility references:
[text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html),
[minimum target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).


### Shared voice provider

The owner subsequently requested ElevenLabs shared by the CRM and Hermes. Add it
under Settings > Conexiones with the existing compact icon/edit/switch pattern.
Sara stays Hermes; an ElevenLabs voice agent is a separate provider session, not a
replacement model. Generating an audio response creates an exact proposal first;
never start paid work or audio playback automatically. Voice-agent sessions require
an explicit start button and microphone consent, with visible stop/mute controls.
Calls require a separate exact-recipient consent checkbox. Provider credentials
must never be prefilled, rendered in results or included in chat history. Use
honest unavailable/paused/partially permitted states rather than fake connections.
See [ELEVENLABS.md](docs/ELEVENLABS.md) for implemented scope and rollout limits.
