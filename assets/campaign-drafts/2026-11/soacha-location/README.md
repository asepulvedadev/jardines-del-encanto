# Soacha event location draft

Owner-requested campaign 16, prepared on November 16, 2026. The original 15
campaign documents and images are unchanged. Production publication was authorized
after local verification; GitHub Actions records the release outcome separately.
The template remains a draft, not submitted to Meta, scheduled or sent to customers.

## Content and provenance

- Venue label corrected at the owner's request: `Cámara de Comercio de Bogotá — Sede Soacha`.
- Address supplied by the owner: `Carrera 7 # 11 - 83 (Soacha)`.
- The owner's 23-second voice note requests the venue photo, clear address and
  emphasis on paying attention to the location. No date or time was added.
- `venue-owner-original.png` preserves the supplied screenshot.
- `venue-enhanced.png` is a built-in image_gen restoration, with clarity and
  exposure improvements and the clipped bottom screenshot strip removed.
- `apps/api/app/campaigns/assets/campaign-16.png` is the vertical 941 × 1672
  artwork. Its project logo is reference-guided from the approved supplied
  artwork, not a claim of pixel-identical SVG composition.
- `poster-prompt.txt` records the built-in generation prompt;
  `venue-label-edit-prompt.txt` records the later focused institution-name edit. `manifest.json`
  records source and output hashes. No institution endorsement is implied.

## Editable CRM draft

The source-controlled `campaign-16` seed supplies the editable text, name and
location-link examples, plus the map URL and two choice buttons. The image is
included in the existing authenticated asset catalog; approval remains explicit.
The Maps link searches the exact address. It is not a verified coordinate pin.
No new provider integration, automated sending or schedule is introduced.

## Verification

- Campaign API and review tests: 26 passed.
- Campaign gateway tests: 6 passed.
- TypeScript typecheck and Ruff: passed.
- Original 15 campaign documents compared against HEAD: unchanged.
- Artwork visually checked for legibility, exact address and venue identity.
- Local verification did not use a production browser session or claim live CRM
  rendering. Release health is checked separately during deployment.
