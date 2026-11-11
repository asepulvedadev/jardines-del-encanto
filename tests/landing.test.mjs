import assert from "node:assert/strict";
import { test } from "node:test";

const base = process.env.LANDING_BASE_URL ?? "http://127.0.0.1:4317";

test("the public landing renders the supplied offer and correct WhatsApp destination", async () => {
  const response = await fetch(base);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /lang="es-CO"/);
  assert.match(html, /13 millones/);
  assert.match(html, /7 × 14/);
  assert.match(html, /24 meses/);
  assert.match(html, /https:\/\/wa\.me\/573008348478\?text=/);
  assert.match(html, /Visualización arquitectónica/);
  assert.match(html, /no refleja disponibilidad en tiempo real/);
  assert.doesNotMatch(html, /The project foundation is ready/);
});

test("actual media, architectural film and original PDF are served", async () => {
  for (const [path, type] of [
    ["/media/aerial-960.webp", "image/webp"],
    ["/media/entrance-960.webp", "image/webp"],
    ["/media/neighborhood-960.webp", "image/webp"],
    ["/media/gate-960.webp", "image/webp"],
    ["/media/masterplan.webp", "image/webp"],
    ["/media/plano-jardines-del-encanto.pdf", "application/pdf"],
    ["/media/recorrido-arquitectonico.mp4", "video/mp4"],
  ]) {
    const response = await fetch(`${base}${path}`, { method: "HEAD" });
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get("content-type"), new RegExp(type));
    assert.ok(Number(response.headers.get("content-length")) > 0, path);
  }
});

test("existing infrastructure health contract and security headers remain intact", async () => {
  const response = await fetch(`${base}/health`);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, "ok");
  const page = await fetch(base);
  assert.equal(page.headers.get("x-frame-options"), "DENY");
  assert.equal(page.headers.get("x-content-type-options"), "nosniff");
});

test("redesigned landing exposes hero film, transparent daily cycle and an inline lot explorer", async () => {
  const html = await (await fetch(base)).text();
  assert.match(html, /Precio de lanzamiento/);
  assert.match(html, /Quiero mi cupo/);
  assert.match(html, /data-hero-film/);
  assert.match(html, /data-launch-cycle/);
  assert.doesNotMatch(html, /Ciclo diario/);
  assert.doesNotMatch(html, /ACACÍAS, META/);
  assert.match(html, /aria-label="Contador de 24 horas"/);
  assert.doesNotMatch(html, /El contador se reinicia|No indica el vencimiento/);
  assert.match(html, /data-plan-explorer/);
  assert.match(html, /<svg[^>]+data-masterplan/);
  assert.doesNotMatch(html, /Descargar plano PDF/);
});

test("the landing has a dismissible named cupo form with explicit contact consent", async () => {
  const html = await (await fetch(base)).text();
  assert.match(html, /lead-capture-title/);
  assert.match(html, /Nombre completo/);
  assert.match(html, /Número de celular/);
  assert.match(html, /Autorizo a Jardines del Encanto/);
  assert.match(html, /name="consent"/);
  assert.doesNotMatch(html, /No hay formularios de captación/);
});
