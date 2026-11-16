import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { GET, PATCH, POST } from "../apps/web/app/api/crm/[...path]/route.ts";

const root = new URL("../", import.meta.url);
const source = (file) => readFileSync(new URL(file, root), "utf8");
const id = "00000000-0000-4000-8000-000000000001";
const config = (extra = {}) => ({
  version: 0,
  enabled: false,
  account_id: "",
  phone: "",
  developers: [],
  instructions: "",
  knowledge: "",
  status: { ready: false, reason: "agent_not_configured" },
  lessons: [],
  activity: [],
  ...extra,
});
function harness(request) {
  const states = [],
    refs = [],
    effects = [];
  let cursor = 0,
    refCursor = 0,
    effectCursor = 0;
  const deps = [];
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in states))
        states[i] = typeof initial === "function" ? initial() : initial;
      return [
        states[i],
        (v) => {
          states[i] = typeof v === "function" ? v(states[i]) : v;
        },
      ];
    },
    useRef(initial) {
      const i = refCursor++;
      return (refs[i] ??= { current: initial });
    },
    useEffect(fn, current) {
      const i = effectCursor++;
      if (!deps[i] || current.some((v, j) => v !== deps[i][j])) {
        deps[i] = current;
        effects.push(fn);
      }
    },
    useCallback(fn) {
      return fn;
    },
  };
  const jsx = (type, props) => ({ type, props });
  const module = { exports: {} };
  const compiled = ts.transpileModule(
    source("apps/web/components/crm/whatsapp-agent-panel.tsx"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  new Function("require", "module", "exports", compiled)(
    (name) =>
      name === "react"
        ? react
        : name === "react/jsx-runtime"
          ? { jsx, jsxs: jsx }
          : name.endsWith(".css")
            ? {}
            : { settingsError: (error) => error.message },
    module,
    module.exports,
  );
  let tree;
  const render = () => {
    cursor = 0;
    refCursor = 0;
    effectCursor = 0;
    tree = module.exports.WhatsAppAgentPanel({ request, active: true });
    return tree;
  };
  const descend = (node) =>
    !node || typeof node !== "object"
      ? []
      : Array.isArray(node)
        ? node.flatMap((n) => descend(n))
        : [node, ...descend(node.props?.children)];
  const nodes = () => descend(tree);
  const text = (node) =>
    node == null || typeof node === "boolean"
      ? ""
      : Array.isArray(node)
        ? node.map(text).join(" ")
        : typeof node === "object"
          ? text(node.props?.children)
          : String(node);
  return {
    render,
    nodes,
    text,
    field: (id) => nodes().find((n) => n.props?.id === id),
    button: (label) =>
      nodes().find((n) => n.type === "button" && text(n) === label),
    async flush() {
      for (const effect of effects.splice(0)) effect();
      await new Promise((resolve) => setImmediate(resolve));
      render();
    },
  };
}

test("Sara WhatsApp tab reuses associated keyboard navigation and shared request boundary", () => {
  const modal = source("apps/web/components/crm/settings-modal.tsx");
  assert.match(modal, /\["whatsapp-agent", "Sara WhatsApp"\]/);
  assert.match(modal, /settings-panel-whatsapp-agent/);
  assert.match(modal, /<WhatsAppAgentPanel/);
  assert.match(modal, /ArrowDown/);
  assert.match(modal, /16384/);
});

test("new panel loads safely, requires explicit inbound consent and separates knowledge", async () => {
  const calls = [];
  const h = harness(async (...args) => {
    calls.push(args);
    return config({ status: { ready: true, reason: null } });
  });
  h.render();
  assert.match(h.text(h.render()), /Consultando/);
  await h.flush();
  assert.equal(calls[0][0], "social/whatsapp-agent");
  assert.equal(h.button("Activar").props.disabled, true);
  assert.ok(h.field("whatsapp-agent-instructions"));
  assert.ok(h.field("whatsapp-agent-knowledge"));
  assert.match(h.text(h.render()), /\/aprender <texto>/);
  h.field("whatsapp-agent-consent").props.onChange({
    target: { checked: true },
  });
  h.render();
  await h.button("Activar").props.onClick();
  assert.equal(calls.at(-1)[1], "PATCH");
  assert.equal(calls.at(-1)[2].consent_confirmed, true);
  assert.equal(calls.at(-1)[2].enabled, true);
  h.render();
  h.field("whatsapp-agent-consent").props.onChange({
    target: { checked: true },
  });
  h.render();
  await h.button("Actualizar estado").props.onClick();
  h.render();
  assert.equal(h.field("whatsapp-agent-consent").props.checked, false);
});

test("conflicts and refresh retain unsaved edits and block blind overwrite", async () => {
  let writes = 0;
  const h = harness(async (_, method) => {
    if (method === "PATCH") {
      writes++;
      throw new Error("La configuración cambió en otra sesión.");
    }
    return config({ version: 5, knowledge: "Servidor" });
  });
  h.render();
  await h.flush();
  h.field("whatsapp-agent-knowledge").props.onChange({
    target: { value: "Borrador local" },
  });
  h.render();
  await h.button("Guardar cambios").props.onClick();
  h.render();
  assert.equal(writes, 1);
  assert.equal(
    h.field("whatsapp-agent-knowledge").props.value,
    "Borrador local",
  );
  await h.button("Actualizar estado").props.onClick();
  h.render();
  assert.equal(
    h.field("whatsapp-agent-knowledge").props.value,
    "Borrador local",
  );
  assert.match(h.text(h.render()), /Conservamos tus cambios/);
});

test("pause remains available while unready and lesson review uses current version", async () => {
  const calls = [];
  const h = harness(async (...args) => {
    calls.push(args);
    return config({
      version: 9,
      enabled: true,
      status: { ready: false, reason: "hermes_unavailable" },
      lessons: [
        {
          id,
          content: "Nuevo conocimiento",
          author: "Desarrollador",
          state: "pending",
          created_at: "2026-11-15T12:00:00Z",
        },
      ],
    });
  });
  h.render();
  await h.flush();
  assert.equal(h.button("Pausar").props.disabled, false);
  await h.button("Pausar").props.onClick();
  h.render();
  assert.equal(calls.at(-1)[2].enabled, false);
  await h.button("Aprobar").props.onClick();
  h.render();
  assert.equal(calls.at(-1)[0], `social/whatsapp-agent/lessons/${id}/approve`);
  assert.deepEqual(calls.at(-1)[2], { version: 9 });
});

test("developer edits reset consent, cap trusted numbers and never become client context", async () => {
  const h = harness(async () =>
    config({ status: { ready: true, reason: null } }),
  );
  h.render();
  await h.flush();
  h.field("whatsapp-agent-consent").props.onChange({
    target: { checked: true },
  });
  h.render();
  h.button("Agregar desarrollador").props.onClick();
  h.render();
  assert.equal(h.field("whatsapp-agent-consent").props.checked, false);
  h.button("Agregar desarrollador").props.onClick();
  h.render();
  assert.equal(h.button("Agregar desarrollador").props.disabled, true);
  assert.equal(h.button("Activar").props.disabled, true);
  assert.match(h.text(h.render()), /clientes tienen un contexto separado/);
  assert.doesNotMatch(
    source("apps/web/components/crm/whatsapp-agent-panel.tsx"),
    /fetch\(|dangerouslySetInnerHTML|573[0-9]{9}/,
  );
});

test("pause does not publish unsaved training, while approving preserves the local draft", async () => {
  const calls = [];
  const saved = config({
    version: 4,
    enabled: true,
    knowledge: "Servidor",
    lessons: [
      {
        id,
        content: "Propuesta",
        author: "Desarrollador",
        state: "pending",
        created_at: "2026-11-15T12:00:00Z",
      },
    ],
  });
  const h = harness(async (...args) => {
    calls.push(args);
    return { ...saved, version: args[1] ? 5 : 4 };
  });
  h.render();
  await h.flush();
  h.field("whatsapp-agent-knowledge").props.onChange({
    target: { value: "Solo local" },
  });
  h.render();
  await h.button("Pausar").props.onClick();
  h.render();
  assert.equal(calls.at(-1)[2].knowledge, "Servidor");
  assert.equal(h.field("whatsapp-agent-knowledge").props.value, "Solo local");
  assert.equal(h.button("Guardar cambios").props.disabled, true);
  h.button("Revisé la versión actual").props.onClick();
  h.render();
  await h.button("Aprobar").props.onClick();
  h.render();
  assert.deepEqual(calls.at(-1)[2], { version: 5 });
  assert.equal(h.field("whatsapp-agent-knowledge").props.value, "Solo local");
  assert.equal(h.button("Guardar cambios").props.disabled, true);
});

test("WhatsApp gateway is exact, bounded, CSRF/session preserving and rejects query expansion", async () => {
  const oldFetch = globalThis.fetch,
    oldBase = process.env.API_BASE_URL,
    oldOrigin = process.env.CRM_ORIGIN;
  const calls = [];
  process.env.API_BASE_URL = "http://private.invalid";
  process.env.CRM_ORIGIN = "https://crm.example.invalid";
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return Response.json(config());
  };
  const req = (method, payload = {}, query = "") => {
    const r = new Request(
      `https://crm.example.invalid/api/crm/social/whatsapp-agent${query}`,
      {
        method,
        headers: {
          origin: "https://crm.example.invalid",
          "content-type": "application/json",
          "x-csrf-token": "fixture",
        },
        body: method === "GET" ? undefined : JSON.stringify(payload),
      },
    );
    Object.defineProperty(r, "cookies", {
      value: {
        get: (name) =>
          name === "__Host-jardines_session"
            ? { name, value: "session" }
            : undefined,
      },
    });
    return r;
  };
  const ctx = (path) => ({
    params: Promise.resolve({ path: path.split("/") }),
  });
  try {
    for (const [method, path] of [
      ["GET", "social/whatsapp-agent"],
      ["PATCH", "social/whatsapp-agent"],
      ["POST", `social/whatsapp-agent/lessons/${id}/approve`],
      ["POST", `social/whatsapp-agent/lessons/${id}/reject`],
    ])
      assert.equal(
        (await { GET, PATCH, POST }[method](req(method), ctx(path))).status,
        200,
      );
    assert.equal(calls.at(-1).options.headers.get("x-csrf-token"), "fixture");
    assert.equal(
      calls.at(-1).options.headers.get("cookie"),
      "__Host-jardines_session=session",
    );
    for (const path of [
      "social/whatsapp-agent/send",
      `social/whatsapp-agent/lessons/${"-".repeat(36)}/approve`,
      `social/whatsapp-agent/lessons/${id}/execute`,
      "social/whatsapp-agent",
    ])
      assert.equal((await POST(req("POST"), ctx(path))).status, 404);
    assert.equal(
      (
        await PATCH(
          req("PATCH", { knowledge: "á".repeat(9000) }),
          ctx("social/whatsapp-agent"),
        )
      ).status,
      413,
    );
    assert.equal(
      (
        await GET(
          req("GET", {}, "?expand=secrets"),
          ctx("social/whatsapp-agent"),
        )
      ).status,
      422,
    );
  } finally {
    globalThis.fetch = oldFetch;
    for (const [key, value] of [
      ["API_BASE_URL", oldBase],
      ["CRM_ORIGIN", oldOrigin],
    ])
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
  }
});

test("WhatsApp shared preference edits carry the published profile version", async () => {
  const calls = [];
  const h = harness(async (...args) => {
    calls.push(args);
    return config({ version: 3, shared_profile_version: 11 });
  });
  h.render();
  await h.flush();
  h.field("whatsapp-agent-knowledge").props.onChange({
    target: { value: "Dato aprobado" },
  });
  h.render();
  await h.button("Guardar cambios").props.onClick();
  assert.equal(calls.at(-1)[2].shared_profile_version, 11);
});
