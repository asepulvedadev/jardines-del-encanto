import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { stages, labels } from "../apps/web/components/crm/types.ts";

test("pipeline has only Nuevo, Contactado and Ganado in its shared UI contract", () => {
  assert.deepEqual(stages, [
    ["new", "Nuevo"],
    ["contacted", "Contactado"],
    ["won", "Ganado"],
  ]);
  assert.equal(labels.pipeline, "Pipeline");
});
test("the shared page heading no longer has the duplicate Nuevo cliente action", () => {
  const source = readFileSync(
    new URL("../apps/web/components/crm/workspace.tsx", import.meta.url),
    "utf8",
  );
  const heading = source.slice(
    source.indexOf('<div className="crm-page-heading">'),
    source.indexOf(
      "{error && (",
      source.indexOf('<div className="crm-page-heading">'),
    ),
  );
  assert.doesNotMatch(heading, /Nuevo cliente/);
  assert.match(source, /Crear cliente en Nuevo/);
  const parts = readFileSync(
    new URL("../apps/web/components/crm/workspace-parts.tsx", import.meta.url),
    "utf8",
  );
  assert.match(parts, /Crear primer cliente/);
});
