import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (name) =>
  readFileSync(
    new URL(`../apps/web/components/crm/${name}`, import.meta.url),
    "utf8",
  );
test("OAuth channel sync is independent of REST configured", () => {
  const source = read("social-panel.tsx");
  const refresh = source.slice(
    source.indexOf("<strong>Canales de la marca</strong>"),
    source.indexOf("Actualizar conexiones"),
  );
  const gating = refresh.slice(0, refresh.indexOf("onClick="));
  assert.match(gating, /settings\?\.can_sync/);
  assert.doesNotMatch(gating, /settings\?\.configured/);
  assert.match(source, /settings.connect_mode === "vendor_dashboard"/);
  assert.match(source, /https:\/\/zernio.com\/dashboard/);
  assert.match(source, /Conectar en Zernio/);
  assert.match(source, /Gestionar en Zernio/);
});
test("MCP successful state changes refresh social settings and shared catalog without GET feedback loops", () => {
  const mcp = read("zernio-mcp.tsx"),
    social = read("social-panel.tsx"),
    modal = read("settings-modal.tsx");
  assert.match(mcp, /onStateChanged/);
  assert.match(social, /onStateChanged=\{reloadAfterMcpChange\}/);
  assert.match(modal, /onStateChanged=\{load\}/);
  assert.equal((mcp.match(/await notifyStateChanged\(\)/g) || []).length, 3);
  for (const operation of ["complete", "check", "disconnect"])
    assert.match(
      mcp,
      new RegExp(`"${operation}"[\\s\\S]{0,700}notifyStateChanged\\(`),
    );
  assert.match(social, /await onStateChanged\?\.\(\)/);
});
test("REST credential and intent flows remain explicit while unauthenticated channels offer MCP authorization", () => {
  const source = read("social-panel.tsx"),
    types = read("social-types.ts");
  assert.match(source, /settings.configured && !replacing/);
  assert.match(source, /api_key: apiKey/);
  assert.match(source, /intent_id: id/);
  assert.match(types, /can_sync: boolean/);
  assert.match(types, /source\?: "rest" \| "oauth"/);
  assert.match(source, /Autorizar Zernio/);
  assert.match(source, /zernio-mcp-heading/);
});

import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url);
const componentRoot = fileURLToPath(
  new URL("../apps/web/components/crm/", import.meta.url),
);
const modules = new Map();
let renderSettings;
let renderOptions;
let stateIndex;
let providerMarkup = null;
function load(path) {
  const absolute = resolve(componentRoot, path);
  if (modules.has(absolute)) return modules.get(absolute).exports;
  const source = readFileSync(absolute, "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  modules.set(absolute, module);
  const scopedRequire = (specifier) => {
    if (specifier.endsWith(".css")) return {};
    if (specifier === "react-dom")
      return {
        createPortal: (node) => {
          providerMarkup = node;
          return null;
        },
      };
    if (specifier === "next/navigation")
      return { useRouter: () => ({ replace() {}, refresh() {} }) };
    if (specifier === "react" && absolute.endsWith("/social-panel.tsx"))
      return {
        ...React,
        useState(initial) {
          const index = stateIndex++;
          return React.useState(
            index === 0
              ? "whatsapp"
              : index === 1
                ? renderSettings
                : index === 2
                  ? false
                  : index === 3
                    ? renderOptions.pending
                    : initial,
          );
        },
      };
    if (specifier.startsWith(".")) {
      const stem = resolve(dirname(absolute), specifier);
      for (const extension of [".tsx", ".ts"]) {
        try {
          readFileSync(stem + extension);
        } catch {
          continue;
        }
        return load(stem + extension);
      }
      throw new Error(`Missing ${specifier}`);
    }
    return require(specifier);
  };
  new Function("require", "module", "exports", code)(
    scopedRequire,
    module,
    module.exports,
  );
  return module.exports;
}
const oauthSettings = () => ({
  configured: false,
  oauth: {
    available: true,
    authorized: true,
    needs_authorization: false,
    verified_at: 1794400000,
  },
  can_sync: true,
  connect_mode: "vendor_dashboard",
  dashboard_url: "https://zernio.com/dashboard",
  profile: null,
  last_sync: null,
  connections: [
    {
      id: "oauth-fixture",
      platform: "whatsapp",
      username: null,
      display_name: "Fixture WhatsApp",
      status: "connected",
      source: "oauth",
    },
  ],
  events: [],
  limitations: { telegram: "code", tiktok: "approval" },
  webhook: { configured: false, path: "" },
  hermes: { connected: false, mode: "manual" },
  sync_warning: null,
});
function renderSocial(
  settings,
  { paused = false, pending = false, providerTarget } = {},
) {
  providerMarkup = null;
  renderSettings = settings;
  renderOptions = { pending };
  stateIndex = 0;
  const { SocialPanel } = load("social-panel.tsx");
  return renderToStaticMarkup(
    React.createElement(SocialPanel, {
      csrf: "fixture",
      providerTarget,
      connections: ["zernio", "whatsapp"].map((key) => ({
        key,
        name: key,
        enabled: !paused,
        available: true,
        effective: true,
        version: 1,
        status: "connected",
      })),
      connectionPending: false,
      onToggleConnection: async () => {},
      onStateChanged: async () => {},
    }),
  );
}
function refreshButton(html) {
  return (
    html.match(/<button[^>]*>Actualizar conexiones<\/button>/)?.[0] ??
    assert.fail("refresh button absent")
  );
}
test("rendered OAuth-only WhatsApp account can refresh and manage in fixed dashboard without REST credentials", () => {
  const html = renderSocial(oauthSettings());
  assert.match(html, /Fixture WhatsApp/);
  assert.match(html, /Conectado · OAuth/);
  assert.doesNotMatch(refreshButton(html), /disabled/);
  assert.match(
    html,
    /<a[^>]+href="https:\/\/zernio.com\/dashboard"[^>]+rel="noopener noreferrer"[^>]*>Gestionar en Zernio<\/a>/,
  );
});
test("rendered REST profile keeps API channel button instead of OAuth vendor handoff", () => {
  const settings = oauthSettings();
  settings.configured = true;
  settings.connect_mode = "api";
  settings.connections = [];
  settings.profile = { id: "fixture", name: "Perfil REST" };
  const html = renderSocial(settings);
  assert.doesNotMatch(refreshButton(html), /disabled/);
  assert.match(html, /aria-label="Conectar WhatsApp"/);
  assert.doesNotMatch(html, /<a[^>]+href="https:\/\/zernio.com\/dashboard"/);
  assert.match(html, /Reemplazar credencial/);
});
test("pause and pending block vendor handoff; unauthenticated channels offer actual authorization control", () => {
  for (const options of [{ paused: true }, { pending: true }]) {
    const html = renderSocial(oauthSettings(), options);
    assert.match(refreshButton(html), /disabled/);
    assert.doesNotMatch(html, /<a[^>]+href="https:\/\/zernio.com\/dashboard"/);
  }
  const settings = oauthSettings();
  settings.oauth.authorized = false;
  settings.oauth.verified_at = null;
  settings.can_sync = false;
  settings.connect_mode = "unavailable";
  settings.connections = [];
  const html = renderSocial(settings);
  assert.match(refreshButton(html), /disabled/);
  assert.match(html, /<button[^>]*>Autorizar Zernio<\/button>/);
  assert.match(html, /id="zernio-authorize"/);
});
test("unverified OAuth snapshots remain visible but never claim connected state", () => {
  const settings = oauthSettings();
  settings.oauth.verified_at = null;
  const html = renderSocial(settings);
  assert.match(html, /Fixture WhatsApp/);
  assert.match(html, /Por verificar · OAuth/);
  assert.doesNotMatch(html, /Conectado · OAuth/);
});

test("failed MCP verification invalidates OAuth-only presentation and reloads sanitized state without success notification", () => {
  const mcp = read("zernio-mcp.tsx"),
    social = read("social-panel.tsx");
  assert.match(mcp, /onStateInvalidated/);
  assert.match(mcp, /refreshAfterFailure/);
  assert.match(social, /onStateInvalidated=\{invalidateAfterMcpFailure\}/);
  assert.match(social, /verified_at: null/);
  assert.match(social, /await reloadAfterMcpChange\(\)/);
});

test("filtered vendor-only account types are informational, not a failed verification", () => {
  const settings = oauthSettings();
  settings.sync_warning = "oauth_unsupported_platforms_filtered";
  const html = renderSocial(settings);
  assert.match(
    html,
    /Otras conexiones de Zernio no forman parte de estas redes sociales/,
  );
  assert.doesNotMatch(
    html,
    /La última consulta no pudo verificar todos los canales/,
  );
  settings.sync_warning = "oauth_verification_required";
  assert.match(
    renderSocial(settings),
    /La última consulta no pudo verificar todos los canales/,
  );
});

test("social channels exclude provider authorization and credentials when Settings supplies its Connections target", () => {
  const settings = oauthSettings();
  const html = renderSocial(settings, { providerTarget: {} });
  assert.match(html, /Canales de la marca/);
  assert.match(html, /Fixture WhatsApp/);
  assert.doesNotMatch(
    html,
    /Acceso a Zernio|social-api-key|Conexión avanzada|Eventos recibidos/,
  );
  assert.ok(providerMarkup, "Provider editor was placed in Connections");
  const provider = renderToStaticMarkup(providerMarkup);
  assert.match(provider, /Acceso a Zernio/);
  assert.match(provider, /Conexión avanzada con API key/);
  assert.match(provider, /Eventos recibidos/);
  assert.doesNotMatch(provider, /Canales de la marca|Fixture WhatsApp/);
});

test("deferred provider target does not mount a second inline authorization consumer", () => {
  const html = renderSocial(oauthSettings(), { providerTarget: null });
  assert.match(html, /Fixture WhatsApp/);
  assert.doesNotMatch(html, /Acceso a Zernio|social-api-key/);
  assert.equal(providerMarkup, null);
});

test("Zernio application row belongs to Connections beside Hermes and ElevenLabs", () => {
  const source = read("settings-modal.tsx");
  const social = source.slice(
    source.indexOf('id="settings-panel-social"'),
    source.indexOf('id="settings-panel-connections"'),
  );
  const connections = source.slice(
    source.indexOf('id="settings-panel-connections"'),
    source.indexOf('id="settings-panel-customizations"'),
  );
  assert.doesNotMatch(social, /map\(connectionRow\)|Acceso a Zernio/);
  assert.match(social, /providerTarget=\{zernioTarget\}/);
  assert.match(connections, /"zernio"/);
  assert.match(connections, /"elevenlabs"/);
  assert.match(connections, /id="zernio-connection-editor"/);
});
