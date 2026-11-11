import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import test from "node:test";
const data = JSON.parse(
  readFileSync(
    new URL("../apps/web/lib/masterplan-data.json", import.meta.url),
    "utf8",
  ),
);
test("all source label occurrences have unique internal identity", () => {
  assert.equal(
    data.metadata.sourceSha256,
    "e80b746e47b808f077432a61a6794993205a244e896667b2e16d51feb416f74d",
  );
  assert.equal(data.lots.length, 1568);
  assert.equal(new Set(data.lots.map((l) => l.id)).size, 1568);
  assert.equal(data.blocks.length, 55);
  assert.ok(
    data.lots.every(
      (l) => l.sourceLabel && data.blocks.some((b) => b.id === l.blockId),
    ),
  );
});
test("finite source geometry and bounds remain separate from unresolved entries", () => {
  for (const lot of data.lots) {
    assert.ok(lot.center.every(Number.isFinite));
    if (!lot.path) {
      assert.equal(lot.geometrySource, "unresolved");
      continue;
    }
    assert.match(lot.path, /^M/);
    assert.ok(!/NaN|Infinity/.test(lot.path));
    assert.ok(lot.bounds.every(Number.isFinite));
    assert.ok(lot.bounds[0] < lot.bounds[2] && lot.bounds[1] < lot.bounds[3]);
    assert.match(lot.geometrySource, /^source-vector/);
  }
});
test("areas and dimensions have explicit source provenance", () => {
  const one = data.lots.find((l) => l.sourceLabel === "LT 1-1");
  assert.equal(one.areaM2, 239.81);
  assert.equal(one.areaSource, "printed-pdf-label");
  assert.ok(
    one.measurements.some(
      (m) => m.value === "22.80" && m.source === "printed-pdf-edge-label",
    ),
  );
  for (const lot of data.lots) {
    if (lot.areaM2 !== null) assert.equal(lot.areaSource, "printed-pdf-label");
    assert.ok(
      lot.measurements.every(
        (m) => m.source === "printed-pdf-edge-label" && Number(m.value) > 0,
      ),
    );
    assert.equal(lot.availability, undefined);
  }
});
test("duplicate and malformed printed identifiers are preserved and flagged", () => {
  for (const label of ["LT 24-3", "LT 24-4", "LT 24-5", "LT 31-42"]) {
    const rows = data.lots.filter((l) => l.sourceLabel === label);
    assert.equal(rows.length, 2);
    assert.ok(
      rows.every((l) => l.anomalies.includes("duplicate-source-label")),
    );
  }
  assert.ok(
    data.lots
      .find((l) => l.sourceLabel === "LT 1018")
      .anomalies.includes("malformed-source-label"),
  );
  assert.ok(data.lots.some((l) => l.sourceLabel === "LT 44-16a"));
  assert.ok(data.blocks.some((b) => b.id === "21a"));
});
test("the SSR component contains individual inline vector paths and non-SVG selection", () => {
  const src = readFileSync(
    new URL("../apps/web/components/masterplan-explorer.tsx", import.meta.url),
    "utf8",
  );
  assert.match(src, /data-plan-explorer/);
  assert.match(src, /data-masterplan/);
  assert.match(src, /<path/);
  assert.match(src, /<select/);
  assert.match(src, /whatsappLink/);
  assert.doesNotMatch(src, /\.pdf["']/);
});

test("every printed parcel has an individual source-vector contour", () => {
  assert.equal(data.metadata.resolvedGeometry, 1568);
  assert.equal(data.metadata.unresolvedGeometry, 0);
  assert.equal(new Set(data.lots.map((lot) => lot.path)).size, 1568);
  for (const label of ["LT 25-11", "LT 25-16", "LT 26-26", "LT 26-8"]) {
    const lot = data.lots.find((row) => row.sourceLabel === label);
    assert.ok(lot.path, `${label} must retain its actual source contour`);
    assert.match(lot.geometrySource, /^source-vector/);
    assert.ok(!lot.anomalies.includes("unresolved-source-boundary"));
    assert.ok(lot.measurements.length >= 3);
    assert.ok(lot.measurements.every((m) => m.source === "printed-pdf-edge-label"));
  }
  assert.equal(data.metadata.sourceAreaLabels, 1570);
  for (const lot of data.lots) {
    if (lot.areaM2 !== null) {
      assert.match(lot.areaLabel, /^A:/);
      assert.ok(lot.areaPosition.every(Number.isFinite));
    }
  }
});

test("contact recovery preserves the prior 1,564 audited parcel paths", () => {
  const recovered = new Set(["LT 25-11", "LT 25-16", "LT 26-26", "LT 26-8"]);
  const prior = data.lots.filter((lot) => !recovered.has(lot.sourceLabel));
  assert.equal(prior.length, 1564);
  assert.equal(
    createHash("sha256")
      .update(JSON.stringify(prior.map((lot) => [lot.id, lot.path])))
      .digest("hex"),
    "2d02a8620b39dc4e434a61436db01ce3beae1f554d7d959033f8f8f1913f372f",
  );
  assert.equal(data.metadata.contactRecoveredGeometry, 4);
  const sourceBounds = {
    "LT 26-8": [125.219, 1750.921, 171.237, 1815.114],
    "LT 26-26": [227.891, 2061.961, 291.96, 2134.68],
    "LT 25-11": [461.882, 1995.25, 489.826, 2056.88],
    "LT 25-16": [533.376, 2042.64, 586.436, 2104.283],
  };
  for (const lot of data.lots.filter((row) => recovered.has(row.sourceLabel))) {
    assert.deepEqual(lot.bounds, sourceBounds[lot.sourceLabel]);
    assert.equal(lot.geometrySource, "source-vector-stroke-contact-reconciled");
    assert.ok((lot.path.match(/L/g) || []).length > 4);
  }
});

test("unitless printed area text is retained without inventing square metres", () => {
  const cases = [
    ["source-lot-0675", "LT 17-7", "A: 180.00", [1170.003, 1533.008]],
    ["source-lot-0834", "LT 26-3", "A: 160.58", [185.828, 1633.755]],
  ];
  for (const [id, label, raw, position] of cases) {
    const lot = data.lots.find((row) => row.id === id);
    assert.equal(lot.sourceLabel, label);
    assert.equal(lot.areaM2, null);
    assert.equal(lot.areaLabel, raw);
    assert.deepEqual(lot.areaPosition, position);
    assert.equal(lot.areaSource, "printed-pdf-label-without-unit");
    assert.ok(lot.anomalies.includes("source-area-unit-missing"));
  }
  assert.equal(data.metadata.parseableAreaLabels, 1568);
});

test("SVG titles have a single string child for hydration-safe React rendering", async () => {
  const { default: ts } = await import("typescript");
  const source = readFileSync(
    new URL("../apps/web/components/masterplan-explorer.tsx", import.meta.url),
    "utf8",
  );
  const tree = ts.createSourceFile(
    "masterplan-explorer.tsx",
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  let titleCount = 0;
  function visit(node) {
    if (
      ts.isJsxElement(node) &&
      node.openingElement.tagName.getText(tree) === "title"
    ) {
      titleCount++;
      const children = node.children.filter(
        (child) => !ts.isJsxText(child) || child.text.trim(),
      );
      assert.equal(
        children.length,
        1,
        "SVG title must have exactly one string expression/text child",
      );
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.ok(titleCount >= 3);
});
