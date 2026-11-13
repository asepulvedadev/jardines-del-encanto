import test, { afterEach, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  GET,
  POST,
  PATCH,
  DELETE,
} from "../../apps/web/app/api/crm/[...path]/route.ts";

const previous = {
  fetch: globalThis.fetch,
  base: process.env.API_BASE_URL,
  origin: process.env.CRM_ORIGIN,
};
let calls;
const context = (path) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
function request(
  method,
  path,
  body = { revision: 7 },
  origin = "https://crm.invalid",
) {
  const result = new Request(`https://crm.invalid/api/crm/${path}`, {
    method,
    headers: {
      origin,
      "content-type": "application/json",
      "x-csrf-token": "fixture-csrf",
    },
    body: method === "GET" ? undefined : JSON.stringify(body),
  });
  Object.defineProperty(result, "cookies", {
    value: {
      get: (name) =>
        name === "__Host-jardines_session"
          ? { name, value: "fixture-session" }
          : undefined,
    },
  });
  return result;
}
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.invalid";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({
      snapshots: [],
      partial: true,
      errors: [],
      cached: false,
    });
  };
});
afterEach(() => {
  globalThis.fetch = previous.fetch;
  for (const [key, value] of [
    ["API_BASE_URL", previous.base],
    ["CRM_ORIGIN", previous.origin],
  ]) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});
test("automatic inventory and exact reads admit only bounded POSTs with CSRF/session forwarding", async () => {
  for (const path of ["retell/inventory", "retell/read", "retell/editor"]) {
    const response = await POST(request("POST", path), context(path));
    assert.equal(response.status, 200);
    assert.match(response.headers.get("cache-control"), /no-store, private/);
    const call = calls.at(-1);
    assert.equal(call.url, `http://private-api:8000/crm/${path}`);
    assert.equal(
      call.options.headers.get("cookie"),
      "__Host-jardines_session=fixture-session",
    );
    assert.equal(call.options.headers.get("x-csrf-token"), "fixture-csrf");
    assert.equal(call.options.cache, "no-store");
    assert.equal(
      new TextDecoder().decode(call.options.body),
      JSON.stringify({ revision: 7 }),
    );
  }
});
test("automatic reads reject queries, other methods, origins and neighboring paths before fetching", async () => {
  for (const path of ["retell/inventory", "retell/read", "retell/editor"]) {
    for (const [method, handler] of [
      ["GET", GET],
      ["PATCH", PATCH],
      ["DELETE", DELETE],
    ])
      assert.equal(
        (await handler(request(method, path), context(path))).status,
        404,
      );
    assert.equal(
      (
        await POST(
          request("POST", `${path}?endpoint=deleteAgent`),
          context(path),
        )
      ).status,
      422,
    );
    assert.equal(
      (
        await POST(
          request("POST", path, {}, "https://other.invalid"),
          context(path),
        )
      ).status,
      403,
    );
    assert.equal(
      (
        await POST(
          request("POST", path, { data: "x".repeat(17000) }),
          context(path),
        )
      ).status,
      413,
    );
    assert.equal(
      (await POST(request("POST", `${path}/proxy`), context(`${path}/proxy`)))
        .status,
      404,
    );
  }
  assert.equal(calls.length, 0);
});
