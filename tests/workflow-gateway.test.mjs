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
  for (const [key, value] of [
    ["API_BASE_URL", oldBase],
    ["CRM_ORIGIN", oldOrigin],
  ])
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
});
const id = "00000000-0000-4000-8000-000000000001";
const ctx = (path) => ({ params: Promise.resolve({ path: path.split("/") }) });
function req(method, body = {}, query = "") {
  const r = new Request(
    `https://crm.example.invalid/api/crm/workflows/catalog${query}`,
    {
      method,
      headers: {
        origin: "https://crm.example.invalid",
        "content-type": "application/json",
        "x-csrf-token": "fixture",
      },
      body: method === "GET" ? undefined : JSON.stringify(body),
    },
  );
  Object.defineProperty(r, "cookies", { value: { get: () => undefined } });
  return r;
}
test("workflows gateway is an exact allowlist and rejects query injection", async () => {
  for (const [method, path] of [
    ["GET", "catalog"],
    ["GET", "definitions"],
    ["POST", "definitions"],
    ["PATCH", `definitions/${id}`],
    ["POST", `definitions/${id}/prepare`],
    ["POST", "options"],
    ["GET", "runs"],
    ["GET", `runs/${id}`],
    ["POST", `runs/${id}/activate`],
    ["POST", `runs/${id}/pause`],
    ["POST", `runs/${id}/resume`],
    ["POST", `runs/${id}/stop`],
  ])
    assert.equal(
      (
        await { GET, POST, PATCH }[method](
          req(method),
          ctx(`workflows/${path}`),
        )
      ).status,
      200,
      path,
    );
  const before = calls.length;
  for (const path of [
    `runs/${id}/execute`,
    `runs/${id}/retry`,
    "definitions/../secrets",
    "proxy",
    "runs/not-a-uuid",
  ])
    assert.equal(
      (await POST(req("POST"), ctx(`workflows/${path}`))).status,
      404,
    );
  assert.equal(
    (
      await GET(
        req("GET", {}, "?url=https://evil.test"),
        ctx("workflows/catalog"),
      )
    ).status,
    422,
  );
  assert.equal(calls.length, before);
});
test("64KiB only for workflow definitions/preparation; activation stays16KiB", async () => {
  const body = { text: "x".repeat(20000) };
  for (const [method, path] of [
    ["POST", "definitions"],
    ["PATCH", `definitions/${id}`],
    ["POST", `definitions/${id}/prepare`],
  ])
    assert.equal(
      (
        await { POST, PATCH }[method](
          req(method, body),
          ctx(`workflows/${path}`),
        )
      ).status,
      200,
    );
  for (const path of ["options", `runs/${id}/activate`, `runs/${id}/pause`])
    assert.equal(
      (await POST(req("POST", body), ctx(`workflows/${path}`))).status,
      413,
    );
  assert.equal(
    (
      await POST(
        req("POST", { text: "x".repeat(65536) }),
        ctx("workflows/definitions"),
      )
    ).status,
    413,
  );
});
