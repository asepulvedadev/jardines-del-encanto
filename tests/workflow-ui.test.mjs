import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const root = new URL("../apps/web/components/crm/", import.meta.url);
const source = readFileSync(new URL("workflow-types.ts", root), "utf8");
const model = { exports: {} };
new Function(
  "module",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
)(model, model.exports);
const {
  initialDocument,
  insertNode,
  removeNode,
  graphIssues,
  connectionOptions,
  prepareArguments,
  canActivate,
  workflowError,
} = model.exports;
test("editor inserts genuine linked steps before the end without mutating the draft", () => {
  const original = initialDocument();
  const next = insertNode(original, "wait", "wait-one");
  assert.equal(original.nodes.length, 1);
  assert.equal(next.entry_id, "wait-one");
  assert.equal(next.nodes.find((n) => n.id === "wait-one").next_id, "end");
  assert.deepEqual(graphIssues(next), []);
  const branch = insertNode(next, "condition", "branch");
  assert.deepEqual(graphIssues(branch), []);
  assert.deepEqual(removeNode(branch, "branch"), next);
});
test("connections never offer cycles; missing CRM data is not modeled as false", () => {
  let d = insertNode(initialDocument(), "wait", "a");
  d = insertNode(d, "condition", "b");
  assert(!connectionOptions(d, "b").some((n) => n.id === "a"));
  const cyclic = structuredClone(d);
  cyclic.nodes.find((n) => n.id === "b").on_true = "a";
  assert(graphIssues(cyclic).some((s) => /ciclo/i.test(s)));
  const orphan = structuredClone(d);
  orphan.entry_id = "end";
  assert(graphIssues(orphan).some((s) => /conectad/i.test(s)));
});
test("frozen preparation only uses selected contact IDs and exact run bindings", () => {
  const payload = prepareArguments(
    4,
    ["contact-one"],
    {
      "contact-one": { account_id: "account", conversation_id: "thread" },
      "not-selected": { account_id: "other", conversation_id: "other" },
    },
    true,
  );
  assert.deepEqual(payload, {
    version: 4,
    contact_ids: ["contact-one"],
    bindings: [
      {
        contact_id: "contact-one",
        account_id: "account",
        conversation_id: "thread",
      },
    ],
    consent_confirmed: true,
  });
  assert.throws(() => prepareArguments(4, [], {}, true));
  assert.throws(() =>
    prepareArguments(
      4,
      Array.from({ length: 51 }, (_, i) => `${i}`),
      {},
      true,
    ),
  );
  assert.throws(() => prepareArguments(4, ["one"], {}, false));
});
test("activation is fail closed for dirty, unconsented, expired and worker-unavailable reviews", () => {
  const review = {
    expires_at: "2026-12-01T00:00:00Z",
    run: { status: "prepared" },
  };
  const worker = { enabled: true, available: true };
  const now = Date.parse("2026-11-01");
  assert.equal(canActivate(review, worker, false, true, now), true);
  for (const args of [
    [review, worker, true, true, now],
    [review, worker, false, false, now],
    [review, { enabled: true, available: false }, false, true, now],
    [review, worker, false, true, Date.parse("2026-12-02")],
    [null, worker, false, true, now],
  ])
    assert.equal(canActivate(...args), false);
  assert.match(workflowError("record_changed"), /otra sesión|versión/i);
});
test("UI explicitly separates draft save, review and activation with accessible real-state surfaces", () => {
  const panel = readFileSync(new URL("workflow-panel.tsx", root), "utf8");
  const workspace = readFileSync(new URL("workspace.tsx", root), "utf8");
  for (const copy of [
    "Guardar borrador",
    "Preparar revisión",
    "Aprobar y activar",
    "Constructor",
    "Programación",
    "Clientes e historial",
    "Detener",
    "Pausar",
    "Reanudar",
  ])
    assert(panel.includes(copy), copy);
  assert.match(panel, /<svg[\s\S]*aria-hidden="true"/);
  assert.match(panel, /Lista de pasos/);
  assert.match(panel, /<dialog/);
  assert.match(panel, /No se enviará|no envía|No envía/);
  assert.match(panel, /on_true/);
  assert.match(panel, /on_false/);
  assert.match(
    workspace,
    /\["voice", "microphone"\],[\s\S]{0,40}\["workflows", "connections"\]/,
  );
});

// Execute the client component with deterministic hook state and fake HTTP responses.
// JSX remains a real React element tree; no browser, credentials or provider is used.
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
function clientHarness() {
  const states = [],
    refs = [],
    modules = new Map();
  let stateCursor = 0,
    refCursor = 0;
  const react = {
    useState(initial) {
      const i = stateCursor++;
      if (!(i in states))
        states[i] = typeof initial === "function" ? initial() : initial;
      return [
        states[i],
        (value) => {
          states[i] = typeof value === "function" ? value(states[i]) : value;
        },
      ];
    },
    useRef(initial) {
      const i = refCursor++;
      return (refs[i] ??= { current: initial });
    },
    useEffect() {},
    useMemo(fn) {
      return fn();
    },
    useCallback(fn) {
      return fn;
    },
  };
  function load(filename) {
    const full = resolve(fileURLToPath(root), filename);
    if (modules.has(full)) return modules.get(full).exports;
    const module = { exports: {} };
    modules.set(full, module);
    const code = ts.transpileModule(readFileSync(full, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function("require", "module", "exports", code)(
      (name) => {
        if (name === "react") return react;
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = resolve(dirname(full), name);
          for (const ext of [".ts", ".tsx"]) {
            try {
              readFileSync(base + ext);
            } catch {
              continue;
            }
            return load(base + ext);
          }
        }
        return require(name);
      },
      module,
      module.exports,
    );
    return module.exports;
  }
  const { WorkflowPanel } = load("workflow-panel.tsx");
  const props = {
    csrf: "fixture-csrf",
    contacts: [
      {
        id: "contact-one",
        name: "Cliente sintético",
        phone: "+573000000001",
        source: "web",
        version: 1,
        created_at: "2026-11-01",
      },
    ],
    onOpenConnections() {},
  };
  function render() {
    stateCursor = 0;
    refCursor = 0;
    return WorkflowPanel(props);
  }
  render();
  states[11] = false;
  function all(node, result = []) {
    if (!node || typeof node !== "object") return result;
    if (Array.isArray(node)) {
      node.forEach((child) => all(child, result));
      return result;
    }
    if (typeof node.type === "function")
      return all(node.type(node.props), result);
    if (node.type) result.push(node);
    all(node.props?.children, result);
    return result;
  }
  function textOf(node) {
    if (node === null || node === undefined || typeof node === "boolean")
      return "";
    if (typeof node !== "object") return String(node);
    if (Array.isArray(node)) return node.map(textOf).join("");
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
  }
  const button = (label) =>
    all(render()).find(
      (node) => node.type === "button" && textOf(node) === label,
    );
  const label = (label) =>
    all(render()).find(
      (node) => node.type === "label" && textOf(node).startsWith(label),
    );
  return { states, render, all, textOf, button, label };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
test("save does not prepare or activate, and the server response alone confirms the draft", async () => {
  const harness = clientHarness(),
    calls = [];
  const saved = {
    id: "flow-one",
    name: "Nueva secuencia",
    description: "",
    document: initialDocument(),
    version: 1,
    created_at: "2026-11-01",
    updated_at: "2026-11-01",
  };
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => saved };
  };
  try {
    harness.button("Guardar borrador").props.onClick();
    await flush();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/crm/workflows/definitions");
    assert.equal(calls[0].options.headers["X-CSRF-Token"], "fixture-csrf");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(harness.states[3], "flow-one");
    assert.equal(harness.states[4], 1);
    assert.match(harness.textOf(harness.render()), /Borrador guardado/);
    assert.equal(harness.button("Guardar borrador").props.disabled, true);
  } finally {
    globalThis.fetch = previous;
  }
});
test("preparation is exact audience-only with no outbound endpoint or activation", async () => {
  const harness = clientHarness(),
    calls = [];
  harness.states[3] = "flow-one";
  harness.states[4] = 2;
  harness.states[10] = "history";
  harness.states[16] = ["contact-one"];
  harness.states[19] = true;
  const review = {
    run: {
      id: "run-one",
      workflow_name: "Nueva secuencia",
      workflow_version: 2,
      status: "prepared",
      created_at: "2026-11-01",
      counts: {
        total: 1,
        completed: 0,
        active: 0,
        blocked: 0,
        unknown: 0,
        stopped: 0,
      },
    },
    fingerprint: "opaque-review",
    expires_at: "2099-01-01",
    recipients: [],
    steps: [],
    warnings: [],
  };
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return { ok: true, status: 200, json: async () => review };
  };
  try {
    assert.equal(harness.button("Preparar revisión").props.disabled, false);
    harness.button("Preparar revisión").props.onClick();
    await flush();
    assert.deepEqual(calls, [
      {
        url: "/api/crm/workflows/definitions/flow-one/prepare",
        body: {
          version: 2,
          contact_ids: ["contact-one"],
          bindings: [],
          consent_confirmed: true,
        },
      },
    ]);
    assert.equal(harness.states[20].fingerprint, "opaque-review");
    assert.equal(
      harness.button("Aprobar y activar").props.disabled,
      true,
      "worker unavailability and final consent block activation",
    );
  } finally {
    globalThis.fetch = previous;
  }
});
test("version-conflict save preserves the local draft and never emits a false success", async () => {
  const harness = clientHarness();
  harness.states[3] = "flow-one";
  harness.states[4] = 2;
  harness.states[5] = "Cambio local";
  const previous = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 409,
    json: async () => ({ detail: "record_changed" }),
  });
  try {
    harness.button("Guardar borrador").props.onClick();
    await flush();
    assert.equal(harness.states[5], "Cambio local");
    assert.equal(harness.states[15], true);
    assert.match(
      harness.textOf(harness.render()),
      /borrador local no se sobrescribió/,
    );
    assert.doesNotMatch(harness.textOf(harness.render()), /Borrador guardado/);
  } finally {
    globalThis.fetch = previous;
  }
});
test("external review budget blocks preparation independently of the worker or daily limit", () => {
  const harness = clientHarness();
  let document = insertNode(initialDocument(), "social_message", "social");
  document.nodes.find((n) => n.id === "social").settings = {
    account_id: "account",
    platform: "whatsapp",
    text: "Hola {{nombre}}",
  };
  harness.states[3] = "flow";
  harness.states[7] = document;
  harness.states[8] = JSON.stringify({
    name: "Nueva secuencia",
    description: "",
    document,
  });
  harness.states[10] = "history";
  harness.states[19] = true;
  harness.states[16] = Array.from({ length: 11 }, (_, i) => `contact-${i}`);
  harness.states[17] = Object.fromEntries(
    harness.states[16].map((id) => [
      id,
      { account_id: "account", conversation_id: "thread" },
    ]),
  );
  assert.equal(harness.button("Preparar revisión").props.disabled, true);
  assert.match(
    harness.textOf(harness.render()),
    /supera el límite de 10 acciones externas/,
  );
});
test("template selection atomically preserves name, language and positional parameters", () => {
  const harness = clientHarness();
  const document = insertNode(
    initialDocument(),
    "whatsapp_template",
    "template-node",
  );
  document.nodes.find((n) => n.id === "template-node").settings.account_id =
    "account";
  harness.states[7] = document;
  harness.states[9] = "template-node";
  harness.states[25] = {
    available: true,
    accounts: [],
    conversations: [],
    templates: [
      {
        name: "approved_greeting",
        language: "es_CO",
        status: "APPROVED",
        parameter_count: 2,
        body: "Hola {{1}}, tu solicitud {{2}}.",
      },
    ],
  };
  harness.states[27] = "account";
  const select = harness
    .all(harness.label("Plantilla aprobada"))
    .find((node) => node.type === "select");
  select.props.onChange({ target: { value: "approved_greeting|es_CO" } });
  assert.deepEqual(
    harness.states[7].nodes.find((n) => n.id === "template-node").settings,
    {
      account_id: "account",
      template_name: "approved_greeting",
      language: "es_CO",
      parameters: ["", ""],
    },
  );
});
test("ambiguous activation is held instead of allowing a second submit", async () => {
  const harness = clientHarness(),
    calls = [];
  harness.states[0] = {
    worker: { enabled: true, available: true },
    nodes: [],
    connections: [],
  };
  harness.states[20] = {
    run: {
      id: "run-one",
      workflow_name: "Secuencia",
      workflow_version: 1,
      status: "prepared",
    },
    fingerprint: "exact-fingerprint",
    expires_at: "2099-01-01",
    recipients: [],
    steps: [],
    warnings: [],
  };
  harness.states[21] = true;
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    throw new Error("fixture connection interrupted");
  };
  try {
    const activation = harness.button("Aprobar y activar");
    assert.equal(activation.props.disabled, false);
    activation.props.onClick();
    await flush();
    assert.deepEqual(calls, [
      {
        url: "/api/crm/workflows/runs/run-one/activate",
        body: { fingerprint: "exact-fingerprint", consent_confirmed: true },
      },
    ]);
    assert.equal(harness.button("Aprobar y activar").props.disabled, true);
    assert.match(harness.textOf(harness.render()), /No la repitas/);
    harness.button("Aprobar y activar").props.onClick();
    await flush();
    assert.equal(calls.length, 1);
  } finally {
    globalThis.fetch = previous;
  }
});

test("prepared review expiry is never presented as execution grant expiry", () => {
  const source = readFileSync(
    new URL("../apps/web/components/crm/workflow-panel.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /formatDate\(review\.run\.expires_at\)/);
  assert.match(source, /30 días después de activar/);
});
