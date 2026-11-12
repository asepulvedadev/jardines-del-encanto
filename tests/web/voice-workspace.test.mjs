import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";
const require = createRequire(import.meta.url),
  tick = () => new Promise(setImmediate);
function harness(file, component, props = {}, transport) {
  let cursor = 0,
    tree;
  const slots = [],
    effects = [],
    calls = [];
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots))
        slots[i] = typeof initial === "function" ? initial() : initial;
      return [
        slots[i],
        (v) => (slots[i] = typeof v === "function" ? v(slots[i]) : v),
      ];
    },
    useRef(initial) {
      const i = cursor++;
      return (slots[i] ??= { current: initial });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!slots[i] || deps.some((v, j) => !Object.is(v, slots[i].deps[j])))
        slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return this.useMemo(() => fn, deps);
    },
    useEffect(fn, deps) {
      const i = cursor++;
      if (!slots[i] || deps.some((v, j) => !Object.is(v, slots[i].deps[j]))) {
        const old = slots[i];
        slots[i] = { deps };
        effects.push(() => {
          old?.cleanup?.();
          slots[i].cleanup = fn();
        });
      }
    },
  };
  react.useCallback = (fn, deps) => react.useMemo(() => fn, deps);
  const request = async (...args) => {
    calls.push(args);
    return transport?.(...args);
  };
  const modules = {};
  const router = { replace: () => {} };
  function load(name) {
    if (modules[name]) return modules[name];
    const m = { exports: {} };
    modules[name] = m.exports;
    const source = readFileSync(
      new URL(`../../apps/web/components/crm/${name}`, import.meta.url),
      "utf8",
    );
    const fakeRequire = (path) => {
      if (path === "react") return react;
      if (path === "react/jsx-runtime")
        return {
          jsx: (type, props) => ({ type, props }),
          jsxs: (type, props) => ({ type, props }),
          Fragment: "fragment",
        };
      if (path === "next/navigation") return { useRouter: () => router };
      if (path === "./voice-request") return { voiceRequest: () => request };
      if (path === "./settings-types")
        return { settingsError: (e) => e.message };
      if (["./voice-workspace-data", "./retell-schema"].includes(path))
        return load(
          `${path.slice(2)}.${path === "./retell-schema" ? "tsx" : "ts"}`,
        );
      if (path === "./retell-panel") return { RetellPanel: "RetellPanel" };
      if (path === "./voice-agent-editor")
        return { VoiceAgentEditor: "VoiceAgentEditor" };
      if (path === "./hermes-panel") return { ActionOutput: "ActionOutput" };
      if (path === "./elevenlabs-result")
        return { ElevenLabsVoiceResult: "ElevenLabsVoiceResult" };
      if (path === "./retell-result")
        return { RetellVoiceResult: "RetellVoiceResult" };
      return require(path);
    };
    new Function(
      "require",
      "module",
      "exports",
      "document",
      ts.transpileModule(source, {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          jsx: ts.JsxEmit.ReactJSX,
          target: ts.ScriptTarget.ES2022,
        },
      }).outputText,
    )(fakeRequire, m, m.exports, { activeElement: { focus() {} } });
    modules[name] = m.exports;
    return m.exports;
  }
  const exports = load(file);
  function nodes(node) {
    if (!arguments.length) node = tree;
    return !node || typeof node !== "object"
      ? []
      : [
          node,
          ...[node.props?.children].flat(Infinity).flatMap((x) => nodes(x)),
        ];
  }
  function render() {
    cursor = 0;
    tree = exports[component]({ ...props, request });
    for (const n of nodes())
      if (n.type === "dialog" && n.props.ref)
        n.props.ref.current ??= {
          open: false,
          showModal() {
            this.open = true;
          },
          close() {
            this.open = false;
          },
        };
    while (effects.length) effects.shift()();
    return tree;
  }
  function click(label) {
    render();
    const button = nodes().find(
      (n) => n.type === "button" && flatten(n.props.children) === label,
    );
    assert.ok(button, label);
    button.props.onClick();
  }
  function flatten(x) {
    return Array.isArray(x)
      ? x.map(flatten).join("")
      : typeof x === "object" && x
        ? flatten(x.props?.children)
        : (x ?? "");
  }
  render();
  return { render, nodes, click, calls, exports };
}
const state = {
  available: true,
  configured: true,
  verified: true,
  enabled: true,
  revision: 1,
};
const catalog = {
  revision: 1,
  operations: [
    "listAgents",
    "createAgent",
    "updateAgent",
    "createRetellLLM",
    "updateRetellLLM",
    "getAgent",
  ].map((endpoint) => ({ endpoint, available: true, group: "agents" })),
};
test("opening Voz loads metadata and saved snapshots but never invokes provider operations", async () => {
  const h = harness(
    "voice-workspace.tsx",
    "VoiceWorkspace",
    {
      csrf: "x",
      active: true,
      onChanged: async () => {},
      onOpenConnection: () => {},
    },
    async (path) =>
      path === "retell/settings"
        ? state
        : path === "retell/results"
          ? { snapshots: [], partial: true }
          : catalog,
  );
  await tick();
  h.render();
  assert.deepEqual(h.calls.map((c) => c[0]).sort(), [
    "retell/catalog",
    "retell/results",
    "retell/settings",
  ]);
  h.click("Cargar agentes");
  await tick();
  h.render();
  const sent = h.calls.find((c) => c[0] === "hermes/actions");
  assert.deepEqual(sent[2], {
    action: "retell.execute",
    arguments: { endpoint: "listAgents", arguments: {} },
  });
  assert.equal(
    h.nodes().find((n) => n.type === "ActionOutput").props.value,
    catalog,
  );
});
test("agent form uses current schemas, actual IDs and proposal handoff only", async () => {
  const h = harness(
    "voice-workspace.tsx",
    "VoiceWorkspace",
    {
      csrf: "x",
      active: true,
      onChanged: async () => {},
      onOpenConnection: () => {},
    },
    async (path) =>
      path === "retell/settings"
        ? state
        : path === "retell/results"
          ? {
              snapshots: [
                {
                  endpoint: "listAgents",
                  provider_revision: 1,
                  data: [
                    {
                      agent_id: "a",
                      agent_name: "Existing",
                      voice_id: "voice-existing",
                    },
                  ],
                },
              ],
              partial: true,
            }
          : path === "retell/schema"
            ? { input_schema: { type: "object" } }
            : catalog,
  );
  await tick();
  h.render();
  h.click("Editar agente");
  await tick();
  h.render();
  const editor = h.nodes().find((n) => n.type === "VoiceAgentEditor");
  assert.equal(editor.props.record.agent_id, "a");
  assert.equal(Object.keys(editor.props.schemas).length, 4);
  assert.ok(!h.calls.some((c) => c[0] === "hermes/actions"));
  await editor.props.onSubmit("updateAgent", {
    agent_id: "a",
    requestBody: { agent_name: "New" },
  });
  h.render();
  assert.equal(h.calls.filter((c) => c[0] === "hermes/actions").length, 1);
});
test("approved result callback fires once and a failed refresh never replays vendor work", async () => {
  let updates = 0;
  const proposal = {
    id: "p",
    action: "retell.execute",
    arguments: { endpoint: "listAgents" },
    requirements: { consent: false },
    version: 1,
    status: "pending",
  };
  const result = {
    provider: "retell",
    status: "completed",
    endpoint: "listAgents",
    data: [],
  };
  const h = harness(
    "hermes-panel.tsx",
    "ActionProposals",
    {
      proposals: [proposal],
      onResult: async (v) => {
        assert.equal(v, result);
        updates++;
      },
      onChanged: async () => {
        throw new Error("refresh failed");
      },
    },
    async () => ({ proposal: { ...proposal, status: "approved" }, result }),
  );
  h.click("Aprobar acción exacta");
  h.click("Aprobar acción exacta");
  await tick();
  h.render();
  assert.equal(h.calls.length, 1);
  assert.equal(updates, 1);
  assert.ok(h.nodes().some((n) => n.props?.role === "alert"));
  assert.ok(
    !h
      .nodes()
      .some(
        (n) =>
          n.type === "button" && n.props.children === "Aprobar acción exacta",
      ),
  );
});
test("operation-only panel hides keys and loads only catalogue metadata", async () => {
  const h = harness(
    "retell-panel.tsx",
    "RetellPanel",
    { active: true, operationsOnly: true, onChanged: async () => {} },
    async (path) =>
      path === "retell/settings" ? { ...state, defaults: {} } : catalog,
  );
  await tick();
  h.render();
  assert.ok(!h.nodes().some((n) => n.props?.id === "retell-key"));
  assert.ok(h.nodes().some((n) => n.props?.id === "retell-operation"));
  assert.deepEqual(
    h.calls.map((c) => c[0]),
    ["retell/settings", "retell/catalog"],
  );
});
test("contextual delete remains agent B after switching from JSON to guided fields", async () => {
  const schema = {
    type: "object",
    required: ["agent_id"],
    properties: { agent_id: { type: "string" } },
  };
  const h = harness(
    "retell-panel.tsx",
    "RetellPanel",
    {
      active: true,
      operationsOnly: true,
      initialOperation: {
        endpoint: "deleteAgent",
        arguments: { agent_id: "agent-B" },
      },
      onChanged: async () => {},
    },
    async (path) =>
      path === "retell/settings"
        ? { ...state, defaults: { agent_id: "agent-A" } }
        : path === "retell/schema"
          ? { input_schema: schema }
          : path === "hermes/actions"
            ? { proposals: [] }
            : {
                revision: 1,
                operations: [
                  {
                    endpoint: "deleteAgent",
                    available: true,
                    risk: "destructive",
                    group: "agents",
                  },
                ],
              },
  );
  await tick();
  h.render();
  await tick();
  h.render();
  h.click("Campos");
  h.render();
  const field = h.nodes().find((n) => n.props?.id === "retell-field-agent_id");
  assert.equal(field.props.value, "agent-B");
  const form = h.nodes().find((n) => n.type === "form");
  form.props.onSubmit({ preventDefault() {} });
  await tick();
  h.render();
  assert.equal(
    h.calls.find((c) => c[0] === "hermes/actions")[2].arguments.arguments
      .agent_id,
    "agent-B",
  );
});
test("a catalogue failure does not falsely disconnect a verified provider", async () => {
  const h = harness(
    "voice-workspace.tsx",
    "VoiceWorkspace",
    {
      csrf: "x",
      active: true,
      onChanged: async () => {},
      onOpenConnection: () => {},
    },
    async (path) => {
      if (path === "retell/settings") return state;
      if (path === "retell/results") return { snapshots: [], partial: true };
      throw new Error("No se pudo consultar el catálogo.");
    },
  );
  await tick();
  h.render();
  assert.ok(
    h
      .nodes()
      .some(
        (n) => n.props?.role === "status" && n.props.children === "Conectado",
      ),
  );
  assert.ok(h.nodes().some((n) => n.props?.role === "alert"));
});
test("Voz is a dedicated sidebar view and opens connection settings through the existing modal", () => {
  const workspace = readFileSync(
    new URL("../../apps/web/components/crm/workspace.tsx", import.meta.url),
    "utf8",
  );
  const types = readFileSync(
    new URL("../../apps/web/components/crm/types.ts", import.meta.url),
    "utf8",
  );
  assert.match(types, /voice: "Voz"/);
  assert.match(workspace, /\["voice", "microphone"\]/);
  assert.match(workspace, /<VoiceWorkspace/);
  assert.match(workspace, /setSettingsTab\("connections"\)/);
});
