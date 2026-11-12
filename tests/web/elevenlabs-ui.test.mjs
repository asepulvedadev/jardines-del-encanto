import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
const root = fileURLToPath(
    new URL("../../apps/web/components/crm/", import.meta.url),
  ),
  require = createRequire(import.meta.url),
  cache = new Map();
function load(name) {
  const path = resolve(root, name);
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const req = (s) => {
    if (s === "next/navigation") return { useRouter: () => ({ replace() {} }) };
    if (s.startsWith(".")) {
      for (const e of [".tsx", ".ts"]) {
        try {
          readFileSync(resolve(dirname(path), s) + e);
        } catch {
          continue;
        }
        return load(resolve(dirname(path), s) + e);
      }
    }
    return require(s);
  };
  new Function("require", "module", "exports", code)(
    req,
    module,
    module.exports,
  );
  return module.exports;
}
const { voiceArtifactPath, ElevenLabsVoiceResult } = load(
    "elevenlabs-result.tsx",
  ),
  { ActionProposals } = load("hermes-panel.tsx");
const id = "00000000-0000-4000-8000-000000000001";
test("only exact owned artifact routes become audio sources with no autoplay", () => {
  const path = `/api/crm/voice/artifacts/${id}/content`;
  assert.equal(
    voiceArtifactPath({ artifact_id: id, content_path: path }),
    path,
  );
  for (const content_path of [
    "https://vendor.invalid/audio",
    path + "?key=secret",
    "/api/crm/voice/artifacts/other/content",
  ])
    assert.equal(voiceArtifactPath({ artifact_id: id, content_path }), null);
  const html = renderToStaticMarkup(
    React.createElement(ElevenLabsVoiceResult, {
      result: { artifact_id: id, content_path: path },
    }),
  );
  assert.match(html, /<audio controls="" preload="none"/);
  assert.doesNotMatch(html, /autoPlay|autoplay/);
});
test("outbound proposal approval starts disabled until separate human consent", () => {
  const proposal = {
    id,
    action: "voice.execute",
    arguments: {
      operation: "outbound_call",
      arguments: { contact_id: id, expected_phone: "+573001234567" },
    },
    status: "pending",
    version: 1,
  };
  const html = renderToStaticMarkup(
    React.createElement(ActionProposals, {
      proposals: [proposal],
      request: async () => {},
      onChanged: async () => {},
    }),
  );
  assert.match(html, /type="checkbox"/);
  assert.doesNotMatch(html, /checked=""/);
  assert.match(html, /disabled="">Aprobar acción exacta/);
  assert.match(html, /destinatario indicado autorizó/);
  assert.match(html, /573001234567/);
});
test("agent sessions require a separate explicit click and expose no credentials", () => {
  const html = renderToStaticMarkup(
    React.createElement(ElevenLabsVoiceResult, {
      result: { status: "ready", session_id: id },
      request: async () => {},
    }),
  );
  assert.match(html, /Iniciar sesión de voz/);
  assert.match(html, /5 minutos/);
  assert.match(html, /Agente de ElevenLabs/);
  assert.doesNotMatch(html, /Hermes|token/);
});
test("browser sessions have stale-start cleanup and no persisted tokens", () => {
  const s = readFileSync(resolve(root, "elevenlabs-result.tsx"), "utf8");
  assert.match(s, /import\("@elevenlabs\/client"\)/);
  assert.match(s, /connectionType: "webrtc"/);
  assert.match(s, /run !== generation.current/);
  assert.match(s, /endSession\(\)/);
  assert.match(s, /5 \* 60 \* 1000/);
  assert.doesNotMatch(s, /localStorage|sessionStorage|console\./);
});
