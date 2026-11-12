import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url);
for (const ext of [".tsx", ".ts"])
  require.extensions[ext] = (module, file) =>
    module._compile(
      ts.transpileModule(readFileSync(file, "utf8"), {
        compilerOptions: {
          target: ts.ScriptTarget.ES2022,
          module: ts.ModuleKind.CommonJS,
          jsx: ts.JsxEmit.ReactJSX,
        },
      }).outputText,
      file,
    );
const {
  ActionOutput,
  ActionProposals,
  ActionResultDetails,
} = require("../../apps/web/components/crm/hermes-panel.tsx");
const render = (component, props) =>
  renderToStaticMarkup(React.createElement(component, props));
const proposal = {
  id: "fixture",
  action: "retell.execute",
  status: "pending",
  version: 7,
  requirements: { consent: true, kind: "operation" },
  arguments: {
    endpoint: "updateAgent",
    arguments: {
      agent_id: "agent-B",
      requestBody: {
        agent_name: "<script>never execute</script>",
        general_prompt: "Full instructions\n" + "x".repeat(3500),
        response_engine: { type: "retell-llm", llm_id: "llm-existing" },
        enabled: false,
        probability: 0,
        nullable: null,
        empty_text: "",
        empty_array: [],
        empty_object: {},
        nested: [
          { recipient: "+15555555555", active: true },
          "second exact value",
        ],
      },
    },
    contacts: [{ contact_id: "customer-1", expected_phone: "+15555555555" }],
  },
};
const shared = { request: async () => ({}), onChanged: async () => {} };
function visible(html) {
  return html.replace(
    /<details class="voice-technical">[\s\S]*?<\/details>/g,
    "",
  );
}
test("friendly Retell proposal exposes every nested value without default JSON or clipping", () => {
  const html = render(ActionProposals, {
    ...shared,
    proposals: [proposal],
    presentation: "friendly",
  });
  const main = visible(html);
  assert.match(main, /Editar agente/);
  assert.doesNotMatch(main, /<pre/);
  for (const value of [
    "agent-B",
    "llm-existing",
    "customer-1",
    "+15555555555",
    "second exact value",
    "x".repeat(3500),
  ])
    assert.ok(main.includes(value), value.slice(0, 30));
  for (const value of [
    "No",
    "Sí",
    "Sin valor",
    "Texto vacío",
    "Lista vacía",
    "Objeto vacío",
  ])
    assert.ok(main.includes(value), value);
  assert.ok(main.includes("&lt;script&gt;never execute&lt;/script&gt;"));
  assert.doesNotMatch(main, /<script>/);
  assert.match(
    html,
    /<details class="voice-technical"><summary>Detalles técnicos<\/summary><pre/,
  );
  assert.ok(html.includes("Aprobar acción exacta"));
  assert.match(html, /type="checkbox"/);
  assert.doesNotMatch(html, /<details[^>]*open/);
});
test("friendly results show readable statuses and all fields with technical JSON closed", () => {
  for (const status of [
    "completed",
    "external_outcome_unconfirmed",
    "dispatch_reserved",
    "ready",
  ]) {
    const html = render(ActionResultDetails, {
      ...shared,
      presentation: "friendly",
      result: {
        provider: "retell",
        endpoint: "getAgent",
        status,
        data: { agent_id: "agent-B", voice_id: "voice-one" },
      },
    });
    assert.doesNotMatch(visible(html), /<pre/);
    assert.ok(visible(html).includes("voice-one"));
    if (["external_outcome_unconfirmed", "dispatch_reserved"].includes(status))
      assert.ok(html.includes("No repitas la acción"));
    assert.match(
      html,
      /<details class="voice-technical"><summary>Detalles técnicos/,
    );
  }
});
test("friendly ready result keeps explicit voice controls without starting audio", () => {
  const html = render(ActionResultDetails, {
    ...shared,
    presentation: "friendly",
    result: {
      provider: "retell",
      status: "ready",
      session_id: "00000000-0000-4000-8000-000000000001",
    },
  });
  assert.ok(html.includes("Iniciar sesión de voz"));
  assert.ok(html.includes("Requiere micrófono"));
  assert.doesNotMatch(html, /<audio|autoplay/);
});
test("ActionOutput passes friendly presentation while default callers keep original JSON", () => {
  const props = { ...shared, value: { proposals: [proposal] } };
  assert.doesNotMatch(
    visible(render(ActionOutput, { ...props, presentation: "friendly" })),
    /<pre/,
  );
  const old = render(ActionOutput, props);
  assert.match(old, /<pre aria-label="Argumentos exactos de retell.execute">/);
  assert.doesNotMatch(old, /voice-technical/);
  assert.match(
    render(ActionResultDetails, {
      result: { provider: "other", status: "ok" },
    }),
    /<details open="">/,
  );
});
test("friendly values retain every array entry, zero, empty values and unknown fields", () => {
  const result = {
    provider: "retell",
    status: "completed",
    data: {
      unknown_field: Array.from({ length: 65 }, (_, i) => ({
        position: i,
        value: `item-${i}-exact`,
      })),
      numeric_zero: 0,
      empty_text: "",
      flag: false,
    },
  };
  const html = visible(
    render(ActionResultDetails, { result, presentation: "friendly" }),
  );
  for (let i = 0; i < 65; i++) assert.ok(html.includes(`item-${i}-exact`));
  assert.ok(html.includes('title="numeric_zero"'));
  assert.match(html, /voice-summary-value">0<\/span>/);
  assert.ok(html.includes("Texto vacío"));
  assert.ok(html.includes("Operación completada"));
  assert.doesNotMatch(html, />completed</);
});
test("friendly reviewed proposals do not claim confirmed success or remain labelled as unapplied", () => {
  const html = visible(
    render(ActionProposals, {
      ...shared,
      proposals: [{ ...proposal, status: "approved" }],
      presentation: "friendly",
    }),
  );
  assert.ok(html.includes("La aprobación ya fue procesada"));
  assert.doesNotMatch(html, /todavía no se ha aplicado|Operación completada/);
});
