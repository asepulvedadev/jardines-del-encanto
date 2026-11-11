import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import test from "node:test";
const read = (name) =>
  readFileSync(
    new URL(`../apps/web/components/crm/${name}`, import.meta.url),
    "utf8",
  );
test("settings uses a named native modal without replacing CRM navigation", () => {
  const modal = read("settings-modal.tsx"),
    workspace = read("workspace.tsx");
  assert.match(modal, /<dialog/);
  assert.match(modal, /aria-labelledby="settings-title"/);
  assert.match(modal, /role="tablist"/);
  assert.match(modal, /ArrowRight/);
  assert.match(modal, /hidden=\{tab !== "social"\}/);
  assert.doesNotMatch(workspace, /setView\("settings"\)/);
  assert.match(workspace, /social_intent/);
  assert.match(workspace, /zernio_callback/);
});
test("shared settings use optimistic server versions and disabled creation", () => {
  const modal = read("settings-modal.tsx"),
    custom = read("customizations.tsx");
  assert.match(modal, /version: connection.version/);
  assert.match(custom, /enabled: false/);
  assert.match(custom, /version: editor.version/);
  assert.match(custom, /steps/);
  assert.match(custom, /input_schema/);
});
test("Hermes requires explicit proposal decisions and renders exact arguments", () => {
  const code = read("hermes-panel.tsx");
  assert.match(code, /hermes\/chat/);
  assert.match(code, /JSON.stringify\(proposal.arguments/);
  assert.match(code, /approve/);
  assert.match(code, /reject/);
  assert.match(code, /version: proposal.version/);
  assert.doesNotMatch(code, /dangerouslySetInnerHTML/);
});

// Render actual TSX without a bundler or browser; effects remain intentionally inactive.
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url);
const cache = new Map();
function loadComponent(path) {
  const absolute = resolve(
    fileURLToPath(new URL("../apps/web/components/crm/", import.meta.url)),
    path,
  );
  if (cache.has(absolute)) return cache.get(absolute).exports;
  const source = readFileSync(absolute, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  cache.set(absolute, module);
  const scopedRequire = (specifier) => {
    if (specifier.endsWith(".css")) return {};
    if (specifier === "next/navigation")
      return { useRouter: () => ({ replace() {}, refresh() {} }) };
    if (specifier.startsWith(".")) {
      const stem = resolve(dirname(absolute), specifier);
      let target;
      for (const ext of [".tsx", ".ts"]) {
        try {
          readFileSync(stem + ext);
          target = stem + ext;
          break;
        } catch {}
      }
      if (!target) throw new Error(`Missing component: ${specifier}`);
      return loadComponent(target);
    }
    return require(specifier);
  };
  new Function("require", "module", "exports", compiled)(
    scopedRequire,
    module,
    module.exports,
  );
  return module.exports;
}
test("rendered switch exposes checked, disabled and labeled state", () => {
  const { SettingsSwitch } = loadComponent("integration-icon.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SettingsSwitch, {
      name: "Activar Hermes",
      checked: false,
      disabled: true,
      onChange() {},
    }),
  );
  assert.match(html, /role="switch"/);
  assert.match(html, /aria-checked="false"/);
  assert.match(html, /aria-label="Activar Hermes"/);
  assert.match(html, /disabled=""/);
});
test("rendered modal exposes three associated keyboard tabs and no fake connected status", () => {
  const { SettingsModal } = loadComponent("settings-modal.tsx");
  const html = renderToStaticMarkup(
    React.createElement(SettingsModal, {
      open: false,
      csrf: "fixture",
      onClose() {},
      onWorkspaceChanged: async () => {},
    }),
  );
  assert.match(html, /<dialog[^>]+aria-labelledby="settings-title"/);
  assert.equal((html.match(/role="tab"/g) || []).length, 3);
  assert.equal((html.match(/role="tabpanel"/g) || []).length, 3);
  for (const label of ["Redes sociales", "Conexiones", "Customizaciones"])
    assert.ok(html.includes(label));
  assert.doesNotMatch(html, /Conectado|Disponible para Hermes/);
});
test("rendered proposals retain exact arguments and approval remains separate from results", () => {
  const { ActionProposals } = loadComponent("hermes-panel.tsx");
  const html = renderToStaticMarkup(
    React.createElement(ActionProposals, {
      proposals: [
        {
          id: "fixture",
          action: "crm.note.create",
          arguments: {
            deal_id: "123",
            body: "<script>not executable</script>",
          },
          status: "pending",
          version: 2,
        },
      ],
      request: async () => {},
      onChanged: async () => {},
    }),
  );
  assert.match(html, /Pendiente de revisión/);
  assert.match(html, /Aprobar acción exacta/);
  assert.match(html, /Rechazar/);
  assert.match(html, /crm.note.create/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});
test("social callback is captured and scrubbed before settings fetch and never remounted per tab", () => {
  const social = read("social-panel.tsx"),
    modal = read("settings-modal.tsx");
  assert.ok(
    social.indexOf("window.history.replaceState") <
      social.indexOf('request<SocialSettings>("settings", "GET"'),
  );
  assert.match(social, /callbackCaptured.current/);
  assert.equal((modal.match(/<SocialPanel/g) || []).length, 1);
  assert.doesNotMatch(modal, /tab === "social" &&/);
  assert.match(modal, /credentials: "same-origin"/);
  assert.match(modal, /X-CSRF-Token/);
  assert.match(modal, /65536/);
});

test("modal explicitly restores centering and readable forms after app resets", () => {
  const css = readFileSync(
    new URL("../apps/web/app/crm/settings.css", import.meta.url),
    "utf8",
  );
  assert.match(css, /\.crm-shell \.settings-modal\s*\{\s*margin: auto;/);
  assert.match(
    css,
    /\.crm-shell \.settings-body textarea\s*\{\s*min-height: 120px;/,
  );
  assert.match(css, /font-size: 16px/);
  assert.match(css, /prefers-reduced-motion/);
});

test("external dispatch uncertainty is not presented as confirmed execution", () => {
  const { ActionResultDetails } = loadComponent("hermes-panel.tsx");
  for (const status of ["external_outcome_unconfirmed", "dispatch_reserved"]) {
    const html = renderToStaticMarkup(
      React.createElement(ActionResultDetails, {
        result: { status, retryable: false },
      }),
    );
    assert.match(html, /Resultado externo no confirmado/);
    assert.match(html, /No repitas la acción/);
    assert.doesNotMatch(html, /Resultado confirmado|<button/);
  }
  const modal = read("settings-modal.tsx");
  assert.match(modal, /El servidor ya respondió a la acción/);
  assert.match(modal, /old.items.some/);
});

test("Hermes edit opens a persistent editor and focuses its prompt", () => {
  const modal = read("settings-modal.tsx");
  assert.match(modal, /id="hermes-connection-editor"/);
  assert.match(modal, /hidden=\{editingConnection !== "hermes"\}/);
  assert.match(modal, /prompt\?\.focus\(\)/);
  assert.equal((modal.match(/<HermesPanel/g) || []).length, 1);
});
