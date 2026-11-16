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
  channelBindingKey,
  multichannelPrepareArguments,
} = model.exports;
test("multichannel review binds each selected client to each explicit sender account", () => {
  const bindings = {
    [channelBindingKey("one", "fb")]: {
      account_id: "fb",
      conversation_id: "fb-thread",
    },
    [channelBindingKey("one", "ig")]: {
      account_id: "ig",
      conversation_id: "ig-thread",
    },
    [channelBindingKey("other", "fb")]: {
      account_id: "fb",
      conversation_id: "private-other",
    },
    [channelBindingKey("one", "unused")]: {
      account_id: "unused",
      conversation_id: "old-thread",
    },
  };
  const result = multichannelPrepareArguments(3, ["one"], bindings, true, [
    "fb",
    "ig",
    "fb",
  ]);
  assert.deepEqual(result.channel_bindings, [
    { contact_id: "one", account_id: "fb", conversation_id: "fb-thread" },
    { contact_id: "one", account_id: "ig", conversation_id: "ig-thread" },
  ]);
  assert.deepEqual(result.bindings, []);
  assert.throws(() =>
    multichannelPrepareArguments(3, ["one"], {}, true, ["fb"]),
  );
  assert.notEqual(channelBindingKey("a|b", "c"), channelBindingKey("a", "b|c"));
});
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
  const canvas = readFileSync(new URL("workflow-canvas.tsx", root), "utf8");
  assert.match(canvas, /<svg[\s\S]*aria-hidden="true"/);
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
function clientHarness(component = "WorkflowPanel", overrides = {}) {
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
  const Component = load("workflow-panel.tsx")[component];
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
    ...overrides,
  };
  function render() {
    stateCursor = 0;
    refCursor = 0;
    return Component(props);
  }
  render();
  if (component === "WorkflowPanel") states[11] = false;
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
test("canvas zoom preserves its anchor, fits negative positions and bounds node movement", () => {
  const viewportModule = { exports: {} };
  const viewportSource = readFileSync(
    new URL("workflow-viewport.ts", root),
    "utf8",
  );
  new Function(
    "module",
    "exports",
    ts.transpileModule(viewportSource, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  )(viewportModule, viewportModule.exports);
  const { zoomAt, fitViewport, movePosition } = viewportModule.exports;
  const view = { x: 100, y: 50, zoom: 1 };
  const zoomed = zoomAt(view, 2, { x: 300, y: 200 });
  assert.deepEqual(zoomed, { x: -100, y: -100, zoom: 2 });
  assert.equal(zoomAt(view, 100, { x: 0, y: 0 }).zoom, 2);
  assert.equal(zoomAt(view, 0.001, { x: 0, y: 0 }).zoom, 0.1);
  const nodes = [
    { position: { x: -300, y: -100 } },
    { position: { x: 300, y: 500 } },
  ];
  const fit = fitViewport(nodes, 800, 600);
  for (const node of nodes) {
    const x = fit.x + node.position.x * fit.zoom;
    const y = fit.y + node.position.y * fit.zoom;
    assert(x >= 134 * fit.zoom && x <= 800 - 134 * fit.zoom);
    assert(y >= 44 * fit.zoom && y <= 600 - 44 * fit.zoom);
  }
  assert.deepEqual(movePosition({ x: 100, y: 100 }, 50, -25, 0.5), {
    x: 200,
    y: 50,
  });
  assert.deepEqual(movePosition({ x: 99999, y: -99999 }, 500, -500, 1), {
    x: 100000,
    y: -100000,
  });
});
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

test("canvas controls zoom, pan, drag at the current scale and keep keyboard movement available", () => {
  const moves = [],
    selections = [];
  const document = initialDocument();
  const harness = clientHarness("WorkflowCanvas", {
    document,
    selected: "end",
    onSelect: (id) => selections.push(id),
    onMove: (id, position) => moves.push({ id, position }),
  });
  const find = (predicate) => harness.all(harness.render()).find(predicate);
  const control = (label) => find((n) => n.props["aria-label"] === label);
  const map = () => find((n) => n.props.className === "workflow-map-scroll");
  map().props.ref.current = { clientWidth: 800, clientHeight: 600, focus() {} };
  control("Alejar lienzo").props.onClick();
  assert.equal(harness.states[0].zoom, 0.8);
  control("Acercar lienzo").props.onClick();
  assert.equal(harness.states[0].zoom, 1);
  control("Encajar todos los pasos").props.onClick();
  assert.equal(harness.states[0].x + 330 * harness.states[0].zoom, 400);
  let prevented = false;
  const mapNode = map();
  mapNode.props.onKeyDown({
    key: "ArrowRight",
    target: 1,
    currentTarget: 1,
    preventDefault() {
      prevented = true;
    },
  });
  assert.equal(prevented, true);
  const beforePan = harness.states[0].x;
  const target = { setPointerCapture() {}, focus() {} };
  map().props.onPointerDown({
    button: 0,
    pointerId: 1,
    clientX: 0,
    clientY: 0,
    currentTarget: target,
    target,
    preventDefault() {},
  });
  map().props.onPointerMove({ pointerId: 1, clientX: 100, clientY: 50 });
  assert.equal(harness.states[0].x, beforePan + 100);
  map().props.onPointerUp({ pointerId: 1, clientX: 100, clientY: 50 });
  assert.equal(moves.length, 0, "panning must never edit the workflow");
  const card = () =>
    find(
      (n) =>
        n.type === "button" && n.props.className?.includes("workflow-node "),
    );
  card().props.onPointerDown({
    button: 0,
    pointerId: 2,
    clientX: 100,
    clientY: 100,
    currentTarget: target,
    stopPropagation() {},
  });
  map().props.onPointerMove({ pointerId: 2, clientX: 180, clientY: 140 });
  assert.equal(
    moves.length,
    0,
    "pointer movement is a local preview, not a persisted write",
  );
  map().props.onPointerUp({ pointerId: 2, clientX: 180, clientY: 140 });
  assert.deepEqual(moves, [{ id: "end", position: { x: 410, y: 190 } }]);
  card().props.onClick();
  assert.deepEqual(selections, [], "dragging must not open the inspector");
  card().props.onKeyDown({
    key: "ArrowRight",
    altKey: true,
    shiftKey: false,
    preventDefault() {},
    stopPropagation() {},
  });
  assert.deepEqual(moves[1], { id: "end", position: { x: 340, y: 150 } });
  assert.deepEqual(
    document.nodes[0].position,
    { x: 330, y: 150 },
    "input document remains immutable",
  );
});

test("builder starts with a clear canvas and opens only the panel needed for the selected action", () => {
  const harness = clientHarness();
  harness.states[0] = {
    nodes: [{ kind: "wait", available: true }],
    worker: { enabled: false, available: false },
  };
  const aside = (label) =>
    harness.all(harness.render()).find((n) => n.props["aria-label"] === label);
  assert.equal(aside("Pasos disponibles").props.hidden, true);
  assert.equal(aside("Inspector del paso seleccionado").props.hidden, true);
  harness.button("Agregar paso").props.onClick();
  assert.equal(aside("Pasos disponibles").props.hidden, false);
  harness.button("Esperar").props.onClick();
  assert.equal(aside("Pasos disponibles").props.hidden, true);
  assert.equal(aside("Inspector del paso seleccionado").props.hidden, false);
  assert.equal(harness.states[7].nodes.length, 2);
});

test("cancelled or locked node gestures cannot change the draft", () => {
  for (const disabled of [false, true]) {
    const moves = [];
    const harness = clientHarness("WorkflowCanvas", {
      document: initialDocument(),
      selected: "end",
      disabled,
      onSelect() {},
      onMove: (...args) => moves.push(args),
    });
    const find = (predicate) => harness.all(harness.render()).find(predicate);
    const card = find(
      (n) =>
        n.type === "button" && n.props.className?.includes("workflow-node "),
    );
    const map = () => find((n) => n.props.className === "workflow-map-scroll");
    card.props.onPointerDown({
      button: 0,
      pointerId: 1,
      clientX: 0,
      clientY: 0,
      currentTarget: { setPointerCapture() {} },
      stopPropagation() {},
    });
    map().props.onPointerMove({ pointerId: 1, clientX: 100, clientY: 100 });
    map().props.onPointerCancel();
    map().props.onPointerUp({ pointerId: 1, clientX: 100, clientY: 100 });
    assert.deepEqual(moves, []);
    assert.equal(harness.states[1], null);
  }
});
