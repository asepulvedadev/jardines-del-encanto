// Synthetic, loopback-only browser fixture. Never connects to CRM or providers.
import { createServer } from "node:http";
import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../../", import.meta.url));
export async function startWorkflowPreview(port = 0, multichannel = false) {
  const scratch = await mkdtemp(join(tmpdir(), "jardines-workflow-"));
  const { webpack } = require("next/dist/compiled/webpack/webpack");
  const loader = join(scratch, "loader.cjs");
  await writeFile(
    loader,
    `const ts = require(${JSON.stringify(require.resolve("typescript"))}); module.exports = function(source) { return ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText; };`,
  );
  await writeFile(join(scratch, "empty.cjs"), "module.exports = () => ''; ");
  await writeFile(
    join(scratch, "entry.tsx"),
    `import React from 'react'; import { createRoot } from 'react-dom/client'; import { WorkflowPanel } from ${JSON.stringify(join(root, "apps/web/components/crm/workflow-panel"))}; createRoot(document.getElementById('app')!).render(<WorkflowPanel csrf="fixture-only" contacts={${JSON.stringify(multichannel ? [{ id: "00000000-0000-4000-8000-000000000001", name: "Cliente de prueba", phone: "+573000000000", source: "web" }] : [])}} onOpenConnections={() => {}} />);`,
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
          },
          module: {
            rules: [
              { test: /\.tsx?$/, use: loader },
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
  const node = (id, kind, label, y, next_id, settings = {}) => ({
    id,
    kind,
    label,
    position: { x: 330, y },
    settings,
    ...(next_id ? { next_id } : {}),
  });
  const fixture = {
    id: "fixture-sequence",
    name: "Seguimiento de interesados",
    description: "Borrador sintético para verificar el constructor.",
    version: 1,
    document: {
      entry_id: "wait",
      nodes: [
        node("wait", "wait", "Esperar un día", 90, "condition", { hours: 24 }),
        {
          ...node("condition", "condition", "¿Ya fue contactado?", 240, null, {
            field: "stage",
            value: "contactado",
          }),
          on_true: "note",
          on_false: "end",
        },
        node("note", "crm_note", "Registrar gestión", 390, "end", {
          body: "Revisar el interés antes de contactar.",
        }),
        node("end", "end", "Fin de la secuencia", 540, null),
      ],
      schedule: {
        timezone: "America/Bogota",
        days: [1, 2, 3, 4, 5],
        start_time: "09:00",
        end_time: "17:00",
        daily_limit: 20,
      },
      stop_on_reply: true,
    },
  };
  const channels = ["facebook", "instagram", "whatsapp"];
  const accounts = channels.map((platform) => ({
    id: `fixture-${platform}`,
    name: `Jardines · ${platform}`,
    platform,
    available: true,
  }));
  if (multichannel) {
    fixture.name = "Seguimiento multicanal · prueba local";
    fixture.document.entry_id = "facebook";
    fixture.document.nodes = channels.map((platform, index) =>
      node(
        platform,
        "social_message",
        `Mensaje · ${platform}`,
        90 + index * 150,
        channels[index + 1] ?? "end",
        {
          account_id: `fixture-${platform}`,
          platform,
          text: "Hola {{nombre}}, ¿quieres conocer el proyecto?",
          allow_provider_takeover: false,
        },
      ),
    );
    fixture.document.nodes.push(
      node("end", "end", "Fin de la secuencia", 540, null),
    );
  }
  const writes = [];
  const server = createServer(async (req, res) => {
    try {
      if (req.url === "/bundle.js") {
        res.setHeader("Content-Type", "text/javascript");
        res.end(await readFile(join(scratch, "bundle.js")));
        return;
      }
      if (req.url === "/styles.css") {
        res.setHeader("Content-Type", "text/css");
        const styles = await Promise.all(
          [
            "apps/web/app/crm/crm.css",
            "apps/web/components/crm/workflows.css",
          ].map((p) => readFile(join(root, p), "utf8")),
        );
        res.end(styles.join("\n"));
        return;
      }
      if (req.url === "/font.ttf") {
        res.setHeader("Content-Type", "font/ttf");
        res.end(
          await readFile(join(root, "apps/web/app/fonts/Manrope-Variable.ttf")),
        );
        return;
      }
      if (req.url.startsWith("/api/")) {
        res.setHeader("Content-Type", "application/json");
        if (
          multichannel &&
          req.url.endsWith("/options") &&
          req.method === "POST"
        ) {
          let body = "";
          for await (const chunk of req) body += chunk;
          const input = JSON.parse(body);
          const account = accounts.find((item) => item.id === input.account_id);
          res.end(
            JSON.stringify(
              input.provider === "retell"
                ? {
                    available: true,
                    agents: [],
                    numbers: [],
                    destination_policy: {
                      colombia_available: false,
                      reason: "retell_route_confirmation_required",
                    },
                  }
                : {
                    available: true,
                    accounts,
                    templates: [],
                    conversations: account
                      ? [
                          {
                            id: `thread-${account.platform}`,
                            account_id: account.id,
                            platform: account.platform,
                            participant_id: `person-${account.platform}`,
                            label: "Cliente de prueba",
                            can_reply: false,
                            reason: "zernio_window_verification_required",
                          },
                        ]
                      : [],
                  },
            ),
          );
          return;
        }
        if (req.method !== "GET") {
          let body = "";
          for await (const chunk of req) body += chunk;
          writes.push({ path: req.url, body: JSON.parse(body) });
          res.statusCode = 403;
          res.end(JSON.stringify({ detail: "fixture_read_only" }));
          return;
        }
        const kind = req.url.split("/").at(-1);
        res.end(
          JSON.stringify(
            kind === "catalog"
              ? {
                  worker: { enabled: false, available: false },
                  connections: [],
                  nodes: [
                    "whatsapp_template",
                    "social_message",
                    "retell_call",
                    "wait",
                    "condition",
                    "crm_note",
                    "crm_task",
                    "end",
                  ].map((kind) => ({
                    kind,
                    available:
                      multichannel ||
                      ![
                        "whatsapp_template",
                        "social_message",
                        "retell_call",
                      ].includes(kind),
                    reason:
                      !multichannel &&
                      [
                        "whatsapp_template",
                        "social_message",
                        "retell_call",
                      ].includes(kind)
                        ? "Proveedor no conectado en esta prueba local."
                        : undefined,
                  })),
                }
              : kind === "definitions"
                ? { workflows: [fixture] }
                : { runs: [] },
          ),
        );
        return;
      }
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(
        `<!doctype html><html lang="es"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Secuencias · Vista local</title><link rel="stylesheet" href="/styles.css"><style>@font-face{font-family:Manrope;src:url('/font.ttf')}*{box-sizing:border-box}body{margin:0;background:#f6f7f1;font-family:Manrope,system-ui,sans-serif}button,input,select,textarea{font:inherit}h1{font-size:24px;margin:0 0 4px}header{padding:18px 28px;border-bottom:1px solid #d9e1d5;background:white;color:#062619;font-weight:700}header span{float:right;font-size:12px;color:#526056}main{max-width:1440px;padding:24px 28px;margin:auto}.subtitle{color:#526056;font-size:14px;margin:0 0 24px}@media(max-width:600px){main{padding:16px}header{padding:16px}header span{display:block;float:none}}</style><header>Jardines del Encanto<span>Vista local · Datos de prueba · Sin envíos</span></header><main class="crm-shell" style="display:block;min-height:0"><h1>Secuencias</h1><p class="subtitle">Construye el próximo paso.</p><div id="app"></div></main><script src="/bundle.js"></script></html>`,
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
  const fixture = await startWorkflowPreview(
    Number(process.env.PORT || 4336),
    process.env.MULTICHANNEL === "1",
  );
  console.log(fixture.url);
  const close = async () => {
    await fixture.close();
    process.exit(0);
  };
  process.on("SIGINT", close);
  process.on("SIGTERM", close);
}
