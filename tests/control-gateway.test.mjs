import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { GET, POST, PATCH } from "../apps/web/app/api/crm/[...path]/route.ts";
const oldFetch = globalThis.fetch,
  oldBase = process.env.API_BASE_URL,
  oldOrigin = process.env.CRM_ORIGIN;
let calls;
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.example.invalid";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({ ok: true });
  };
});
afterEach(() => {
  globalThis.fetch = oldFetch;
  for (const [k, v] of [
    ["API_BASE_URL", oldBase],
    ["CRM_ORIGIN", oldOrigin],
  ]) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
});
function req(method, body = {}) {
  const r = new Request("https://crm.example.invalid/api/crm/control/catalog", {
    method,
    headers: {
      origin: "https://crm.example.invalid",
      "content-type": "application/json",
      "x-csrf-token": "fixture-csrf",
    },
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
  Object.defineProperty(r, "cookies", { value: { get: () => undefined } });
  return r;
}
const ctx = (path) => ({ params: Promise.resolve({ path: path.split("/") }) });
const id = "00000000-0000-4000-8000-000000000001";
test("shared control gateway admits only exact app-control and Hermes routes", async () => {
  for (const [method, path] of [
    ["GET", "control/catalog"],
    ["POST", "control/items"],
    ["PATCH", `control/items/${id}`],
    ["POST", `control/items/${id}/run`],
    ["PATCH", "control/connections/hermes"],
    ["GET", "hermes/status"],
    ["POST", "hermes/chat"],
    ["POST", "hermes/actions"],
    ["POST", `hermes/proposals/${id}/approve`],
    ["POST", `hermes/proposals/${id}/reject`],
  ])
    assert.equal(
      (await { GET, POST, PATCH }[method](req(method), ctx(path))).status,
      200,
      path,
    );
  const before = calls.length;
  for (const path of [
    "internal/hermes/call",
    "hermes/tools/execute",
    "control/proxy",
    "control/connections/arbitrary",
    "control/items/../secrets",
  ])
    assert.equal((await POST(req("POST"), ctx(path))).status, 404, path);
  assert.equal(calls.length, before);
});
test("only definition creation/edit accepts bounded Unicode skill content beyond16KiB", async () => {
  const body = {
    kind: "skill",
    name: "Prueba",
    definition: { content: "árbol".repeat(5000) },
  };
  assert.equal(
    (await POST(req("POST", body), ctx("control/items"))).status,
    200,
  );
  assert.equal(
    (await PATCH(req("PATCH", body), ctx(`control/items/${id}`))).status,
    200,
  );
  assert.equal((await POST(req("POST", body), ctx("hermes/chat"))).status, 413);
  assert.equal(
    (
      await POST(
        req("POST", { content: "x".repeat(65537) }),
        ctx("control/items"),
      )
    ).status,
    413,
  );
});
