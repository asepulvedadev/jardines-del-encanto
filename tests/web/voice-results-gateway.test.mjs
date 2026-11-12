import test, { afterEach, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  GET,
  POST,
  PATCH,
  DELETE,
} from "../../apps/web/app/api/crm/[...path]/route.ts";

const originalFetch = globalThis.fetch;
const originalBase = process.env.API_BASE_URL;
const originalOrigin = process.env.CRM_ORIGIN;
let calls;
const context = (path = "retell/results") => ({
  params: Promise.resolve({ path: path.split("/") }),
});
function request(method = "GET", query = "") {
  const value = new Request(
    `https://crm.invalid/api/crm/retell/results${query}`,
    {
      method,
      headers: {
        origin: "https://crm.invalid",
        "content-type": "application/json",
      },
      body: method === "GET" ? undefined : "{}",
    },
  );
  Object.defineProperty(value, "cookies", {
    value: {
      get: (name) =>
        name === "__Host-jardines_session"
          ? { name, value: "fixture-session" }
          : undefined,
    },
  });
  return value;
}
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.invalid";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({ snapshots: [], partial: true });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  for (const [key, value] of [
    ["API_BASE_URL", originalBase],
    ["CRM_ORIGIN", originalOrigin],
  ]) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

test("Retell results proxy is an exact, authenticated-cookie, no-store local GET", async () => {
  const response = await GET(request(), context());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { snapshots: [], partial: true });
  assert.match(response.headers.get("cache-control"), /no-store, private/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://private-api:8000/crm/retell/results");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(
    calls[0].options.headers.get("cookie"),
    "__Host-jardines_session=fixture-session",
  );
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[0].options.redirect, "error");
  assert.equal(calls[0].options.body, undefined);
});

test("Retell results deny other verbs, queries, bodies and neighboring paths before fetch", async () => {
  for (const [method, handler] of [
    ["POST", POST],
    ["PATCH", PATCH],
    ["DELETE", DELETE],
  ]) {
    assert.equal((await handler(request(method), context())).status, 404);
  }
  for (const path of [
    "retell/results/extra",
    "retell/result",
    "retell/results-proxy",
  ]) {
    assert.equal((await GET(request(), context(path))).status, 404);
  }
  assert.equal(
    (await GET(request("GET", "?endpoint=listAgents"), context())).status,
    422,
  );
  const withBody = request();
  Object.defineProperty(withBody, "body", { value: new ReadableStream() });
  assert.equal((await GET(withBody, context())).status, 422);
  assert.equal(calls.length, 0);
});

test("Retell result responses remain bounded JSON and preserve upstream auth denial", async () => {
  globalThis.fetch = async () =>
    Response.json({ detail: "authentication_required" }, { status: 401 });
  assert.equal((await GET(request(), context())).status, 401);
  globalThis.fetch = async () =>
    new Response("not-json", { headers: { "content-type": "text/plain" } });
  assert.equal((await GET(request(), context())).status, 502);
  globalThis.fetch = async () =>
    new Response("x".repeat(2 * 1024 * 1024 + 1), {
      headers: { "content-type": "application/json" },
    });
  assert.equal((await GET(request(), context())).status, 502);
});
