import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const path = fileURLToPath(new URL("../../apps/web/components/crm/analytics-panel.tsx", import.meta.url));
const module = { exports: {} };
const code = ts.transpileModule(readFileSync(path, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;
new Function("require", "module", "exports", code)((name) => {
  if (name.endsWith(".css")) return {};
  if (name === "next/navigation") return { useRouter: () => ({ replace() {} }) };
  return require(name);
}, module, module.exports);
const { AnalyticsSummary, parseAnalyticsSummary, analyticsChartBars } = module.exports;
const fixture = {
  status: "ready", timezone: "America/Bogota", days: 7, updated_at: "2026-11-16T15:00:00Z",
  totals: { visitors: 41, sessions: 52, pageviews: 83, clicks: 19, registrations: 8 },
  daily: [
    { date: "2026-11-15", pageviews: 0, sessions: 0, registrations: 0 },
    { date: "2026-11-16", pageviews: 83, sessions: 52, registrations: 8 },
  ],
  events: [{ name: "whatsapp_click", count: 19 }], sources: [{ name: "facebook", count: 30 }],
};
const render = (data, extra = {}) => renderToStaticMarkup(React.createElement(AnalyticsSummary, { data, loading: false, error: "", days: 7, onDaysChange() {}, onRetry() {}, ...extra }));

test("dashboard analytics renders actual counts, named controls, chart and accessible daily table", () => {
  const html = render(parseAnalyticsSummary(fixture, 7));
  for (const value of ["Rendimiento de la landing", "Visitantes", "Vistas de página", "Clics", "Leads web", "83", "41", "19", "8", "Facebook", "WhatsApp", "Ver datos por día"]) assert.ok(html.includes(value), value);
  assert.match(html, /role="img"/);
  assert.match(html, /<table/);
  assert.match(html, /aria-pressed="true">7 días/);
  assert.doesNotMatch(html, /Lo que sigue|NaN|Infinity/);
});

test("missing tracker is not reported as zero and real CRM registrations remain visible", () => {
  const missing = { ...fixture, status: "not_configured", totals: { visitors: null, sessions: null, pageviews: null, clicks: null, registrations: 8 }, daily: fixture.daily.map((day) => ({ ...day, pageviews: null, sessions: null })), events: [], sources: [] };
  const html = render(parseAnalyticsSummary(missing, 7));
  assert.match(html, /Medición de visitas pendiente/);
  assert.match(html, /No disponible/);
  assert.match(html, /Leads web/);
  assert.match(html, />8<\/strong>/);
  assert.doesNotMatch(html, /<svg/);
});

test("all real zero values are displayed as zero without invented chart bars", () => {
  const zero = { ...fixture, totals: { visitors: 0, sessions: 0, pageviews: 0, clicks: 0, registrations: 0 }, daily: fixture.daily.map((day) => ({ ...day, pageviews: 0, sessions: 0, registrations: 0 })), events: [], sources: [] };
  const html = render(parseAnalyticsSummary(zero, 7));
  assert.match(html, /Aún no hay actividad registrada/);
  assert.ok(analyticsChartBars(zero.daily).every((bar) => bar.height === 0));
});

test("chart geometry preserves missing values, zeros and proportional counts", () => {
  const bars = analyticsChartBars([{ date: "2026-11-14", pageviews: null }, { date: "2026-11-15", pageviews: 0 }, { date: "2026-11-16", pageviews: 10 }, { date: "2026-11-17", pageviews: 20 }]);
  assert.equal(bars[0].height, null);
  assert.equal(bars[1].height, 0);
  assert.equal(bars[2].height * 2, bars[3].height);
});

test("summary parser fails closed on malformed, non-finite or mismatched period responses", () => {
  for (const value of [null, {}, { ...fixture, days: 30 }, { ...fixture, totals: { ...fixture.totals, visitors: -1 } }, { ...fixture, daily: [{ ...fixture.daily[0], date: "2026-99-01" }] }, { ...fixture, events: [{ name: "test", count: Infinity }] }]) assert.throws(() => parseAnalyticsSummary(value, 7));
});

test("loading and failed requests have explicit live feedback and recovery without fake data", () => {
  assert.match(render(null, { loading: true }), /Cargando métricas/);
  const failed = render(null, { error: "No se pudieron cargar las métricas." });
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Reintentar/);
  assert.doesNotMatch(failed, /<svg/);
  const unavailable = render({ ...fixture, status: "unavailable" });
  assert.match(unavailable, /Medición temporalmente no disponible/);
});

function hookHarness() {
  const state = [], refs = [], effects = [], redirects = [];
  let stateIndex = 0, refIndex = 0;
  const ReactHooks = {
    ...React,
    useState(initial) { const index = stateIndex++; if (!(index in state)) state[index] = initial; return [state[index], (value) => { state[index] = typeof value === "function" ? value(state[index]) : value; }]; },
    useRef(initial) { const index = refIndex++; return refs[index] ??= { current: initial }; },
    useEffect(effect) { effects.push(effect); },
  };
  const router = { replace(path) { redirects.push(path); } };
  const isolated = { exports: {} };
  new Function("require", "module", "exports", code)((name) => {
    if (name.endsWith(".css")) return {};
    if (name === "react") return ReactHooks;
    if (name === "next/navigation") return { useRouter: () => router };
    return require(name);
  }, isolated, isolated.exports);
  return { state, effects, redirects, render() { stateIndex = 0; refIndex = 0; return isolated.exports.AnalyticsPanel(); } };
}
const settle = async () => { for (let index = 0; index < 8; index++) await Promise.resolve(); };

test("live analytics fetches automatically, prevents overlaps and ignores stale period results", async () => {
  const previous = { fetch: globalThis.fetch, document: globalThis.document, window: globalThis.window };
  const requests = [], listeners = new Map(), intervals = new Map(), timeouts = new Map();
  let nextTimer = 0;
  globalThis.fetch = (url, options) => new Promise((resolve) => requests.push({ url, options, resolve }));
  globalThis.document = { visibilityState: "visible", addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener: (name) => listeners.delete(name) };
  globalThis.window = { setTimeout: (fn, delay) => { timeouts.set(++nextTimer, { callback: fn, delay }); return nextTimer; }, clearTimeout: (id) => timeouts.delete(id), setInterval: (fn) => { intervals.set(++nextTimer, fn); return nextTimer; }, clearInterval: (id) => intervals.delete(id) };
  let cleanup;
  try {
    const harness = hookHarness();
    let result = harness.render();
    cleanup = harness.effects.pop()();
    assert.equal(requests.length, 1);
    assert.equal([...timeouts.values()][0].delay, 25_000);
    assert.equal(requests[0].url, "/api/crm/analytics/summary?days=7");
    assert.equal(requests[0].options.credentials, "same-origin");
    assert.equal(requests[0].options.cache, "no-store");
    for (const refresh of intervals.values()) refresh();
    listeners.get("visibilitychange")();
    assert.equal(requests.length, 1, "busy fetch cannot overlap a refresh");
    result.props.onDaysChange(30);
    cleanup();
    assert.equal(requests[0].options.signal.aborted, true);
    result = harness.render();
    cleanup = harness.effects.pop()();
    assert.equal(requests[1].url, "/api/crm/analytics/summary?days=30");
    requests[0].resolve({ ok: true, status: 200, json: async () => fixture });
    await settle();
    assert.equal(harness.state[2], null, "stale first request does not populate the selected period");
    requests[1].resolve({ ok: true, status: 200, json: async () => ({ ...fixture, days: 30 }) });
    await settle();
    assert.equal(harness.state[2].days, 30);
    globalThis.document.visibilityState = "hidden";
    for (const refresh of intervals.values()) refresh();
    assert.equal(requests.length, 2, "hidden dashboard does not poll");
    globalThis.document.visibilityState = "visible";
    listeners.get("visibilitychange")();
    assert.equal(requests.length, 3);
    requests[2].resolve({ ok: false, status: 401 });
    await settle();
    assert.deepEqual(harness.redirects, ["/login"]);
    cleanup();
    assert.equal(intervals.size, 0);
    assert.equal(listeners.size, 0);
  } finally {
    cleanup?.();
    Object.assign(globalThis, previous);
  }
});

test("failed live requests expose recovery and retry can return genuine zero measurements", async () => {
  const previous = { fetch: globalThis.fetch, document: globalThis.document, window: globalThis.window };
  const requests = [];
  globalThis.fetch = () => new Promise((resolve, reject) => requests.push({ resolve, reject }));
  globalThis.document = { visibilityState: "visible", addEventListener() {}, removeEventListener() {} };
  globalThis.window = { setTimeout: () => 1, clearTimeout() {}, setInterval: () => 2, clearInterval() {} };
  let cleanup;
  try {
    const harness = hookHarness();
    harness.render();
    cleanup = harness.effects.pop()();
    requests[0].reject(new Error("offline"));
    await settle();
    let result = harness.render();
    assert.equal(result.props.loading, false);
    assert.equal(result.props.data, null);
    assert.equal(result.props.error, "No se pudieron cargar las métricas.");
    result.props.onRetry();
    cleanup();
    harness.effects.length = 0;
    harness.render();
    cleanup = harness.effects.pop()();
    requests[1].resolve({ ok: true, status: 200, json: async () => ({ ...fixture, totals: { visitors: 0, sessions: 0, pageviews: 0, clicks: 0, registrations: 0 }, daily: fixture.daily.map((day) => ({ ...day, pageviews: 0, sessions: 0, registrations: 0 })), events: [], sources: [] }) });
    await settle();
    result = harness.render();
    assert.equal(result.props.error, "");
    assert.equal(result.props.loading, false);
    assert.equal(result.props.data.totals.pageviews, 0);
    assert.equal(result.props.data.totals.registrations, 0);
  } finally {
    cleanup?.();
    Object.assign(globalThis, previous);
  }
});


test("collector actions and source buckets use concise Spanish labels without recomputing totals", () => {
  const html = render({ ...fixture, totals: { ...fixture.totals, clicks: 123 }, events: ["whatsapp_click", "group_click", "visit_click", "plan_open", "registration_open"].map((name, index) => ({ name, count: index + 1 })), sources: [{ name: "whatsapp", count: 7 }, { name: "other", count: 2 }] });
  for (const label of ["WhatsApp", "Grupo de WhatsApp", "Agendar visita", "Explorar plano", "Abrir registro", "Otros", "123"]) assert.ok(html.includes(label), label);
  assert.doesNotMatch(html, />other</);
});

test("small screens keep chart labels readable inside a keyboard-accessible local scroll region", () => {
  const html = render(fixture);
  assert.match(html, /class="crm-analytics-plot"[^>]*tabindex="0"[^>]*role="region"[^>]*aria-label="Gráfico desplazable de vistas por día"/);
  const css = readFileSync(new URL("../../apps/web/components/crm/analytics-panel.css", import.meta.url), "utf8");
  assert.match(css, /\.crm-analytics-plot\s*\{[^}]*overflow-x:\s*auto/);
  assert.match(css, /\.crm-analytics-chart svg\s*\{[^}]*min-width:\s*520px/);
  assert.match(css, /\.crm-analytics-chart svg text\s*\{[^}]*font:\s*12px/);
});
