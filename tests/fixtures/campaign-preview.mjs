// Synthetic loopback-only UI fixture. No CRM database or provider connections.
import { createServer } from "node:http";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../../", import.meta.url));
export async function startCampaignPreview(port = 0) {
  const scratch = await mkdtemp(join(tmpdir(), "jardines-campaign-"));
  const { webpack } = require("next/dist/compiled/webpack/webpack");
  await writeFile(
    join(scratch, "loader.cjs"),
    `const ts=require(${JSON.stringify(require.resolve("typescript"))});module.exports=function(source){return ts.transpileModule(source,{fileName:this.resourcePath,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;};`,
  );
  await writeFile(join(scratch, "empty.cjs"), "module.exports=()=>'';");
  await writeFile(
    join(scratch, "navigation.cjs"),
    "const router={replace(){},refresh(){},push(){}};module.exports={useRouter:()=>router};",
  );
  const data = {
    contacts: [],
    deals: [],
    tasks: [],
    activities: [],
    counts: { contacts: 0, active: 0, won: 0, pending: 0, overdue: 0 },
    limited: false,
  };
  await writeFile(
    join(scratch, "entry.tsx"),
    `import React from 'react';import {createRoot} from 'react-dom/client';import {Workspace} from ${JSON.stringify(join(root, "apps/web/components/crm/workspace"))};createRoot(document.getElementById('app')!).render(<Workspace initialData={${JSON.stringify(data)}} user={{username:'Vista de prueba',role:'admin'}} csrf="fixture-only"/>);`,
  );
  try {
    await new Promise((done, reject) =>
      webpack(
        {
          mode: "development",
          devtool: false,
          entry: join(scratch, "entry.tsx"),
          output: { path: scratch, filename: "bundle.js" },
          resolve: {
            extensions: [".tsx", ".ts", ".js"],
            modules: [join(root, "node_modules")],
            alias: { "next/navigation$": join(scratch, "navigation.cjs") },
          },
          module: {
            rules: [
              { test: /\.tsx?$/, use: join(scratch, "loader.cjs") },
              { test: /\.css$/, use: join(scratch, "empty.cjs") },
            ],
          },
          optimization: { minimize: false },
        },
        (error, stats) =>
          error || stats.hasErrors()
            ? reject(
                error ||
                  new Error(stats.toString({ all: false, errors: true })),
              )
            : done(),
      ),
    );
  } catch (error) {
    await rm(scratch, { recursive: true });
    throw error;
  }
  const items = JSON.parse(
    await readFile(join(root, "apps/api/app/campaigns/seeds.json"), "utf8"),
  ).map((item) => ({
    ...item,
    version: 0,
    status: "local_draft",
    updated_at: null,
  }));
  const writes = [];
  const reviews = [];
  const reviewAccount = {
    id: "aaaaaaaaaaaaaaaaaaaaaaaa",
    label: "WhatsApp de prueba · Sin conexión real",
  };
  const server = createServer(async (req, res) => {
    try {
      res.setHeader("Cache-Control", "no-store");
      if (req.url === "/bundle.js") {
        res.setHeader("Content-Type", "text/javascript");
        res.end(await readFile(join(scratch, "bundle.js")));
        return;
      }
      if (req.url === "/font.ttf") {
        res.setHeader("Content-Type", "font/ttf");
        res.end(
          await readFile(join(root, "apps/web/app/fonts/Manrope-Variable.ttf")),
        );
        return;
      }
      if (req.url === "/styles.css") {
        res.setHeader("Content-Type", "text/css");
        res.end(
          (
            await Promise.all(
              ["../globals.css", "crm.css", "campaigns.css"].map((p) =>
                readFile(join(root, "apps/web/app/crm", p), "utf8").then(
                  (css) => css.replace('@import "tailwindcss";', ""),
                ),
              ),
            )
          ).join("\n"),
        );
        return;
      }
      if (req.url === "/brand/jardines-del-encanto-refinado.svg") {
        res.setHeader("Content-Type", "image/svg+xml");
        res.end(await readFile(join(root, "apps/web/public", req.url)));
        return;
      }
      const media =
        /^\/api\/crm\/campaigns\/media\/(campaign-(0[1-9]|1[0-5]))$/.exec(
          req.url,
        );
      if (media) {
        res.setHeader("Content-Type", "image/png");
        res.end(
          await readFile(
            join(root, "apps/api/app/campaigns/assets", `${media[1]}.png`),
          ),
        );
        return;
      }
      if (req.url.startsWith("/api/")) {
        res.setHeader("Content-Type", "application/json");
        if (req.method === "GET") {
          if (req.url === "/api/crm/campaigns/review-accounts") {
            res.end(JSON.stringify({ items: [reviewAccount] }));
            return;
          }
          const history = /^\/api\/crm\/campaigns\/([^/]+)\/reviews$/.exec(
            req.url,
          );
          if (history) {
            res.end(
              JSON.stringify({
                items: reviews.filter((row) => row.slug === history[1]),
              }),
            );
            return;
          }
          res.end(JSON.stringify({ items, limited: false }));
          return;
        }
        let body = "";
        for await (const chunk of req) body += chunk;
        const payload = JSON.parse(body);
        writes.push({ path: req.url, payload });
        const reviewPath =
          /^\/api\/crm\/campaigns\/([^/]+)\/(review-preview|reviews)(?:\/([^/]+)\/refresh)?$/.exec(
            req.url,
          );
        if (reviewPath) {
          const draft = items.find((row) => row.id === reviewPath[1]);
          if (reviewPath[3]) {
            const row = reviews.find((row) => row.id === reviewPath[3]);
            row.status = "APPROVED";
            row.checked_at = new Date().toISOString();
            draft.review = {
              id: row.id,
              version: row.version,
              status: row.status,
            };
            res.end(JSON.stringify(row));
            return;
          }
          const name = `jardines_fixture_${draft.id.replaceAll("-", "_")}_v${draft.version}`;
          if (reviewPath[2] === "review-preview") {
            res.end(
              JSON.stringify({
                name,
                version: draft.version,
                account: reviewAccount,
                category: "MARKETING",
                language: "es_CO",
                components: [],
              }),
            );
            return;
          }
          if (
            reviews.some(
              (row) => row.slug === draft.id && row.version === draft.version,
            )
          ) {
            res.statusCode = 409;
            res.end(JSON.stringify({ detail: "review_already_requested" }));
            return;
          }
          const row = {
            id: "11111111-1111-4111-8111-111111111111",
            slug: draft.id,
            version: draft.version,
            account_id: reviewAccount.id,
            account_label: reviewAccount.label,
            name,
            snapshot: structuredClone(draft.document),
            status: "PENDING",
            provider_id: "12345",
            category: "MARKETING",
            created_at: new Date().toISOString(),
            checked_at: new Date().toISOString(),
          };
          reviews.unshift(row);
          draft.review = {
            id: row.id,
            version: row.version,
            status: row.status,
          };
          res.statusCode = 201;
          res.end(JSON.stringify(row));
          return;
        }
        if (req.method === "POST" && req.url === "/api/crm/campaigns") {
          const item = {
            id: `draft-fixture-${items.length}`,
            document: payload.document,
            status: "local_draft",
            version: 1,
            updated_at: "2026-11-15T15:00:00Z",
          };
          items.push(item);
          res.statusCode = 201;
          res.end(JSON.stringify(item));
          return;
        }
        const item = items.find(
          (item) => req.url === `/api/crm/campaigns/${item.id}`,
        );
        if (
          req.method === "PATCH" &&
          item &&
          item.version === payload.version
        ) {
          item.document = payload.document;
          item.version++;
          res.end(JSON.stringify(item));
          return;
        }
        res.statusCode = 409;
        res.end(JSON.stringify({ detail: "record_changed" }));
        return;
      }
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(
        `<!doctype html><html lang="es"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Plantillas · Vista local</title><link rel="stylesheet" href="/styles.css"><style>@font-face{font-family:Manrope;src:url('/font.ttf')}*{box-sizing:border-box}body{margin:0;background:#f6f7f1;font-family:Manrope,system-ui,sans-serif}button,input,select,textarea{font:inherit}.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}</style><div id="app"></div><script src="/bundle.js"></script></html>`,
      );
    } catch {
      res.statusCode = 500;
      res.end("Fixture error");
    }
  });
  await new Promise((done) => server.listen(port, "127.0.0.1", done));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    writes,
    scratch,
    async close() {
      await new Promise((done) => server.close(done));
      await rm(scratch, { recursive: true });
    },
  };
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const fixture = await startCampaignPreview(Number(process.env.PORT || 4338));
  console.log(fixture.url);
  const close = async () => {
    await fixture.close();
    process.exit(0);
  };
  process.on("SIGINT", close);
  process.on("SIGTERM", close);
}
