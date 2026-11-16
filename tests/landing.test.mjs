import assert from "node:assert/strict";
import { test } from "node:test";

const base = process.env.LANDING_BASE_URL ?? "http://127.0.0.1:4317";

test("the Bogotá and Soacha invitation is a standalone full-width section", async () => {
  const html = await (await fetch(base)).text();
  const main = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/)?.[1] ?? "";
  const buyer = main.match(/<section[^>]*class="section container buyer-intro"[\s\S]*?<\/section>/)?.[0] ?? "";
  assert.doesNotMatch(buyer, /event-buyer-reminder/);
  const invitation = main.match(/<section[^>]*id="invitacion-bogota-soacha"[\s\S]*?<\/section>/)?.[0] ?? "";
  assert.ok(invitation, "invitation is outside the buyer guide's two-column layout");
  assert.match(invitation, /<h2[^>]*id="event-buyer-title"/);
  assert.match(invitation, /Bogotá y Soacha, nos vemos este domingo/);
  assert.match(invitation, /dateTime="2026-11-22"/i);
  assert.match(invitation, /Cámara de Comercio de Soacha/);
  assert.match(invitation, /Consultar el evento por WhatsApp/);
  assert.match(invitation, /data-soacha-event-contact="true"/);
});

test("the landing uses the original project logo without desktop or mobile menus", async () => {
  const html = await (await fetch(base)).text();
  const header = html.match(/<header\b[^>]*>[\s\S]*?<\/header>/)?.[0] ?? "";
  const footer = html.match(/<footer\b[^>]*>[\s\S]*?<\/footer>/)?.[0] ?? "";
  assert.doesNotMatch(header, /<nav\b|Menú|menu-toggle|mobile-navigation/);
  for (const region of [header, footer]) {
    assert.match(region, /src="\/brand\/jardines-del-encanto-refinado.svg"/);
    assert.match(region, /alt="Jardines del Encanto"/);
    assert.match(region, /width="980" height="1160"/);
  }
  const logo = await fetch(`${base}/brand/jardines-del-encanto-refinado.svg`);
  assert.equal(logo.status, 200);
  assert.match(logo.headers.get("content-type"), /image\/svg\+xml/);
});

test("the public landing renders the supplied offer and correct WhatsApp destination", async () => {
  const response = await fetch(base);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /lang="es-CO"/);
  assert.match(html, /13 millones/);
  assert.match(html, /7 × 14/);
  assert.match(html, /24 meses/);
  assert.match(html, /https:\/\/wa\.me\/573008348478\?text=/);
  assert.match(html, /Visualización arquitectónica/);
  assert.match(html, /no refleja disponibilidad en tiempo real/);
  assert.doesNotMatch(html, /The project foundation is ready/);
});

test("actual media, architectural film and original PDF are served", async () => {
  for (const [path, type] of [
    ["/media/aerial-960.webp", "image/webp"],
    ["/media/entrance-960.webp", "image/webp"],
    ["/media/neighborhood-960.webp", "image/webp"],
    ["/media/gate-960.webp", "image/webp"],
    ["/media/masterplan.webp", "image/webp"],
    ["/media/plano-jardines-del-encanto.pdf", "application/pdf"],
    ["/media/recorrido-arquitectonico.mp4", "video/mp4"],
  ]) {
    const response = await fetch(`${base}${path}`, { method: "HEAD" });
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get("content-type"), new RegExp(type));
    assert.ok(Number(response.headers.get("content-length")) > 0, path);
  }
});

test("existing infrastructure health contract and security headers remain intact", async () => {
  const response = await fetch(`${base}/health`);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, "ok");
  const page = await fetch(base);
  assert.equal(page.headers.get("x-frame-options"), "DENY");
  assert.equal(page.headers.get("x-content-type-options"), "nosniff");
});

test("redesigned landing exposes hero film, transparent daily cycle and an inline lot explorer", async () => {
  const html = await (await fetch(base)).text();
  assert.match(html, /Precio de lanzamiento/);
  assert.match(html, /Quiero mi cupo/);
  assert.match(html, /data-hero-film/);
  assert.match(html, /data-launch-cycle/);
  assert.doesNotMatch(html, /Ciclo diario/);
  assert.doesNotMatch(html, /ACACÍAS, META/);
  assert.match(html, /aria-label="Contador de 24 horas"/);
  assert.doesNotMatch(html, /El contador se reinicia|No indica el vencimiento/);
  assert.match(html, /data-plan-explorer/);
  assert.match(html, /<svg[^>]+data-masterplan/);
  assert.doesNotMatch(html, /Descargar plano PDF/);
});

test("the landing has a dismissible named cupo form with explicit contact consent", async () => {
  const html = await (await fetch(base)).text();
  assert.match(html, /lead-capture-title/);
  assert.match(html, /Nombre completo/);
  assert.match(html, /Número de celular/);
  assert.match(html, /Autorizo a Jardines del Encanto/);
  assert.match(html, /name="consent"/);
  assert.doesNotMatch(html, /No hay formularios de captación/);
});

test("the Soacha event follows the hero and distinguishes the venue from the property", async () => {
  const html = await (await fetch(base)).text();
  const main = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/)?.[1] ?? "";
  assert.match(main, /<\/section><section[^>]*id="encuentro-soacha"/);
  assert.ok(main.indexOf('id="encuentro-soacha"') < main.indexOf('class="facts-section"'));
  const event = main.match(/<section[^>]*id="encuentro-soacha"[\s\S]*?<\/section>/)?.[0] ?? "";
  assert.match(event, /dateTime="2026-11-22"/i);
  assert.match(event, /Domingo/);
  assert.match(event, /Cámara de Comercio de Soacha/);
  assert.match(event, /Acacías, Meta/);
  assert.doesNotMatch(event, /entrada gratis|cupos limitados|descuento exclusivo|\d+:\d{2}/i);
});

test("event calls to action use the existing WhatsApp with an accurate prefilled request", async () => {
  const html = await (await fetch(base)).text();
  const main = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/)?.[1] ?? "";
  const links = [...main.matchAll(/<a\b[^>]*data-soacha-event-contact="true"[^>]*>[\s\S]*?<\/a>/g)];
  assert.equal(links.length, 3, "event, buyer section and final contact each offer WhatsApp");
  for (const [anchor] of links) {
    const url = new URL(anchor.match(/href="([^"]+)"/)[1].replaceAll("&amp;", "&"));
    assert.equal(url.origin, "https://wa.me");
    assert.equal(url.pathname, "/573008348478");
    assert.match(url.searchParams.get("text"), /domingo 22 de noviembre de 2026/);
    assert.match(url.searchParams.get("text"), /Cámara de Comercio de Soacha/);
    assert.match(url.searchParams.get("text"), /horario.*dirección exacta/);
    assert.match(anchor, /target="_blank"/);
    assert.match(anchor, /rel="noopener noreferrer"/);
  }
  assert.match(main, /¿Dónde y cuándo es el encuentro en Soacha\?/);
  assert.match(main, /¿Cómo puedo coordinar mi asistencia\?/);
  assert.equal((html.match(/data-lead-capture-trigger/g) ?? []).length, 5);
});

test("the event reflows, navigates and opens only the intended WhatsApp draft", {
  skip: !process.env.HERO_PLAYWRIGHT_MODULE,
}, async () => {
  const { chromium } = await import(process.env.HERO_PLAYWRIGHT_MODULE);
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.HERO_CHROMIUM_PATH ? { executablePath: process.env.HERO_CHROMIUM_PATH } : {}),
  });
  try {
    for (const width of [320, 390, 768, 1440]) {
      const context = await browser.newContext({
        viewport: { width, height: 1000 },
        reducedMotion: width === 1440 ? "no-preference" : "reduce",
      });
      // A returning visitor has already seen the automatic interest prompt.
      // Its first-visit trigger is covered separately by the hero browser tests.
      await context.addInitScript(() => sessionStorage.setItem("jardines-capture-seen-v1", "1"));
      // Keep external navigation local: no WhatsApp request or message is sent.
      await context.route("https://wa.me/**", route => route.fulfill({
        status: 200, contentType: "text/html", body: "<p>Local navigation fixture</p>",
      }));
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(base);
      await page.evaluate(() => document.fonts.ready);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px overflow`);
      assert.equal(await page.locator("header nav, .menu-toggle, .mobile-navigation").count(), 0);
      for (const image of await page.locator("header .brand-logo, footer .brand-logo").all()) {
        await image.scrollIntoViewIfNeeded();
        await page.waitForFunction(el => el.complete && el.naturalWidth > 0, await image.elementHandle());
        assert.ok(await image.evaluate(el => el.complete && el.naturalWidth > 0));
        const size = await image.boundingBox();
        assert.ok(size.width >= 88 && size.height > size.width, "original logo retains its portrait proportions");
      }
      await page.locator(".hero-event-link").click();
      await page.waitForURL("**/#encuentro-soacha");
      const event = page.locator("#encuentro-soacha");
      assert.equal(await event.locator("time").getAttribute("datetime"), "2026-11-22");
      assert.ok((await event.locator("h2").innerText()).includes("Domingo 22"));
      assert.equal(await event.locator(".event-main-venue").innerText(), "Cámara de Comercio de Soacha");
      assert.ok((await event.innerText()).includes("BOGOTÁ Y SOACHA"));
      const contact = event.locator("[data-soacha-event-contact]");
      await contact.focus();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      assert.ok(await contact.evaluate(el => el.matches(":focus-visible")));
      assert.notEqual(await contact.evaluate(el => getComputedStyle(el).outlineStyle), "none");
      if (process.env.EVENT_SCREENSHOT_DIR) {
        await event.screenshot({ path: `${process.env.EVENT_SCREENSHOT_DIR}/soacha-event-${width}.png` });
      }
      const popupPromise = page.waitForEvent("popup");
      await contact.click();
      const popup = await popupPromise;
      await popup.waitForLoadState("domcontentloaded");
      const destination = new URL(popup.url());
      assert.equal(destination.hostname, "wa.me");
      assert.equal(destination.pathname, "/573008348478");
      assert.match(destination.searchParams.get("text"), /domingo 22 de noviembre de 2026/);
      await popup.close();
      const invitation = page.locator("#invitacion-bogota-soacha");
      const invitationBox = await invitation.boundingBox();
      assert.ok(Math.abs(invitationBox.x) <= 1);
      assert.ok(Math.abs(invitationBox.width - width) <= 1, `${width}px invitation fills viewport width`);
      if (width >= 1024) {
        assert.ok(invitationBox.height >= 1000, "desktop invitation fills viewport height");
        assert.ok(await invitation.locator("h2").evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 60));
      } else {
        assert.ok(invitationBox.height < 1000, "mobile/tablet invitation follows content height");
      }
      await invitation.scrollIntoViewIfNeeded();
      if (process.env.EVENT_SCREENSHOT_DIR) {
        await invitation.screenshot({ path: `${process.env.EVENT_SCREENSHOT_DIR}/full-invitation-${width}.png` });
      }
      const invitationPopupPromise = page.waitForEvent("popup");
      await invitation.locator("[data-soacha-event-contact]").click();
      const invitationPopup = await invitationPopupPromise;
      await invitationPopup.waitForLoadState("domcontentloaded");
      assert.equal(invitationPopup.url(), destination.href);
      await invitationPopup.close();
      await page.locator("summary").filter({ hasText: "¿Cómo puedo coordinar mi asistencia?" }).click();
      assert.ok(await page.getByText(/Abrir el chat no confirma tu asistencia/).isVisible());
      await page.locator(".hero-actions [data-lead-capture-trigger]").click();
      await page.locator("dialog.lead-capture").waitFor({ state: "visible" });
      assert.equal(await page.locator("dialog[open]").count(), 1);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally {
    await browser.close();
  }
});
