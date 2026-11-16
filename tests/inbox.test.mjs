import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { readFileSync } from "node:fs";
import { GET, POST, PATCH } from "../apps/web/app/api/crm/[...path]/route.ts";
import {
  inboxCursor,
  inboxPartial,
  inboxRows,
  inboxSafeLink,
  inboxTitle,
  inboxBody,
  inboxOperationLabels,
} from "../apps/web/components/crm/inbox-types.ts";
const realFetch = globalThis.fetch,
  oldBase = process.env.API_BASE_URL,
  oldOrigin = process.env.CRM_ORIGIN;
let calls = [];
beforeEach(() => {
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.example.invalid";
  calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({ data: [] });
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
  for (const [key, value] of [
    ["API_BASE_URL", oldBase],
    ["CRM_ORIGIN", oldOrigin],
  ])
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
});
function request(
  method = "GET",
  path = "inbox/catalog",
  query = "",
  body = {},
) {
  const req = new Request(
    `https://crm.example.invalid/api/crm/${path}${query}`,
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
  Object.defineProperty(req, "cookies", {
    value: {
      get: (name) =>
        name === "__Host-jardines_session"
          ? { name, value: "fixture-only" }
          : undefined,
    },
  });
  return req;
}
const context = (path) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
test("Inbox appears directly after Plantillas and preserves sales order", () => {
  const source = readFileSync(
    new URL("../apps/web/components/crm/workspace.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /\["campaigns", "list"\],\s*\["inbox", "message"\]/);
  assert.match(source, /<InboxPanel/);
});
test("every pinned vendor inbox function has a human-readable Spanish action", () => {
  const registry = JSON.parse(
    readFileSync(
      new URL("../apps/api/app/inbox/registry.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(Object.keys(registry.operations).length, 43);
  for (const key of Object.keys(registry.operations))
    assert.ok(inboxOperationLabels[key], key);
});
test("opaque cursors and provider partial data are never interpreted as an empty complete inbox", () => {
  assert.equal(
    inboxCursor({ pagination: { hasMore: true, nextCursor: "opaque/?x" } }),
    "opaque/?x",
  );
  assert.equal(
    inboxCursor({ pagination: { hasMore: true, cursor: "next" } }),
    "next",
  );
  assert.equal(
    inboxCursor({ pagination: { hasMore: false, nextCursor: "stale" } }),
    null,
  );
  assert.equal(inboxPartial({ meta: { accountsFailed: 1 } }), true);
  assert.equal(
    inboxPartial({ meta: { accountsSkipped: [{ accountId: "a" }] } }),
    true,
  );
  assert.deepEqual(inboxRows({ data: [{ id: "1" }, null, "x"] }), [
    { id: "1" },
  ]);
});
test("untrusted content is text and unsafe media links are not navigable", () => {
  assert.equal(inboxSafeLink("javascript:alert(1)"), null);
  assert.equal(inboxSafeLink("https://user:password@example.com/a"), null);
  assert.equal(inboxSafeLink("https://example.com/a"), "https://example.com/a");
  assert.equal(
    inboxTitle({ participantName: "<script>test</script>" }),
    "<script>test</script>",
  );
  assert.equal(inboxBody({ message: "<b>text</b>" }), "<b>text</b>");
});
test("gateway allows exact private inbox methods and forwards session and CSRF", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  for (const [method, path] of [
    ["GET", "inbox/lead-capture"],
    ["GET", "inbox/catalog"],
    ["GET", "inbox/accounts"],
    ["GET", "inbox/actions"],
    ["GET", `inbox/actions/${id}`],
    ["POST", "inbox/read"],
    ["POST", "inbox/prepare"],
    ["POST", `inbox/actions/${id}/confirm`],
  ]) {
    const handler = method === "GET" ? GET : POST;
    assert.equal(
      (await handler(request(method, path), context(path))).status,
      200,
      path,
    );
    assert.equal(
      calls.at(-1).options.headers.get("cookie"),
      "__Host-jardines_session=fixture-only",
    );
    assert.equal(calls.at(-1).options.headers.get("x-csrf-token"), "fixture");
    assert.equal(calls.at(-1).options.redirect, "error");
  }
});
test("gateway rejects unknown operations, query smuggling and wrong HTTP methods before any upstream call", async () => {
  for (const path of [
    "inbox/send",
    "inbox/execute",
    "inbox/read/../../social/settings",
    "inbox/actions/other/confirm",
  ])
    assert.equal(
      (await POST(request("POST", path), context(path))).status,
      404,
    );
  assert.equal(
    (await GET(request("GET", "inbox/read"), context("inbox/read"))).status,
    404,
  );
  assert.equal(
    (await PATCH(request("PATCH", "inbox/catalog"), context("inbox/catalog")))
      .status,
    404,
  );
  assert.equal(
    (
      await POST(
        request("POST", "inbox/read", "?accountId=foreign"),
        context("inbox/read"),
      )
    ).status,
    422,
  );
  assert.equal(calls.length, 0);
});
test("gateway bounds oversized inbox requests and rejects non-JSON provider content", async () => {
  assert.equal(
    (
      await POST(
        request("POST", "inbox/prepare", "", { body: "x".repeat(65537) }),
        context("inbox/prepare"),
      )
    ).status,
    413,
  );
  assert.equal(calls.length, 0);
  globalThis.fetch = async () =>
    new Response("<script>secret</script>", {
      headers: { "content-type": "text/html" },
    });
  assert.equal((await GET(request(), context("inbox/catalog"))).status, 502);
});
