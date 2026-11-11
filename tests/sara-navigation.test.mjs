import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (p) => readFileSync(new URL("../" + p, import.meta.url), "utf8");
test("Dashboard is first and Sara IA is immediately below it in CRM navigation", () => {
  const types = read("apps/web/components/crm/types.ts"),
    workspace = read("apps/web/components/crm/workspace.tsx");
  assert.match(types, /overview: "Dashboard"/);
  assert.match(types, /sara: "Sara IA"/);
  assert.match(workspace, /\["overview", "home"\],\s*\["sara", "message"\]/);
  assert.match(workspace, /<SaraPanel/);
});
test("Skills management stays in customization settings without duplicating OAuth consumers", () => {
  const workspace = read("apps/web/components/crm/workspace.tsx"),
    settings = read("apps/web/components/crm/settings-modal.tsx");
  assert.doesNotMatch(workspace, /onManageSkills/);
  assert.match(settings, /customizations/);
  assert.match(workspace, /initialTab=\{settingsTab\}/);
  assert.match(settings, /initialTab/);
  assert.equal((settings.match(/<SocialPanel/g) || []).length, 1);
});

import ts from "typescript";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
function nextHeaders() {
  const module = { exports: {} };
  const code = ts.transpileModule(read("apps/web/next.config.ts"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText;
  new Function("require", "module", "exports", code)(
    require,
    module,
    module.exports,
  );
  return module.exports.default.headers();
}

test("voice notes allow only same-origin CRM microphone after the deny-by-default policy", async () => {
  const rules = await nextHeaders();
  const microphone = rules.flatMap((rule, index) =>
    rule.headers
      .filter((header) => header.key.toLowerCase() === "permissions-policy")
      .map((header) => ({ source: rule.source, value: header.value, index })),
  );
  const global = microphone.find((rule) => rule.source === "/(.*)");
  assert.equal(global?.value, "camera=(), microphone=(), geolocation=()");
  const allowed = microphone.filter(
    (rule) => !rule.value.includes("microphone=()"),
  );
  assert.equal(allowed.length, 1);
  assert.equal(allowed[0].source, "/crm/:path*");
  assert.equal(
    allowed[0].value,
    "camera=(), microphone=(self), geolocation=()",
  );
  assert.ok(allowed[0].index > global.index);
  assert.doesNotMatch(allowed[0].value, /\*|https?:/);
});
