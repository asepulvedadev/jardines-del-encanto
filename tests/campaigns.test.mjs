import assert from "node:assert/strict";
import { test, beforeEach, afterEach } from "node:test";
import { GET, POST, PATCH } from "../apps/web/app/api/crm/[...path]/route.ts";
import {
  renderCampaignText,
  campaignIssues,
  safeCampaignLink,
} from "../apps/web/components/crm/campaign-types.ts";

const originalFetch = globalThis.fetch;
const originalBase = process.env.API_BASE_URL;
const originalOrigin = process.env.CRM_ORIGIN;
let calls;
beforeEach(() => {
  calls = [];
  process.env.API_BASE_URL = "http://private-api:8000";
  process.env.CRM_ORIGIN = "https://crm.example.invalid";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json({ items: [] });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  for (const [key, value] of [
    ["API_BASE_URL", originalBase],
    ["CRM_ORIGIN", originalOrigin],
  ])
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
});
const context = (path) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
function request(method = "GET", query = "", body = {}) {
  const r = new Request(
    `https://crm.example.invalid/api/crm/campaigns${query}`,
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
  Object.defineProperty(r, "cookies", {
    value: {
      get: (name) =>
        name === "__Host-jardines_session"
          ? { name, value: "fixture-only" }
          : undefined,
    },
  });
  return r;
}

test("campaign allowlist supports drafts only and preserves session and csrf forwarding", async () => {
  for (const [method, path] of [
    ["GET", "campaigns"],
    ["POST", "campaigns"],
    ["PATCH", "campaigns/campaign-01"],
  ])
    assert.equal(
      (await { GET, POST, PATCH }[method](request(method), context(path)))
        .status,
      200,
    );
  assert.equal(calls[2].options.headers.get("x-csrf-token"), "fixture");
  assert.equal(
    calls[2].options.headers.get("cookie"),
    "__Host-jardines_session=fixture-only",
  );
  const previous = calls.length;
  for (const path of [
    "campaigns/send",
    "campaigns/submit",
    "campaigns/activate",
    "campaigns/campaign-01/send",
    "campaigns/media/../../secrets",
  ])
    assert.equal((await POST(request("POST"), context(path))).status, 404);
  assert.equal(
    (await GET(request("GET", "?url=https://evil.test"), context("campaigns")))
      .status,
    422,
  );
  assert.equal(calls.length, previous);
});

test("campaign gateway bounds writes and enforces origin without fetching upstream", async () => {
  const wrong = request("POST");
  wrong.headers.set("origin", "https://evil.test");
  assert.equal((await POST(wrong, context("campaigns"))).status, 403);
  assert.equal(
    (
      await PATCH(
        request("PATCH", "", { text: "x".repeat(16385) }),
        context("campaigns/campaign-01"),
      )
    ).status,
    413,
  );
  assert.equal(calls.length, 0);
});

test("campaign private images are bounded and content-checked without changing existing download routes", async () => {
  const png = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0]);
  globalThis.fetch = async () =>
    new Response(png, { headers: { "content-type": "image/png" } });
  const response = await GET(request(), context("campaigns/media/campaign-01"));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "image/png");
  assert.equal(response.headers.get("cache-control"), "no-store, private");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  globalThis.fetch = async () =>
    new Response("<script>bad</script>", {
      headers: { "content-type": "image/png" },
    });
  assert.equal(
    (await GET(request(), context("campaigns/media/campaign-01"))).status,
    502,
  );
  globalThis.fetch = async () =>
    new Response(new Uint8Array(5 * 1024 * 1024 + 1), {
      headers: { "content-type": "image/png" },
    });
  assert.equal(
    (await GET(request(), context("campaigns/media/campaign-01"))).status,
    502,
  );
  globalThis.fetch = async () =>
    Response.json({ detail: "authentication_required" }, { status: 401 });
  assert.equal(
    (await GET(request(), context("campaigns/media/campaign-01"))).status,
    401,
  );
});

const draft = {
  name: "Prueba",
  audience: "invitation",
  suggested_date: null,
  image_id: "campaign-01",
  body: "Hola {{nombre}}. {{enlace}}",
  variables: [
    { key: "nombre", kind: "text", example: "María" },
    {
      key: "enlace",
      kind: "link",
      example: "https://jardinesdelencanto.site/#plano",
    },
  ],
  buttons: [
    { kind: "url", label: "Ver plano", value: "{{enlace}}" },
    { kind: "reply", label: "Sí", value: "si" },
  ],
};
test("named variables resolve once, link variables are safe, and unresolved values block saving", () => {
  assert.equal(
    renderCampaignText(draft.body, draft.variables),
    "Hola María. https://jardinesdelencanto.site/#plano",
  );
  assert.deepEqual(campaignIssues(draft), []);
  assert.ok(campaignIssues({ ...draft, body: "{{desconocida}}" }).length);
  assert.ok(campaignIssues({ ...draft, body: "{{nombre}" }).length);
  assert.ok(
    campaignIssues({
      ...draft,
      buttons: [{ kind: "url", label: "Abrir", value: "{{nombre}}" }],
    }).length,
  );
  assert.equal(safeCampaignLink("javascript:alert(1)"), false);
  assert.equal(safeCampaignLink("https://user:password@example.com/"), false);
  assert.equal(safeCampaignLink("https://127.0.0.1/"), false);
  assert.equal(
    renderCampaignText("{{nombre}}", [
      { key: "nombre", example: "{{enlace}}" },
    ]),
    "{{enlace}}",
  );
});

test("review gateway exposes only explicit review operations and short-lived image capabilities", async () => {
  for (const [method, path] of [
    ["GET", "campaigns/review-accounts"],
    ["POST", "campaigns/campaign-01/review-preview"],
    ["GET", "campaigns/campaign-01/reviews"],
    ["POST", "campaigns/campaign-01/reviews"],
    [
      "POST",
      "campaigns/campaign-01/reviews/11111111-1111-1111-1111-111111111111/refresh",
    ],
  ])
    assert.equal(
      (await { GET, POST }[method](request(method), context(path))).status,
      200,
    );
  const count = calls.length;
  for (const path of [
    "campaigns/campaign-01/reviews/send",
    "campaigns/campaign-01/reviews/approve",
    "campaigns/review-media/../../private",
    "campaigns/campaign-01/activate",
  ])
    assert.equal((await POST(request("POST"), context(path))).status, 404);
  assert.equal(calls.length, count);
  const wrong = request("POST");
  wrong.headers.set("origin", "https://evil.test");
  assert.equal(
    (await POST(wrong, context("campaigns/campaign-01/reviews"))).status,
    403,
  );
  globalThis.fetch = async () =>
    new Response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), {
      headers: { "content-type": "image/png" },
    });
  const media = await GET(
    request(),
    context(
      `campaigns/review-media/11111111-1111-1111-1111-111111111111/${"a".repeat(43)}`,
    ),
  );
  assert.equal(media.status, 200);
  assert.match(media.headers.get("cache-control"), /no-store/);
});
