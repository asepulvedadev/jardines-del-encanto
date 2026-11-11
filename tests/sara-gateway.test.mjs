import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { GET, POST, PATCH } from "../apps/web/app/api/crm/[...path]/route.ts";
const oldFetch = globalThis.fetch,
  oldBase = process.env.API_BASE_URL,
  oldOrigin = process.env.CRM_ORIGIN;
let calls = [];
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
  ])
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
});
const id = "00000000-0000-4000-8000-000000000001";
function req(method, body = {}, query = "") {
  const request = new Request(
    "https://crm.example.invalid/api/crm/sara/conversations" + query,
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
  Object.defineProperty(request, "cookies", {
    value: { get: () => undefined },
  });
  return request;
}
const ctx = (p) => ({ params: Promise.resolve({ path: p.split("/") }) });
test("Sara admits only the typed conversation and attachment routes", async () => {
  for (const [method, path] of [
    ["GET", "sara/status"],
    ["GET", "sara/skills"],
    ["GET", "sara/conversations"],
    ["POST", "sara/conversations"],
    ["PATCH", `sara/conversations/${id}`],
    ["GET", `sara/conversations/${id}/messages`],
    ["POST", `sara/conversations/${id}/messages`],
    ["POST", "sara/attachments"],
  ])
    assert.equal(
      (await { GET, POST, PATCH }[method](req(method), ctx(path))).status,
      200,
      path,
    );
  const n = calls.length;
  for (const path of [
    "sara/proxy",
    "sara/transcribe/arbitrary",
    "sara/conversations/../secret",
    "sara/attachments/../../secrets",
  ])
    assert.equal((await POST(req("POST"), ctx(path))).status, 404);
  assert.equal(calls.length, n);
});
test("Sara accepts larger uploads only on attachments and preserves JSON/Origin guards", async () => {
  const body = { data_base64: "x".repeat(20000) };
  assert.equal(
    (await POST(req("POST", body), ctx("sara/attachments"))).status,
    200,
  );
  assert.equal(
    (await POST(req("POST", body), ctx("sara/conversations"))).status,
    413,
  );
  const huge = { data_base64: "x".repeat(768 * 1024) };
  assert.equal(
    (await POST(req("POST", huge), ctx("sara/attachments"))).status,
    413,
  );
  const bad = req("POST");
  bad.headers.set("origin", "https://untrusted.invalid");
  assert.equal((await POST(bad, ctx("sara/attachments"))).status, 403);
  const form = req("POST");
  form.headers.set("content-type", "multipart/form-data");
  assert.equal((await POST(form, ctx("sara/attachments"))).status, 415);
});
test("Sara pagination forwards only one validated before cursor", async () => {
  assert.equal(
    (await GET(req("GET", {}, `?before=${id}`), ctx("sara/conversations")))
      .status,
    200,
  );
  assert.equal(
    calls[0].url,
    `http://private-api:8000/crm/sara/conversations?before=${id}`,
  );
  for (const query of [
    "?before=bad",
    `?before=${id}&before=${id}`,
    "?url=http://private.invalid",
  ])
    assert.equal(
      (await GET(req("GET", {}, query), ctx("sara/conversations"))).status,
      422,
    );
  assert.equal(calls.length, 1);
});
test("Private file downloads are bounded, typed and never inline HTML", async () => {
  globalThis.fetch = async () =>
    new Response("fixture", {
      headers: {
        "content-type": "text/plain",
        "content-disposition": 'attachment; filename="note.txt"',
      },
    });
  const good = await GET(req("GET"), ctx(`sara/attachments/${id}/content`));
  assert.equal(good.status, 200);
  assert.equal(good.headers.get("content-type"), "text/plain");
  assert.equal(
    good.headers.get("content-disposition"),
    'attachment; filename="note.txt"',
  );
  assert.equal(good.headers.get("x-content-type-options"), "nosniff");
  assert.match(good.headers.get("cache-control"), /private/);
  assert.equal(await good.text(), "fixture");
  globalThis.fetch = async () =>
    new Response("<script>bad</script>", {
      headers: { "content-type": "text/html" },
    });
  assert.equal(
    (await GET(req("GET"), ctx(`sara/attachments/${id}/content`))).status,
    502,
  );
  globalThis.fetch = async () =>
    new Response(new Uint8Array(512 * 1024 + 1), {
      headers: { "content-type": "audio/webm" },
    });
  assert.equal(
    (await GET(req("GET"), ctx(`sara/attachments/${id}/content`))).status,
    502,
  );
});
test("Sara JSON responses have an explicit byte budget", async () => {
  globalThis.fetch = async () =>
    new Response("x".repeat(2 * 1024 * 1024 + 1), {
      headers: { "content-type": "application/json" },
    });
  assert.equal((await GET(req("GET"), ctx("sara/conversations"))).status, 502);
});
