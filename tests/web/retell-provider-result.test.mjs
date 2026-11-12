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
  ActionResultDetails,
} = require("../../apps/web/components/crm/hermes-panel.tsx");
for (const provider of [undefined, "elevenlabs", "retell", "unknown"])
  test(`voice controls select only provider ${provider ?? "legacy"}`, () => {
    const result = {
      status: "ready",
      session_id: "00000000-0000-4000-8000-000000000001",
      ...(provider ? { provider } : {}),
    };
    const html = renderToStaticMarkup(
      React.createElement(ActionResultDetails, {
        result,
        request: async () => ({}),
      }),
    );
    assert.equal(html.includes("Agente de Retell"), provider === "retell");
    assert.equal(
      html.includes("Agente de ElevenLabs"),
      provider === undefined || provider === "elevenlabs",
    );
    assert.equal(
      (html.match(/Iniciar sesión de voz/g) ?? []).length,
      provider === "unknown" ? 0 : 1,
    );
  });
