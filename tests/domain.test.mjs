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
  "canonical login serves the form and anonymous CRM remains protected",
  options,
  async () => {
    const login = await fetch(`${base}/login`, { redirect: "manual" });
    assert.equal(login.status, 200);
    assert.match(await login.text(), /Bienvenido de nuevo/);
    assert.match(login.headers.get("x-robots-tag"), /noindex/);
    const crm = await fetch(`${base}/crm`, { redirect: "manual" });
    assert.ok([302, 303, 307, 308].includes(crm.status));
    assert.equal(
      new URL(crm.headers.get("location"), base).href,
      `${base}/login`,
    );
    assert.equal((await fetch(`${base}/api/crm/auth/session`)).status, 401);
  },
);

test(
  "canonical login API enforces the exact Origin before credentials are evaluated",
  options,
  async () => {
    for (const [origin, expected] of [
      [null, 403],
      ["https://evil.invalid", 403],
      ["https://jardines.2.24.111.40.sslip.io", 403],
      [base, 422],
    ]) {
      const response = await fetch(`${base}/api/crm/auth/login`, {
        method: "POST",
        redirect: "manual",
        headers: {
          "Content-Type": "application/json",
          ...(origin ? { Origin: origin } : {}),
        },
        body: "{}",
      });
      assert.equal(response.status, expected);
      assert.equal(response.headers.get("set-cookie"), null);
    }
  },
);

test(
  "legacy documents redirect to the canonical host without replaying POSTs",
  options,
  async () => {
    const preview = "https://jardines.2.24.111.40.sslip.io";
    for (const path of [
      "/login",
      "/crm",
      "/crm?domain-check=1",
      "/crm/tasks",
    ]) {
      const response = await fetch(preview + path, { redirect: "manual" });
      assert.equal(response.status, 308);
      assert.equal(response.headers.get("location"), base + path);
    }
    assert.equal(
      (
        await fetch(preview + "/api/crm/auth/login", {
          method: "POST",
          redirect: "manual",
          body: "{}",
        })
      ).status,
      403,
    );
    assert.equal(
      (
        await fetch(preview + "/login", {
          method: "POST",
          redirect: "manual",
          body: "{}",
        })
      ).status,
      405,
    );
    assert.equal(
      (
        await fetch(preview + "/api/landing/registrations", {
          method: "POST",
          redirect: "manual",
          body: "{}",
        })
      ).status,
      403,
    );
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

test(
  "the existing legacy webhook still rejects unsigned deliveries",
  options,
  async () => {
    const response = await fetch(
      "https://jardines.2.24.111.40.sslip.io/api/integrations/zernio/webhook",
      {
        method: "POST",
        redirect: "manual",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    assert.equal(response.status, 400);
    assert.equal((await response.json()).detail, "invalid_signature");
  },
);
