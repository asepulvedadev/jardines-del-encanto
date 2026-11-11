import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

// Explicit opt-in: these checks never write a valid registration or customer data.
const base = process.env.DOMAIN_BASE_URL;
const options = { skip: !base };
const endpoint = () => `${base}/api/landing/registrations`;

test(
  "the branded HTTPS landing serves complete HTML and exact hero media",
  options,
  async () => {
    const response = await fetch(base);
    assert.equal(response.status, 200);
    const html = Buffer.from(await response.arrayBuffer());
    if (response.headers.has("content-length"))
      assert.equal(html.length, Number(response.headers.get("content-length")));
    assert.match(html.toString(), /<\/html>/);
    assert.equal(
      (html.toString().match(/data-lead-capture-trigger/g) ?? []).length,
      5,
    );
    const media = await fetch(`${base}/media/hero-loop.mp4`);
    assert.equal(media.status, 200);
    assert.deepEqual(
      Buffer.from(await media.arrayBuffer()),
      await readFile(
        new URL("../apps/web/public/media/hero-loop.mp4", import.meta.url),
      ),
    );
    const health = await (await fetch(`${base}/health`)).json();
    assert.equal(health.status, "ok");
    if (process.env.DOMAIN_EXPECTED_RELEASE)
      assert.equal(health.release, process.env.DOMAIN_EXPECTED_RELEASE);
  },
);

test(
  "the branded public form rejects foreign/missing origins before forwarding",
  options,
  async () => {
    for (const origin of [
      null,
      "null",
      "https://evil.invalid",
      `${base}.evil.invalid`,
      "https://jardines.2.24.111.40.sslip.io",
    ]) {
      const response = await fetch(endpoint(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(origin === null ? {} : { Origin: origin }),
        },
        body: "{}",
        redirect: "error",
      });
      assert.equal(response.status, 403, `Origin ${origin}`);
    }
  },
);

test(
  "the correct origin reaches unchanged form validation without creating a lead",
  options,
  async () => {
    for (const [type, body, status] of [
      ["application/json", "{}", 422],
      ["text/plain", "{}", 415],
      ["application/json", "x".repeat(2049), 413],
    ]) {
      const response = await fetch(endpoint(), {
        method: "POST",
        headers: { Origin: base, "Content-Type": type },
        body,
        redirect: "error",
      });
      assert.equal(response.status, status);
      assert.equal(response.headers.get("set-cookie"), null);
    }
  },
);

test(
  "private CRM stays on its existing origin and is not exposed through the alias",
  options,
  async () => {
    assert.equal(
      (
        await fetch(`${base}/api/crm/auth/login`, {
          method: "POST",
          body: "{}",
        })
      ).status,
      404,
    );
    const response = await fetch(`${base}/crm`, { redirect: "manual" });
    assert.equal(response.status, 302);
    assert.equal(
      response.headers.get("location"),
      "https://jardines.2.24.111.40.sslip.io/crm",
    );
  },
);

test(
  "the original preview retains its existing form origin policy",
  options,
  async () => {
    const preview = "https://jardines.2.24.111.40.sslip.io";
    for (const [origin, status] of [
      [preview, 422],
      [base, 403],
    ]) {
      const response = await fetch(`${preview}/api/landing/registrations`, {
        method: "POST",
        headers: { Origin: origin, "Content-Type": "application/json" },
        body: "{}",
        redirect: "error",
      });
      assert.equal(response.status, status);
    }
  },
);

test("HTTP and www redirect to the branded HTTPS apex", options, async () => {
  const hostname = new URL(base).hostname;
  for (const url of [
    `http://${hostname}/?domain-check=1`,
    `https://www.${hostname}/?domain-check=1`,
  ]) {
    const response = await fetch(url, { redirect: "manual" });
    assert.equal(response.status, 308);
    assert.equal(response.headers.get("location"), `${base}/?domain-check=1`);
  }
});
