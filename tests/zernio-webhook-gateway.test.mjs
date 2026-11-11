import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { POST } from "../apps/web/app/api/integrations/zernio/webhook/route.ts";
const originalFetch = globalThis.fetch;
const originalBase = process.env.API_BASE_URL;
let calls;
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({ received: true });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalBase === undefined) delete process.env.API_BASE_URL;
  else process.env.API_BASE_URL = originalBase;
});
function request(body = '{"id":"event-1"}', headers = {}) {
  return new Request("https://crm.example.invalid/api/integrations/zernio/webhook", {
    method: "POST", body,
    headers: {
      "Content-Type": "application/json", "X-Zernio-Signature": "a".repeat(64),
      "X-Zernio-Event-Id": "event-1", "X-Zernio-Event": "webhook.test", ...headers,
    },
  });
}
test("webhook bridge preserves raw signed bytes, never forwards cookies or authorization", async () => {
  const raw = '{ "id": "event-1", "value": "á" }\n';
  const result = await POST(request(raw, { Cookie: "private-session", Authorization: "private-token" }));
  assert.equal(result.status, 200);
  assert.equal(calls[0].url, "http://private-api:8000/integrations/zernio/webhook");
  assert.equal(new TextDecoder().decode(calls[0].options.body), raw);
  assert.equal(calls[0].options.headers.get("x-zernio-signature"), "a".repeat(64));
  assert.equal(calls[0].options.headers.get("cookie"), null);
  assert.equal(calls[0].options.headers.get("authorization"), null);
  assert.equal(calls[0].options.redirect, "error");
  assert.equal(result.headers.get("cache-control"), "no-store");
});
test("malformed or oversized deliveries never reach the backend", async () => {
  assert.equal((await POST(request("{}", { "X-Zernio-Signature": "invalid" }))).status, 400);
  assert.equal((await POST(request("{}", { "Content-Type": "text/plain" }))).status, 415);
  assert.equal((await POST(request("x".repeat(256 * 1024 + 1)))).status, 413);
  assert.equal(calls.length, 0);
});
test("backend verification failures are preserved and transport errors are sanitized", async () => {
  globalThis.fetch = async () => Response.json({ detail: "invalid_signature" }, { status: 401 });
  assert.equal((await POST(request())).status, 401);
  globalThis.fetch = async () => { throw new Error("sensitive transport detail"); };
  const result = await POST(request());
  assert.equal(result.status, 503);
  assert.deepEqual(await result.json(), { detail: "service_unavailable" });
});
