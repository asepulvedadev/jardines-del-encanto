import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const m = { exports: {} };
new Function(
  "module",
  "exports",
  ts.transpileModule(
    readFileSync(
      new URL(
        "../../apps/web/components/crm/voice-request.ts",
        import.meta.url,
      ),
      "utf8",
    ),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    },
  ).outputText,
)(m, m.exports);
test("workspace request sends same-origin CSRF and never sends GET body", async () => {
  let call;
  const request = m.exports.voiceRequest(
    "csrf",
    () => {},
    async (url, options) => {
      call = { url, options };
      return {
        ok: true,
        status: 200,
        json: async () => ({ snapshots: [], partial: true }),
      };
    },
  );
  await request("retell/results");
  assert.equal(call.options.body, undefined);
  assert.equal(call.options.cache, "no-store");
  assert.equal(call.options.credentials, "same-origin");
  assert.equal(call.options.headers["X-CSRF-Token"], "csrf");
  await request("hermes/actions", "POST", { action: "retell.execute" });
  assert.equal(JSON.parse(call.options.body).action, "retell.execute");
});
test("oversized payloads fail locally and expired sessions redirect", async () => {
  let count = 0,
    expired = 0;
  const request = m.exports.voiceRequest(
    "csrf",
    () => expired++,
    async () => {
      count++;
      return { status: 401, ok: false, json: async () => ({}) };
    },
  );
  await assert.rejects(
    request("hermes/actions", "POST", { value: "x".repeat(17000) }),
  );
  assert.equal(count, 0);
  await assert.rejects(request("retell/settings"), /sesión/);
  assert.equal(expired, 1);
});
test("complete editor failures explain that editing is unavailable without exposing codes", async () => {
  for (const [detail, expected] of [
    ["retell_editor_unavailable", /editor completo no está disponible/],
    ["retell_editor_timeout", /No se pudo cargar el editor a tiempo/],
  ]) {
    const request = m.exports.voiceRequest(
      "csrf",
      () => {},
      async () => ({
        status: 503,
        ok: false,
        json: async () => ({ detail }),
      }),
    );
    await assert.rejects(
      request("retell/editor", "POST", {
        kind: "agent",
        id: "agent_test",
        revision: 1,
      }),
      expected,
    );
  }
});
