import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { leadCohortFilter } from "../../apps/web/components/crm/broadcast-model.ts";

const require = createRequire(import.meta.url);
const module = { exports: {} };
const code = ts.transpileModule(readFileSync(new URL("../../apps/web/components/crm/lead-origins.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
new Function("require", "module", "exports", code)((name) => {
  if (name.endsWith(".css")) return {};
  if (name === "./types") return require("../../apps/web/components/crm/types.ts");
  return require(name);
}, module, module.exports);
const { LeadOrigins } = module.exports;
const origins = { campaign: 246, template: 56, imported: 0, other: 121, other_sources: [{ source: "whatsapp", count: 100 }, { source: "web", count: 21 }] };
const render = (extra = {}) => renderToStaticMarkup(React.createElement(LeadOrigins, { total: 423, origins, onSelect() {}, pending: false, ...extra }));

test("all contacts reconcile with four named groups and readable source detail", () => {
  const html = render();
  for (const text of ["De dónde vienen tus clientes", "Campañas y redes", "Respuestas a templates", "Base importada", "Otros orígenes", "246", "56", "121", "423", "Página web", "WhatsApp", "Cómo se clasifican"]) assert.ok(html.includes(text), text);
  assert.equal((html.match(/>Ver clientes /g) ?? []).length, 4);
  assert.match(html, /No confirma atribución a un anuncio pagado/);
  assert.match(html, /No incluye destinatarios que no respondieron/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test("zero and unavailable or inconsistent totals are never confused", () => {
  assert.match(render({ total: 0, origins: { campaign: 0, template: 0, imported: 0, other: 0, other_sources: [] } }), /Aún no hay clientes registrados/);
  for (const value of [undefined, { ...origins, other: 1 }, { ...origins, imported: -1 }, { ...origins, other_sources: [] }]) {
    const html = render({ origins: value });
    assert.match(html, /Desglose no disponible/);
    assert.doesNotMatch(html, /Ver clientes/);
  }
});

test("each card opens its exact server cohort and pending requests disable actions", () => {
  const selected = [];
  const tree = LeadOrigins({ total: 423, origins, onSelect: (key) => selected.push(key), pending: false });
  function visit(node) {
    if (!node || typeof node !== "object") return;
    if (node.type === "button") node.props.onClick();
    React.Children.forEach(node.props?.children, visit);
  }
  visit(tree);
  assert.deepEqual(selected, ["campaign", "template", "imported", "other"]);
  for (const cohort of selected) assert.deepEqual(leadCohortFilter(cohort), { cohort });
  assert.equal((render({ pending: true }).match(/disabled=""/g) ?? []).length, 4);
  assert.deepEqual(leadCohortFilter("cold"), { cold_only: true });
  assert.deepEqual(leadCohortFilter("a-real-broadcast-id"), { campaign_id: "a-real-broadcast-id" });
});
