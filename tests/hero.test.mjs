import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";

// Browser checks are opt-in so the existing HTTP suite needs no browser install.
const browserModule = process.env.HERO_PLAYWRIGHT_MODULE;
const browserOptions = {
  headless: true,
  ...(process.env.HERO_CHROMIUM_PATH
    ? { executablePath: process.env.HERO_CHROMIUM_PATH }
    : {}),
  args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"],
};

async function withBrowser(run) {
  const { chromium } = await import(browserModule);
  const browser = await chromium.launch(browserOptions);
  try {
    await run(browser);
  } finally {
    await browser.close();
  }
}

const base = process.env.LANDING_BASE_URL ?? "http://127.0.0.1:4317";

test("the hero offers an opt-in 3D experience without hiding contact or the 2D plan", async () => {
  const html = await (await fetch(base)).text();
  assert.match(html, /data-hero-experience/);
  assert.match(html, /aria-pressed="false"[^>]*>[^<]*Maqueta 3D/);
  assert.match(html, /href="#plano"/);
  assert.match(html, /Quiero mi cupo/);
  assert.match(html, /Visualización arquitectónica/);
  assert.match(html, /Maqueta conceptual/);
});

test("the hero keeps controls and the external media disclaimer without decorative copy", async () => {
  const html = await (await fetch(base)).text();
  const hero = html.match(
    /<figure[^>]*data-hero-experience[\s\S]*?<\/figure>/,
  )?.[0];
  assert.ok(hero, "hero must render");
  assert.doesNotMatch(
    hero,
    /IMAGINA TU COMIENZO|Del plano|Explorar en 3D|UNA NUEVA PERSPECTIVA|Un lugar para verlo|01 \/ RECORRIDO/,
  );
  assert.match(hero, /Maqueta 3D/);
  assert.match(hero, /Reproducir recorrido/);
  assert.match(hero, /Visualización arquitectónica/);
});

test("the hero uses a dedicated silent film and a static poster", async () => {
  const html = await (await fetch(base)).text();
  assert.match(html, /data-hero-film/);
  assert.match(html, /poster="\/media\/hero-poster.webp"/);
  assert.match(html, /preload="none"/);
  assert.match(html, /Reproducir recorrido/);
  const response = await fetch(`${base}/media/hero-loop.mp4`, {
    method: "HEAD",
  });
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /video\/mp4/);
});

test("public responses deliver the complete HTML and exact hero assets", async () => {
  const document = await fetch(base);
  assert.equal(document.status, 200);
  const bytes = Buffer.from(await document.arrayBuffer());
  const length = document.headers.get("content-length");
  if (length !== null) assert.equal(bytes.length, Number(length));
  assert.match(bytes.toString(), /<\/html>/);
  for (const name of ["hero-loop.mp4", "hero-poster.webp"]) {
    const response = await fetch(`${base}/media/${name}`);
    assert.equal(response.status, 200);
    assert.deepEqual(
      Buffer.from(await response.arrayBuffer()),
      await readFile(new URL(`../apps/web/public/media/${name}`, import.meta.url)),
      `${name} must reach the visitor without proxy truncation`,
    );
  }
});

test(
  "3D loads only on demand, supports selection and keyboard, and disposes on exit",
  { skip: !browserModule },
  async () => {
    await withBrowser(async (browser) => {
      const page = await browser.newPage({
        viewport: { width: 1440, height: 1000 },
      });
      const requests = [];
      const errors = [];
      page.on("request", (request) => requests.push(request.url()));
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "warning" && message.text().startsWith("THREE."))
          errors.push(message.text());
      });
      await page.goto(base);
      await page
        .getByRole("button", { name: "Pausar recorrido", exact: true })
        .waitFor();
      const duration = await page
        .locator("[data-hero-film] video")
        .evaluate((video) => video.duration);
      assert.ok(
        duration > 15 && duration < 20,
        "the hero must include the appended park sequence without replacing its entrance and lot shots",
      );
      assert.equal(await page.locator(".hero-plan-canvas canvas").count(), 0);
      assert.ok(
        !requests.some((url) => /hero-scene|three_src|three_build/.test(url)),
        "3D renderer must not load before opting in",
      );
      await page
        .getByRole("button", { name: "Pausar recorrido", exact: true })
        .click();
      assert.equal(
        await page
          .locator("[data-hero-film] video")
          .evaluate((video) => video.paused),
        true,
      );
      await page
        .getByRole("button", { name: "Maqueta 3D", exact: true })
        .click();
      assert.equal(
        await page
          .getByRole("button", { name: "Maqueta 3D", exact: true })
          .evaluate((button) => button === document.activeElement),
        true,
      );
      await page.locator('[data-3d-ready="true"]').waitFor();
      assert.equal(
        await page
          .locator(
            ".hero-plan-heading, .hero-plan-instruction, .hero-world-corner",
          )
          .count(),
        0,
      );
      const canvas = page.locator(".hero-plan-canvas canvas");
      await canvas.focus();
      const original = await canvas.screenshot();
      await canvas.press("ArrowRight");
      assert.notDeepEqual(
        await canvas.screenshot(),
        original,
        "keyboard rotation must change the rendered view",
      );
      await page.getByLabel("Acércate a una manzana").selectOption("21a");
      await page
        .getByRole("status")
        .filter({ hasText: "Manzana 21a seleccionada." })
        .waitFor();
      await page
        .getByRole("button", { name: "Restablecer vista general", exact: true })
        .click();
      assert.equal(
        await page.getByLabel("Acércate a una manzana").inputValue(),
        "",
      );
      const previous = await canvas.elementHandle();
      await page
        .getByRole("button", { name: "Recorrido", exact: true })
        .click();
      assert.equal(
        await previous.evaluate((element) => element.isConnected),
        false,
      );
      assert.equal(await canvas.count(), 0);
      await page
        .getByRole("button", { name: "Maqueta 3D", exact: true })
        .click();
      await page.locator('[data-3d-ready="true"]').waitFor();
      assert.equal(await canvas.count(), 1);
      assert.deepEqual(errors, []);
    });
  },
);

test(
  "an interrupted play request does not disable a healthy video",
  { skip: !browserModule },
  async () => {
    await withBrowser(async (browser) => {
      const page = await browser.newPage({ reducedMotion: "reduce" });
      await page.addInitScript(() => {
        HTMLMediaElement.prototype.play = function () {
          return Promise.reject(
            new DOMException("Playback interrupted by pause", "AbortError"),
          );
        };
      });
      await page.goto(base);
      const play = page.getByRole("button", {
        name: "Reproducir recorrido",
        exact: true,
      });
      await play.click();
      assert.equal(await play.isEnabled(), true);
      assert.equal(await page.locator(".hero-cinema-error").count(), 0);
    });
  },
);

test(
  "mobile and reduced-motion visitors retain a poster without automatic video downloads",
  { skip: !browserModule },
  async () => {
    await withBrowser(async (browser) => {
      for (const [width, reducedMotion, saveData] of [
        [320, "reduce", false],
        [390, "reduce", false],
        [768, "reduce", false],
        [1440, "reduce", false],
        [390, "no-preference", false],
        [1440, "no-preference", true],
      ]) {
        const page = await browser.newPage({
          viewport: { width, height: 900 },
          reducedMotion,
        });
        if (saveData)
          await page.addInitScript(() => {
            Object.defineProperty(navigator, "connection", {
              value: { saveData: true, effectiveType: "4g" },
              configurable: true,
            });
          });
        const media = [];
        page.on("request", (request) => {
          if (request.resourceType() === "media") media.push(request.url());
        });
        await page.goto(base);
        await page
          .getByRole("button", { name: "Reproducir recorrido", exact: true })
          .waitFor();
        const mediaBox = await page
          .locator("[data-hero-experience]")
          .boundingBox();
        const copyBox = await page.locator(".hero-copy").boundingBox();
        if (width <= 900) {
          assert.ok(
            mediaBox.y + mediaBox.height <= copyBox.y,
            `media must precede copy at ${width}px`,
          );
        } else {
          assert.ok(
            copyBox.x + copyBox.width <= mediaBox.x,
            "desktop copy must stay to the left of the media",
          );
        }
        assert.equal(
          await page
            .locator("[data-hero-film] video")
            .evaluate((video) => video.paused),
          true,
        );
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          `overflow at ${width}px`,
        );
        assert.deepEqual(media, []);
        await page
          .getByRole("button", { name: "Maqueta 3D", exact: true })
          .click();
        await page.locator('[data-3d-ready="true"]').waitFor();
        await page.getByLabel("Acércate a una manzana").selectOption("1");
        assert.equal(
          await page.getByLabel("Acércate a una manzana").inputValue(),
          "1",
        );
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
        );
        await page.close();
      }
    });
  },
);

test(
  "unsupported or lost WebGL falls back to the original plan with no dead end",
  { skip: !browserModule },
  async () => {
    await withBrowser(async (browser) => {
      for (const unsupported of [true, false]) {
        const page = await browser.newPage({ reducedMotion: "reduce" });
        if (unsupported)
          await page.addInitScript(() => {
            const original = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (type, ...args) {
              if (type.startsWith("webgl")) return null;
              return original.call(this, type, ...args);
            };
          });
        await page.goto(base);
        await page
          .getByRole("button", { name: "Maqueta 3D", exact: true })
          .click();
        if (!unsupported) {
          await page.locator('[data-3d-ready="true"]').waitFor();
          await page.locator(".hero-plan-canvas canvas").evaluate((canvas) => {
            canvas
              .getContext("webgl2")
              .getExtension("WEBGL_lose_context")
              .loseContext();
          });
        }
        await page
          .getByRole("link", { name: "Explorar el plano 2D" })
          .waitFor();
        assert.equal(
          await page.locator(".hero-plan-fallback img").isVisible(),
          true,
        );
        await page
          .getByRole("button", { name: "Recorrido", exact: true })
          .click();
        assert.equal(
          await page.locator("[data-hero-film] video").isVisible(),
          true,
        );
        await page.close();
      }
    });
  },
);
