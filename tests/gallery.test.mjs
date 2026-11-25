import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { test } from "node:test";

const source = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("gallery keeps the requested house, roadway, gate and playground order", async () => {
  const content = await source("apps/web/lib/project.ts");
  const names = [...content.matchAll(/name: "(casa-construida|vias-actuales|porteria-actual|parque-infantil)"/g)].map(match => match[1]);
  assert.deepEqual(names, ["casa-construida", "vias-actuales", "porteria-actual", "parque-infantil"]);
});

test("gallery videos load only when opened and stop on close or navigation", async () => {
  const content = await source("apps/web/components/landing-interactions.tsx");
  assert.match(content, /isOpen && selected\.type === "video"/);
  assert.match(content, /onClose=\{\(\) => setIsOpen\(false\)\}/);
  assert.match(content, /key=\{selected\.name\}/);
  assert.match(content, /preload="metadata"/);
  assert.match(content, /controls/);
  assert.doesNotMatch(content.split("export function ArchitecturalFilm")[0], /autoPlay/);
  assert.match(content, /event\.target instanceof HTMLVideoElement/);
  assert.match(content, /Cerrar galería/);
});

test("optimized gallery files exist within the web delivery budget", async () => {
  for (const name of ["casa-construida", "parque-infantil"]) {
    const file = await stat(new URL(`../apps/web/public/media/${name}.mp4`, import.meta.url));
    assert.ok(file.size > 10000 && file.size < 4_000_000, name);
    assert.ok((await stat(new URL(`../apps/web/public/media/${name}-poster.webp`, import.meta.url))).size > 0);
  }
  for (const name of ["vias-actuales", "porteria-actual"]) {
    for (const width of [640, 1280]) {
      assert.ok((await stat(new URL(`../apps/web/public/media/${name}-${width}.webp`, import.meta.url))).size > 0);
    }
  }
});

test("the event and contact draft retain the corrected venue and Sara welcomes the new campaign", async () => {
  const event = await source("apps/web/lib/soacha-event.ts");
  const welcome = await source("apps/api/app/social/onboarding.py");
  assert.equal((event.match(/Cámara de Comercio de Bogotá en Soacha/g) ?? []).length, 2);
  assert.match(welcome, /domingo veintinueve de noviembre/);
  for (const content of [event, welcome]) assert.doesNotMatch(content, /Cámara de Comercio de Soacha/);
});

// Both portrait posters and landscape photos fill tiles without changing grid rows.
test("mixed-media thumbnails do not impose their intrinsic aspect ratio on the grid", async () => {
  const css = await source("apps/web/app/landing.css");
  assert.match(css, /\.landing \.photo-tile picture\s*\{[^}]*position: absolute;[^}]*inset: 0;/);
});
