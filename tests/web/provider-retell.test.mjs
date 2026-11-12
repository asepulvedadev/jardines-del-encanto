import test, { beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  GET,
  POST,
  PATCH,
} from "../../apps/web/app/api/crm/[...path]/route.ts";
const originalFetch = globalThis.fetch;
const oldBase = process.env.API_BASE_URL,
  oldOrigin = process.env.CRM_ORIGIN;
let calls;
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.invalid";
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    return Response.json({ ok: true });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  for (const [key, value] of [
    ["API_BASE_URL", oldBase],
    ["CRM_ORIGIN", oldOrigin],
  ])
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
});
const id = "00000000-0000-4000-8000-000000000001";
const context = (path) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
function request(method, query = "", body = {}) {
  const req = new Request(
    "https://crm.invalid/api/crm/retell/settings" + query,
    {
      method,
      headers: {
        origin: "https://crm.invalid",
        "content-type": "application/json",
        "x-csrf-token": "fixture",
      },
      body: method === "GET" ? undefined : JSON.stringify(body),
    },
  );
  Object.defineProperty(req, "cookies", { value: { get: () => undefined } });
  return req;
}
test("Retell admits only explicit private routes and preserves other providers", async () => {
  for (const [method, path] of [
    ["GET", "retell/settings"],
    ["POST", "retell/settings"],
    ["POST", "retell/catalog"],
    ["POST", "retell/schema"],
    ["POST", "retell/disconnect"],
    ["POST", `retell/sessions/${id}/claim`],
    ["PATCH", "control/connections/retell"],
    ["GET", "voice/settings"],
    ["GET", "social/settings"],
    ["GET", "sara/status"],
  ])
    assert.equal(
      (await { GET, POST, PATCH }[method](request(method), context(path)))
        .status,
      200,
      path,
    );
  const before = calls.length;
  for (const path of [
    "retell/proxy",
    "retell/invoke",
    "retell/sessions/arbitrary/claim",
    `retell/sessions/${id}/other`,
  ])
    assert.equal(
      (await POST(request("POST"), context(path))).status,
      404,
      path,
    );
  assert.equal(
    (
      await GET(
        request("GET", "?url=https://example.invalid"),
        context("retell/settings"),
      )
    ).status,
    422,
  );
  assert.equal(calls.length, before);
});
test("Retell preserves origin guards and bounds schema/token responses", async () => {
  const req = request("POST");
  req.headers.set("origin", "https://other.invalid");
  assert.equal((await POST(req, context("retell/settings"))).status, 403);
  assert.equal(calls.length, 0);
  globalThis.fetch = async () =>
    new Response("unsafe markup", { headers: { "content-type": "text/html" } });
  assert.equal(
    (await GET(request("GET"), context("retell/settings"))).status,
    502,
  );
  globalThis.fetch = async () =>
    new Response("x".repeat(2 * 1024 * 1024 + 1), {
      headers: { "content-type": "application/json" },
    });
  assert.equal(
    (await POST(request("POST"), context("retell/schema"))).status,
    502,
  );
});
test("Retell replies remain private and bounded payloads do not reach upstream", async () => {
  assert.equal(
    (
      await POST(
        request("POST", "", { arguments: "x".repeat(17000) }),
        context("retell/schema"),
      )
    ).status,
    413,
  );
  assert.equal(calls.length, 0);
  const reply = await GET(request("GET"), context("retell/settings"));
  assert.equal(reply.status, 200);
  assert.match(reply.headers.get("cache-control"), /no-store/);
  assert.match(reply.headers.get("cache-control"), /private/);
  assert.equal(calls[0][1].redirect, "error");
});
