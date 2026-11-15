// Loopback-only inbox UI fixture: synthetic accounts, no credentials or provider IO.
import { createServer } from "node:http";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url),
  root = fileURLToPath(new URL("../../", import.meta.url));
export async function startInboxPreview(port = 0) {
  const scratch = await mkdtemp(join(tmpdir(), "jardines-inbox-"));
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
  const workspace = {
    contacts: [],
    deals: [],
    tasks: [],
    activities: [],
    counts: { contacts: 0, active: 0, won: 0, pending: 0, overdue: 0 },
    limited: false,
  };
  await writeFile(
    join(scratch, "entry.tsx"),
    `import React from 'react';import{createRoot}from'react-dom/client';import{Workspace}from${JSON.stringify(join(root, "apps/web/components/crm/workspace"))};createRoot(document.getElementById('app')!).render(<Workspace initialData={${JSON.stringify(workspace)}} user={{username:'Vista local',role:'admin'}} csrf="fixture-only"/>);`,
  );
  await new Promise((resolve, reject) =>
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
              error || new Error(stats.toString({ all: false, errors: true })),
            )
          : resolve(),
    ),
  );
  const accounts = [
    {
      id: "wa-test",
      platform: "whatsapp",
      name: "Jardines · WhatsApp de prueba",
      active: true,
    },
    {
      id: "ig-test",
      platform: "instagram",
      name: "Jardines · Instagram de prueba",
      active: true,
    },
    {
      id: "fb-test",
      platform: "facebook",
      name: "Jardines · Facebook de prueba",
      active: true,
    },
    {
      id: "yt-test",
      platform: "youtube",
      name: "Jardines · YouTube de prueba",
      active: true,
    },
    {
      id: "gb-test",
      platform: "googlebusiness",
      name: "Jardines · Google de prueba",
      active: true,
    },
  ];
  const now = new Date().toISOString();
  const plans = [];
  const sends = [];
  const reads = [];
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
              [
                "node_modules/tailwindcss/preflight.css",
                "apps/web/app/globals.css",
                "apps/web/app/crm/crm.css",
                "apps/web/app/crm/inbox.css",
              ].map((p) =>
                readFile(join(root, p), "utf8").then((css) =>
                  css.replace(/@import[^;]+;/g, ""),
                ),
              ),
            )
          ).join("\n"),
        );
        return;
      }
      if (req.url.startsWith("/api/crm/")) {
        res.setHeader("Content-Type", "application/json");
        let raw = "";
        for await (const chunk of req) raw += chunk;
        const input = raw ? JSON.parse(raw) : {};
        const operation = input.operation;
        const json = (data) => res.end(JSON.stringify(data));
        const account =
          accounts.find((a) => a.id === input.account_id) ?? accounts[0];
        if (req.url === "/api/crm/inbox/catalog") {
          json(
            JSON.parse(
              await readFile(
                join(root, "apps/api/app/inbox/registry.json"),
                "utf8",
              ),
            ),
          );
          return;
        }
        if (req.url === "/api/crm/inbox/accounts") {
          json({ items: accounts });
          return;
        }
        if (req.url === "/api/crm/inbox/actions") {
          json({ items: [...plans].reverse() });
          return;
        }
        if (req.url === "/api/crm/inbox/read") {
          reads.push(input);
          if (operation === "listInboxConversations") {
            json({
              data: [
                {
                  id: "conversation:one",
                  accountId: account.id,
                  platform: account.platform,
                  participantName: "Contacto de prueba",
                  participantId: "test-participant",
                  lastMessage:
                    "Hola, quisiera conocer el proyecto y coordinar una visita.",
                  unreadCount: 2,
                  updatedTime: now,
                  status: "active",
                },
                {
                  id: "conversation:two",
                  accountId: account.id,
                  platform: account.platform,
                  participantName: "Consulta de prueba",
                  participantId: "second-participant",
                  lastMessage: "¿Me pueden compartir la ubicación?",
                  updatedTime: now,
                  status: "active",
                },
              ],
              pagination: {
                hasMore: !input.query?.cursor,
                nextCursor: input.query?.cursor ? null : "next-fixture-page",
              },
              meta: { accountsQueried: 1, accountsFailed: 0 },
            });
            return;
          }
          if (operation === "getInboxConversationMessages") {
            json({
              messages: [
                {
                  id: "m1",
                  accountId: account.id,
                  conversationId: input.path.conversationId,
                  platform: account.platform,
                  direction: "incoming",
                  senderName: "Contacto de prueba",
                  message:
                    "Hola, quisiera conocer el proyecto y coordinar una visita.",
                  createdAt: now,
                },
                {
                  id: "m2",
                  accountId: account.id,
                  direction: "outgoing",
                  message:
                    "¡Hola! Con gusto te acompañamos. ¿Qué día te gustaría visitarnos?",
                  createdAt: now,
                },
                ...sends
                  .filter(
                    (s) =>
                      s.arguments.path.conversationId ===
                      input.path.conversationId,
                  )
                  .map((s, index) => ({
                    id: "sent-" + index,
                    direction: "outgoing",
                    message: s.arguments.body.message,
                    createdAt: now,
                  })),
              ],
              pagination: { hasMore: false, nextCursor: null },
              sortOrderApplied: "desc",
            });
            return;
          }
          if (operation === "listInboxComments") {
            json({
              data: [
                {
                  id: "post:one",
                  accountId: account.id,
                  platform: account.platform,
                  content:
                    "Conoce Jardines del Encanto. Una nueva perspectiva para tu próximo proyecto.",
                  commentCount: 2,
                  createdTime: now,
                },
              ],
              pagination: { hasMore: false },
            });
            return;
          }
          if (operation === "getInboxPostComments") {
            json({
              comments: [
                {
                  id: "comment:one",
                  message: "¿Dónde puedo ver el plano del proyecto?",
                  createdTime: now,
                  from: { name: "Comentario de prueba" },
                  canReply: true,
                  canLike: true,
                  canHide: true,
                  isHidden: false,
                },
                {
                  id: "comment:two",
                  message: "Me interesa recibir más información.",
                  createdTime: now,
                  from: { name: "Otra consulta" },
                  canReply: true,
                  canLike: true,
                  canHide: true,
                },
              ],
              pagination: { hasMore: false },
            });
            return;
          }
          if (operation === "listInboxMentions") {
            json({
              data: [
                {
                  id: "mention:one",
                  accountId: account.id,
                  platform: account.platform,
                  mediaId: "media:one",
                  authorName: "Mención de prueba",
                  content: "Nos gustaría conocer el proyecto.",
                  publishedAt: now,
                },
              ],
              pagination: { hasMore: false },
            });
            return;
          }
          if (operation === "listInboxReviews") {
            json({
              data: [
                {
                  id: "review:one",
                  accountId: account.id,
                  platform: account.platform,
                  reviewer: { displayName: "Reseña de prueba" },
                  text: "Gracias por la información y la atención.",
                  rating: 5,
                  created: now,
                  hasReply: false,
                },
              ],
              pagination: { hasMore: false },
            });
            return;
          }
          json({ success: true, fixture: true, operation });
          return;
        }
        if (req.url === "/api/crm/inbox/prepare") {
          const spec = JSON.parse(
            await readFile(
              join(root, "apps/api/app/inbox/registry.json"),
              "utf8",
            ),
          ).operations[operation];
          const plan = {
            id: `00000000-0000-4000-8000-${String(plans.length + 1).padStart(12, "0")}`,
            operation,
            account_id: account.id,
            account_label: account.name,
            state: "prepared",
            expires_at: new Date(Date.now() + 600000).toISOString(),
            created_at: now,
            context: {
              participantId: "fixture-participant",
              participantName: "Contacto de prueba",
              accountId: account.id,
              platform: account.platform,
            },
            arguments: {
              path: input.path ?? {},
              query: input.query ?? {},
              body: { ...input.body, accountId: account.id },
            },
          };
          if (!spec || spec.method === "GET") {
            res.statusCode = 422;
            json({ detail: "inbox_write_required" });
            return;
          }
          plans.push(plan);
          res.statusCode = 201;
          json(plan);
          return;
        }
        const confirm = req.url.match(/\/inbox\/actions\/([^/]+)\/confirm$/);
        if (confirm) {
          const plan = plans.find((p) => p.id === confirm[1]);
          if (!plan || plan.state !== "prepared" || input.confirmed !== true) {
            res.statusCode = 409;
            json({ detail: "inbox_action_stale" });
            return;
          }
          plan.state = "sent";
          sends.push(plan);
          json({ id: plan.id, state: "sent", result: { success: true } });
          return;
        }
        const get = req.url.match(/\/inbox\/actions\/([^/]+)$/);
        if (get) {
          json(plans.find((p) => p.id === get[1]) ?? {});
          return;
        }
        json(
          req.url.includes("settings")
            ? { configured: false, connections: [] }
            : {},
        );
        return;
      }
      res.setHeader("Content-Type", "text/html");
      res.end(
        `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Inbox · Vista local sin envíos reales</title><link rel="stylesheet" href="/styles.css"><style>@font-face{font-family:Manrope;src:url('/font.ttf')}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}*{box-sizing:border-box}body{margin:0;background:#f6f7f1;font-family:Manrope,system-ui,sans-serif}button,input,textarea,select{font:inherit}</style><div id="app"></div><script src="/bundle.js"></script></html>`,
      );
    } catch {
      res.statusCode = 500;
      res.end(JSON.stringify({ detail: "fixture_error" }));
    }
  });
  await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    scratch,
    plans,
    sends,
    reads,
    close: async () => {
      await new Promise((resolve) => server.close(resolve));
      await rm(scratch, { recursive: true, force: true });
    },
  };
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const preview = await startInboxPreview(Number(process.env.PORT ?? 4341));
  console.log(JSON.stringify({ url: preview.url, scratch: preview.scratch }));
  for (const sig of ["SIGINT", "SIGTERM"])
    process.on(sig, async () => {
      await preview.close();
      process.exit(0);
    });
}
