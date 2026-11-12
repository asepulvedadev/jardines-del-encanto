import test, { beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  GET,
  POST,
  PATCH,
} from "../../apps/web/app/api/crm/[...path]/route.ts";
const old = globalThis.fetch,
  base = process.env.API_BASE_URL,
  origin = process.env.CRM_ORIGIN;
const id = "00000000-0000-4000-8000-000000000001";
let calls = [];
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.invalid";
  globalThis.fetch = async (u, o) => {
    calls.push([u, o]);
    return Response.json({ ok: true });
  };
});
afterEach(() => {
  globalThis.fetch = old;
  for (const [k, v] of [
    ["API_BASE_URL", base],
    ["CRM_ORIGIN", origin],
  ])
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
});
const ctx = (p) => ({ params: Promise.resolve({ path: p.split("/") }) });
function req(method, body = {}, query = "") {
  const r = new Request("https://crm.invalid/api/crm/voice/settings" + query, {
    method,
    headers: {
      origin: "https://crm.invalid",
      "content-type": "application/json",
      "x-csrf-token": "fixture",
    },
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
  Object.defineProperty(r, "cookies", { value: { get: () => undefined } });
  return r;
}
test("voice gateway admits exact methods and rejects arbitrary paths and queries", async () => {
  for (const [m, p] of [
    ["GET", "voice/settings"],
    ["POST", "voice/settings"],
    ["POST", "voice/catalog"],
    ["POST", "voice/disconnect"],
    ["POST", "voice/attachments"],
    ["POST", `voice/sessions/${id}/claim`],
    ["PATCH", "control/connections/elevenlabs"],
  ])
    assert.equal(
      (await { GET, POST, PATCH }[m](req(m), ctx(p))).status,
      200,
      p,
    );
  const n = calls.length;
  for (const p of [
    "voice/proxy",
    "voice/sessions/garbage/claim",
    `voice/artifacts/${id}/other`,
  ])
    assert.equal((await POST(req("POST"), ctx(p))).status, 404);
  assert.equal(
    (await GET(req("GET", {}, "?url=bad"), ctx("voice/settings"))).status,
    422,
  );
  assert.equal(calls.length, n);
});
test("voice upload body and private binary are independently bounded", async () => {
  assert.equal(
    (
      await POST(
        req("POST", { data_base64: "x".repeat(30000) }),
        ctx("voice/attachments"),
      )
    ).status,
    200,
  );
  assert.equal(
    (
      await POST(
        req("POST", { data_base64: "x".repeat(768 * 1024) }),
        ctx("voice/attachments"),
      )
    ).status,
    413,
  );
  globalThis.fetch = async () =>
    new Response(new Uint8Array(600000), {
      headers: {
        "content-type": "audio/mpeg",
        "content-disposition": "attachment",
      },
    });
  const r = await GET(req("GET"), ctx(`voice/artifacts/${id}/content`));
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("content-type"), "audio/mpeg");
  assert.match(r.headers.get("cache-control"), /private/);
  assert.equal(r.headers.get("content-security-policy"), "sandbox");
  globalThis.fetch = async () =>
    new Response(new Uint8Array(2 * 1024 * 1024 + 1), {
      headers: { "content-type": "audio/mpeg" },
    });
  assert.equal(
    (await GET(req("GET"), ctx(`voice/artifacts/${id}/content`))).status,
    502,
  );
});
test("voice claims retain origin and session protections", async () => {
  const r = req("POST");
  r.headers.set("origin", "https://other.invalid");
  assert.equal((await POST(r, ctx(`voice/sessions/${id}/claim`))).status, 403);
  assert.equal(calls.length, 0);
});
