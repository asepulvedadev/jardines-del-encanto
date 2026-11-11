import assert from "node:assert/strict";
import { test } from "node:test";

const base = process.env.LANDING_BASE_URL ?? "http://127.0.0.1:4317";
const site = "https://jardinesdelencanto.site";
const guide = "/lotes-acacias-desde-bogota-soacha";
const jsonLd = (html) =>
  [
    ...html.matchAll(
      /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g,
    ),
  ].map((match) => JSON.parse(match[1]));

test("public homepage is indexable with a single branded canonical and social metadata", async () => {
  const response = await fetch(base);
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.doesNotMatch(response.headers.get("x-robots-tag") ?? "", /noindex/);
  assert.match(html, /<meta name="robots" content="index, follow/);
  assert.doesNotMatch(html, /<meta name="robots" content="[^"]*noindex/);
  assert.equal((html.match(/rel="canonical"/g) ?? []).length, 1);
  const canonical = html.match(/rel="canonical" href="([^"]+)"/)?.[1];
  assert.equal(new URL(canonical).href, `${site}/`);
  assert.match(html, /<title>[^<]*Lotes en Acacías/);
  assert.match(
    html,
    /property="og:image" content="https:\/\/jardinesdelencanto.site\/media\/aerial-1920.webp"/,
  );
  assert.match(html, /name="twitter:card" content="summary_large_image"/);
  assert.match(html, new RegExp(`href="${guide}"`));
});

test("buyer guide serves original useful content without relocating the project", async () => {
  const response = await fetch(`${base}${guide}`);
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.doesNotMatch(response.headers.get("x-robots-tag") ?? "", /noindex/);
  assert.match(html, /<meta name="robots" content="index, follow/);
  assert.match(html, new RegExp(`rel="canonical" href="${site}${guide}"`));
  assert.equal((html.match(/<h1\b/g) ?? []).length, 1);
  assert.match(html, /Bogotá y Soacha/);
  assert.match(html, /Acacías, Meta/);
  assert.match(html, /13.000.000 COP/);
  assert.match(html, /no es una reserva/);
  assert.match(html, /documentación/);
  assert.match(html, /href="\/\#inicio"/);
  assert.doesNotMatch(
    html,
    /rentabilidad garantizada|valorización garantizada|a solo \d+ horas/i,
  );
});

test("robots and sitemap expose only canonical public pages, not the CRM", async () => {
  const robots = await fetch(`${base}/robots.txt`);
  assert.equal(robots.status, 200);
  const rules = await robots.text();
  assert.match(rules, /User-Agent: \*/i);
  assert.match(rules, /Allow: \//);
  for (const path of ["/crm", "/login", "/api/", "/health"])
    assert.ok(rules.includes(`Disallow: ${path}`));
  assert.ok(rules.includes(`Sitemap: ${site}/sitemap.xml`));
  const sitemap = await fetch(`${base}/sitemap.xml`);
  assert.equal(sitemap.status, 200);
  const xml = await sitemap.text();
  assert.deepEqual(
    [...xml.matchAll(/<loc>(.*?)<\/loc>/g)].map((match) => match[1]).sort(),
    [`${site}/`, `${site}${guide}`].sort(),
  );
  assert.doesNotMatch(xml, /sslip|\/crm|\/login|\/api/);
});

test("JSON-LD describes visible facts and keeps the property in Acacías", async () => {
  for (const path of ["/", guide]) {
    const html = await (await fetch(`${base}${path}`)).text();
    const documents = jsonLd(html);
    assert.equal(documents.length, 1);
    const graph = documents[0]["@graph"];
    const place = graph.find((node) => node["@type"] === "Place");
    assert.equal(place.address.addressLocality, "Acacías");
    assert.equal(place.address.addressRegion, "Meta");
    assert.equal(place.address.addressCountry, "CO");
    assert.equal(place.geo, undefined);
    const webpage = graph.find((node) => node["@type"] === "WebPage");
    assert.equal(webpage.url, `${site}${path}`);
    assert.equal(webpage.inLanguage, "es-CO");
    assert.equal(webpage.about["@id"], place["@id"]);
    const organization = graph.find((node) => node["@type"] === "Organization");
    assert.equal(organization.telephone, "+57 300 834 8478");
    assert.doesNotMatch(
      JSON.stringify(documents),
      /aggregateRating|reviewRating|streetAddress|RealEstateAgent|FAQPage|SearchAction/,
    );
  }
});

test("private, login and API routes remain noindex", async () => {
  const login = await fetch(`${base}/login`);
  assert.match(
    await login.text(),
    /<meta name="robots" content="noindex, nofollow/,
  );
  for (const path of ["/crm", "/api/landing/registrations", "/health"]) {
    const response = await fetch(`${base}${path}`, { redirect: "manual" });
    assert.match(response.headers.get("x-robots-tag") ?? "", /noindex/);
  }
});

test("the buyer guide reflows and leads back to the working interest modal", { skip: !process.env.HERO_PLAYWRIGHT_MODULE }, async () => {
  const { chromium } = await import(process.env.HERO_PLAYWRIGHT_MODULE);
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.HERO_CHROMIUM_PATH ? { executablePath: process.env.HERO_CHROMIUM_PATH } : {}),
  });
  try {
    for (const width of [320, 390, 768, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1100 }, reducedMotion: "reduce" });
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(`${base}${guide}`);
      assert.equal(await page.locator("h1").count(), 1);
      assert.ok((await page.locator("h1").innerText()).includes("Bogotá y Soacha"));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.evaluate(() => document.fonts.ready);
      if (process.env.SEO_SCREENSHOT_DIR && [390, 1440].includes(width)) {
        await page.screenshot({ path: `${process.env.SEO_SCREENSHOT_DIR}/jardines-buyer-guide-${width}.png` });
      }
      await page.getByRole("link", { name: "Conocer los lotes y registrar mi interés" }).click();
      // Native navigation commits while the new document is still loading.
      await page.waitForLoadState("load");
      await page.locator(".hero-actions [data-lead-capture-trigger]").click();
      await page.locator("dialog.lead-capture").waitFor({ state: "visible" });
      assert.equal(await page.locator("dialog[open]").count(), 1);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
});
