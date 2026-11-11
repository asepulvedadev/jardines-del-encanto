# Source-backed interactive masterplan

The landing explorer uses individually selectable SVG parcels extracted from the
owner-supplied Civil 3D PDF. It does not trace a raster image, use invented
rectangles, or infer availability from the drawing.

## Source and reproducibility

- Source: `apps/web/public/media/plano-jardines-del-encanto.pdf`, page 1.
- SHA-256: `e80b746e47b808f077432a61a6794993205a244e896667b2e16d51feb416f74d`.
- Page coordinate system: 2835 by 4008 PDF points, origin at the top left.
- Dependencies: `scripts/masterplan_requirements.txt`.
- Regenerate with `python scripts/build_masterplan.py /absolute/path/to/source.pdf`.
  The generator refuses another source hash. It writes only the two generated
  masterplan assets atomically, so development-server readers never see partial
  JSON/SVG files. Generation is local and needs no service credentials.
- Verify with `node --test tests/masterplan.test.mjs` and `npm run typecheck`.

Generated assets are `apps/web/lib/masterplan-data.json` and
`apps/web/public/media/masterplan-context.svg`. Compact JSON and SVG are generated
machine assets; the generator, UI, types, tests and stylesheet remain readable.

The reviewed generation used the bundled Python/pdfplumber runtime and the
already-installed Shapely 2.1.2 package. Parsed objects from the verified PDF were
cached outside the repository during investigation; no sibling project's source
code was imported or executed, and no new dependency was installed.

## Extraction and geometric limits

1. Reconstruct text runs from source glyph matrices and drawing order. Do not use
   screen-oriented text extraction to reverse or rearrange rotated identifiers.
2. Extract source vector paths across non-foliage CAD colors. Parcel boundaries
   are predominantly RGB `(0.32941, 0.32941, 0.32941)`. Grey road edges, curves and
   other actual source colors are necessary to close perimeter parcels.
3. Subdivide original cubic Beziers using De Casteljau recursion, with control
   point deviation bounded to 0.005 PDF points (maximum recursion depth 18).
   This is vector-derived approximation, not raster tracing.
4. Reconcile an endpoint only to an existing, nonparallel source segment within
   0.2 PDF points. This accounts for tiny plotted-coordinate mismatches; it never
   creates a new boundary direction or connects inferred lot centers. Node at
   0.001 PDF-point precision and polygonize the actual source edges.
5. Accept only the smallest containing face with exactly one source lot label.
   Multiple labels in a merged face do not become invented subdivisions. If a face
   is unresolved, polygonize a supplemental graph that preserves the original
   vertices alongside the projected edges. Add only same-color, original PDF
   command-endpoint contacts within 0.2 points whose printed strokes overlap;
   do not connect artificial cubic subdivision points. Use this supplemental graph
   only for unresolved records, preserving the prior 1,564 audited paths exactly.
   This is not a tolerance increase or a guessed subdivision.
6. Associate printed area labels inside the polygon. Where geometry is unresolved,
   a nearest area is accepted only when the source lot is also that area's nearest
   lot label. Keep source text and position as evidence. Do not convert page-point
   areas into square metres.
7. Associate numeric dimension labels within 5.5 PDF points of a parallel parcel
   edge. Store original text, label position and edge index. These are printed
   edge annotations, not a new survey. Shared boundary labels can appear for both
   adjacent parcels. The UI deliberately lists side values, not a rectangular
   width-times-depth interpretation of an irregular parcel.

The context SVG contains selected original grey road surfaces with their original
curve commands. It contains no embedded images, branding raster or foliage CAD noise.
Coordinates are relative to the sheet, not georeferenced cadastral coordinates.

## Audited coverage and source anomalies

- 1,568 source lot-label occurrences, all retained with unique `source-lot-NNNN`
  internal identifiers in stable source drawing order.
- 55 parsed block identifiers: 1–53, 21a and 28a.
- 1,568 independently closed source-vector parcel faces; no unresolved contours.
- **LT 26-8, LT 26-26, LT 25-11 and LT 25-16** use the source-vertex-preserving
  stroke-contact fallback. Each recovered face contains exactly one source lot
  label. No background frame or generic marker is represented as a parcel.
- The previous 1,564 parcel path strings are byte-identical. Their ordered
  `[internal ID, path]` JSON SHA-256 is
  `2d02a8620b39dc4e434a61436db01ce3beae1f554d7d959033f8f8f1913f372f`;
  the deterministic regression pins that unchanged geometry independently of count.
- 1,570 source `A:` text runs, of which 1,568 include a parseable square-metre unit.
  `A: 180.00` and `A: 160.58` omit the unit in their source text runs. The generator
  does not invent that unit. Their raw text and source positions are retained for
  LT 17-7 and LT 26-3 respectively, with `areaM2: null`, provenance
  `printed-pdf-label-without-unit` and the `source-area-unit-missing` anomaly.
- Source labels LT 24-3, LT 24-4, LT 24-5 and LT 31-42 each appear twice.
  Printed labels are unchanged, and the UI disambiguates their internal references.
- `LT 1018` is malformed in the source. It remains unchanged. Its block association
  is spatially derived from its neighbouring block-10 labels and explicitly flagged;
  it is not silently renamed to LT 10-18.
- Source suffixes, including LT 44-16a and LT 44-17a, remain intact.
- LT 13-5 and LT 13-22 each contain multiple printed area labels; the closest
  contained label is stored and the UI flags the source ambiguity.

These are drawing-label counts, not a verified count of sellable or available lots.
Price, availability and legal measurements require confirmation by the project.
The individual-vector extraction covers every printed lot occurrence. It is not a
survey certification: source identifier, area and unit anomalies remain visible.

### Audited contact evidence

PDF object indices below are zero-based entries in pdfplumber's page `curve` list.
The source hash above fixes the drawing and object order.

| Parcel | Source commands and independently plotted contacts |
| --- | --- |
| LT 26-8 | Curve 9453 is the actual cubic from `(125.798857, 1809.626170)` to `(125.199990, 1814.956274)`. Its end meets curve 9454's straight start `(125.16, 1815.12)` within 0.169 points. The apparent 5.43-point straight-line gap is occupied by that original cubic, not an invented extension. |
| LT 26-26 | Curve 64578 ends at `(247.404898, 2093.517295)`; curve 64579 starts at `(247.44, 2093.52)`, a 0.035-point contact. Its other cubic start `(227.849443, 2067.635284)` meets the existing straight end `(227.88, 2067.60)` within 0.047 points. |
| LT 25-11 | Curve 64536 ends at `(482.834691, 2055.380244)` beside curve 64535's straight end `(482.76, 2055.48)`, within 0.125 points. Preserve the cubic and original straight vertices rather than independently displacing their shared contact. |
| LT 25-16 | Curves 64526 and 64527 meet at `(539.421029, 2069.174530)` and `(539.385428, 2069.185135)`, only 0.037 points apart. These near-tangent source commands were excluded by the original nonparallel-only reconciliation. |

All these source strokes have width 0.72 PDF points. The contact limit stays at
0.2 points, below their overlapping painted widths. Ablation against the same
source graph verified that retaining original edges closes the first three
contours; the near-tangent command contact is additionally necessary for LT 25-16.
Rendered 288-DPI source crops with individual polygon overlays were inspected for
all four recovered contours. Their source area/dimension labels remain associated
through the same containment and edge-alignment rules as the other parcels.

## Interaction contract

The server-rendered component contains substantive inline SVG paths grouped by
source block. Select a block, then a lot; native selectors and source-label search
provide an equivalent non-SVG route to every source occurrence, including anomalies.
Pointer drag and arrow keys pan; zoom buttons and +/- zoom; Home, Escape and the
always-visible reset button return to the project. Pan and zoom remain bounded to
the source plan. Selecting a parcel exposes its printed data and opens the existing
project WhatsApp helper with the printed label and unique internal reference.

No inventory statuses or per-lot prices are fabricated. Reduced-motion preferences
are respected. Geometry is memoized independently of the viewBox so panning does not
recreate all parcel elements. Browser interaction, touch behavior and responsive
visual verification remain separate from deterministic data/type checks.

Block badges use translucent circles and numbers, with full contrast on hover or
keyboard focus. Their displayed diameter and type were reduced by 15% in the
owner's 2026-11-11 annotated refinement; block/lot geometry is unchanged.
