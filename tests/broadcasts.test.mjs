import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { GET, POST } from "../apps/web/app/api/crm/[...path]/route.ts";
import { csvHeaders } from "../apps/web/components/crm/broadcast-model.ts";
const originalFetch = globalThis.fetch,
  originalBase = process.env.API_BASE_URL,
  originalOrigin = process.env.CRM_ORIGIN;
let calls = [];
beforeEach(() => {
  calls = [];
  process.env.CRM_ORIGIN = "https://crm.example.invalid";
  process.env.API_BASE_URL = "http://private-api:8000";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({ items: [] });
  };
});
afterEach(() => {
  if (originalOrigin === undefined) delete process.env.CRM_ORIGIN;
  else process.env.CRM_ORIGIN = originalOrigin;
  globalThis.fetch = originalFetch;
  if (originalBase === undefined) delete process.env.API_BASE_URL;
  else process.env.API_BASE_URL = originalBase;
});
function request(path, method = "GET", body, query = "") {
  const r = new Request(`https://crm.example.invalid/api/crm/${path}${query}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      Origin: "https://crm.example.invalid",
      "X-CSRF-Token": "fixture",
    },
    body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
  });
  Object.defineProperty(r, "cookies", { value: { get: () => undefined } });
  return r;
}
const context = (path) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
test("CSV header reader handles BOM separators quotes and escaped quotes", () => {
  assert.deepEqual(csvHeaders("\uFEFFnombre;celular\nAna;3001234567"), [
    "nombre",
    "celular",
  ]);
  assert.deepEqual(csvHeaders('"Nombre, completo",celular\n'), [
    "Nombre, completo",
    "celular",
  ]);
  assert.deepEqual(csvHeaders('"Nombre ""completo"""\tcelular\n'), [
    'Nombre "completo"',
    "celular",
  ]);
});
test("finite broadcast routes forward only to the private API", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  for (const [path, method] of [
    ["broadcasts", "GET"],
    ["broadcasts/catalog", "GET"],
    ["broadcasts/preview", "POST"],
    ["broadcasts/templates", "POST"],
    ["broadcasts/filter", "POST"],
    [`broadcasts/${id}`, "GET"],
    [`broadcasts/${id}/send`, "POST"],
    [`broadcasts/${id}/refresh`, "POST"],
  ]) {
    const response = await (method === "GET" ? GET : POST)(
      request(path, method),
      context(path),
    );
    assert.equal(response.status, 200);
  }
  assert.equal(calls.length, 8);
  assert.ok(
    calls.every((c) =>
      c.url.startsWith("http://private-api:8000/crm/broadcasts"),
    ),
  );
  assert.equal(calls[0].options.headers.get("authorization"), null);
});
test("unknown route query and oversized CSV cannot reach the API", async () => {
  for (const path of [
    "broadcasts/../../social",
    "broadcasts/not-a-uuid/send",
    "broadcasts/export-everything",
  ])
    assert.equal(
      (await POST(request(path, "POST"), context(path))).status,
      404,
    );
  assert.equal(
    (
      await GET(
        request("broadcasts", "GET", undefined, "?accountId=other"),
        context("broadcasts"),
      )
    ).status,
    422,
  );
  assert.equal(
    (
      await POST(
        request("broadcasts/preview", "POST", {
          csv_text: "x".repeat(1024 * 1024),
        }),
        context("broadcasts/preview"),
      )
    ).status,
    413,
  );
  assert.equal(calls.length, 0);
});
test("shared workspace and existing campaigns routes remain unchanged", async () => {
  for (const path of ["workspace", "campaigns", "analytics/summary"]) {
    const response = await GET(request(path), context(path));
    assert.equal(response.status, 200);
  }
  assert.equal(calls[0].url, "http://private-api:8000/crm/workspace");
  assert.equal(calls[1].url, "http://private-api:8000/crm/campaigns");
  assert.equal(
    calls[2].url,
    "http://private-api:8000/crm/analytics/summary?days=7",
  );
});
