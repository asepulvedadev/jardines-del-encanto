import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { GET, POST, PATCH } from "../apps/web/app/api/crm/[...path]/route.ts";

const realFetch = globalThis.fetch;
const oldBase = process.env.API_BASE_URL;
const oldOrigin = process.env.CRM_ORIGIN;
let calls;
beforeEach(() => {
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.example.invalid";
  calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json(
      { status: "ok" },
      {
        headers: {
          "Set-Cookie":
            "__Host-jardines_session=opaque; Secure; HttpOnly; SameSite=Lax; Path=/",
        },
      },
    );
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
  if (oldBase === undefined) delete process.env.API_BASE_URL;
  else process.env.API_BASE_URL = oldBase;
  if (oldOrigin === undefined) delete process.env.CRM_ORIGIN;
  else process.env.CRM_ORIGIN = oldOrigin;
});
function request(method, body = {}, headers = {}, cookies = {}) {
  const req = new Request("https://crm.example.invalid/api/crm/contacts", {
    method,
    headers: {
      "Content-Type": "application/json",
      Origin: "https://crm.example.invalid",
      ...headers,
    },
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
  Object.defineProperty(req, "cookies", {
    value: {
      get: (name) =>
        cookies[name] ? { name, value: cookies[name] } : undefined,
    },
  });
  return req;
}
const context = (path) => ({
  params: Promise.resolve({ path: path.split("/") }),
});

test("gateway rejects arbitrary paths, traversal, unsupported methods and missing origin", async () => {
  for (const path of [
    "../health",
    "auth/register",
    "http://attacker.invalid",
    "users",
  ])
    assert.equal((await GET(request("GET"), context(path))).status, 404);
  assert.equal(
    (await PATCH(request("PATCH"), context("auth/login"))).status,
    404,
  );
  assert.equal(
    (
      await POST(
        request("POST", {}, { Origin: "https://attacker.invalid" }),
        context("auth/login"),
      )
    ).status,
    403,
  );
  const missing = request("POST");
  missing.headers.delete("Origin");
  assert.equal((await POST(missing, context("contacts"))).status, 403);
  assert.equal(calls.length, 0);
});

test("gateway enforces JSON and bounded request bodies without reaching API", async () => {
  assert.equal(
    (
      await POST(
        request("POST", {}, { "Content-Type": "text/plain" }),
        context("contacts"),
      )
    ).status,
    415,
  );
  assert.equal(
    (
      await POST(
        request("POST", { name: "x".repeat(20000) }),
        context("contacts"),
      )
    ).status,
    413,
  );
  assert.equal(calls.length, 0);
});

test("gateway forwards only the host session, CSRF and origin to its fixed API", async () => {
  const response = await POST(
    request(
      "POST",
      { name: "Test" },
      { "X-CSRF-Token": "csrf", Authorization: "injected" },
      { "__Host-jardines_session": "opaque", unrelated: "private" },
    ),
    context("contacts"),
  );
  assert.equal(response.status, 200);
  assert.equal(calls[0].url, "http://private-api:8000/crm/contacts");
  const headers = calls[0].options.headers;
  assert.equal(headers.get("cookie"), "__Host-jardines_session=opaque");
  assert.equal(headers.get("x-csrf-token"), "csrf");
  assert.equal(headers.get("authorization"), null);
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[0].options.redirect, "error");
  assert.match(response.headers.get("set-cookie"), /Secure; HttpOnly/);
  assert.equal(response.headers.get("cache-control"), "no-store, private");
});

test("gateway preserves backend rejection and sanitizes transport failures", async () => {
  globalThis.fetch = async () =>
    Response.json({ detail: "record_changed" }, { status: 409 });
  assert.equal(
    (
      await PATCH(
        request("PATCH"),
        context("contacts/00000000-0000-0000-0000-000000000001"),
      )
    ).status,
    409,
  );
  globalThis.fetch = async () => {
    throw new Error("private connection credentials");
  };
  const result = await GET(request("GET"), context("workspace"));
  assert.equal(result.status, 503);
  assert.deepEqual(await result.json(), { detail: "service_unavailable" });
});

test("gateway permits only the implemented social connection endpoints", async () => {
  assert.equal((await GET(request("GET"), context("social/settings"))).status, 200);
  for (const endpoint of ["settings", "sync", "complete", ...["facebook", "instagram", "tiktok", "whatsapp", "telegram"].map(p => `connect/${p}`)]) {
    assert.equal((await POST(request("POST"), context(`social/${endpoint}`))).status, 200);
    assert.equal(calls.at(-1).url, `http://private-api:8000/crm/social/${endpoint}`);
  }
  const count = calls.length;
  for (const endpoint of ["connect/twitter", "connect/../facebook", "posts", "send", "api-keys", "webhooks/settings"]) {
    assert.equal((await POST(request("POST"), context(`social/${endpoint}`))).status, 404);
  }
  assert.equal((await PATCH(request("PATCH"), context("social/settings"))).status, 404);
  assert.equal(calls.length, count);
});
