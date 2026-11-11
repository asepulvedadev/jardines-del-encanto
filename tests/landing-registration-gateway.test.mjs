import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { POST } from "../apps/web/app/api/landing/registrations/route.ts";
const originalFetch = globalThis.fetch,
  oldOrigin = process.env.CRM_ORIGIN,
  oldBase = process.env.API_BASE_URL;
let calls;
beforeEach(() => {
  calls = [];
  process.env.CRM_ORIGIN = "https://example.invalid";
  process.env.API_BASE_URL = "http://private-api:8000";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json(
      { code: "JDE-123456789ABC", name: "never expose", phone: "never expose" },
      { status: 201, headers: { "Set-Cookie": "bad=1" } },
    );
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  for (const [key, value] of [
    ["CRM_ORIGIN", oldOrigin],
    ["API_BASE_URL", oldBase],
  ]) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});
function request(headers = {}, body = "{}") {
  return new Request("https://example.invalid/api/landing/registrations", {
    method: "POST",
    headers: {
      origin: "https://example.invalid",
      "content-type": "application/json",
      cookie: "admin=private",
      "x-csrf-token": "private",
      ...headers,
    },
    body,
  });
}
test("public gateway checks origin, JSON and streamed size before forwarding", async () => {
  assert.equal(
    (await POST(request({ origin: "https://evil.invalid" }))).status,
    403,
  );
  assert.equal(
    (await POST(request({ "content-type": "text/plain" }))).status,
    415,
  );
  assert.equal((await POST(request({}, "x".repeat(2049)))).status, 413);
  assert.equal(calls.length, 0);
});
test("public gateway returns only a code and never forwards private session headers", async () => {
  const response = await POST(request());
  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), { code: "JDE-123456789ABC" });
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("cache-control"), "no-store, private");
  assert.equal(calls[0].url, "http://private-api:8000/public/registrations");
  assert.deepEqual(calls[0].options.headers, {
    "Content-Type": "application/json",
    Origin: "https://example.invalid",
  });
  assert.equal(calls[0].options.redirect, "error");
});
test("public gateway fails closed for upstream failure and malformed success", async () => {
  globalThis.fetch = async () => {
    throw Error("private");
  };
  assert.equal((await POST(request())).status, 503);
  globalThis.fetch = async () =>
    Response.json({ code: "not-a-code", name: "secret" }, { status: 201 });
  assert.equal((await POST(request())).status, 502);
  globalThis.fetch = async () =>
    Response.json({ detail: "secret" }, { status: 429 });
  const r = await POST(request());
  assert.equal(r.status, 429);
  assert.equal(r.headers.get("retry-after"), "600");
  assert.deepEqual(await r.json(), { detail: "capture_throttled" });
});
