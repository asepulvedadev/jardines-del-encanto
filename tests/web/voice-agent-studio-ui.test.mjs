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
    useId() {
      cursor++;
      return "studio";
    },
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
      if (
        [
          "./voice-workspace-data",
          "./retell-schema",
          "./voice-summary",
        ].includes(path)
      )
        return load(
          `${path.slice(2)}.${path === "./voice-workspace-data" ? "ts" : "tsx"}`,
        );
      if (
        [
          "./voice-agent-studio-model",
          "./voice-agent-model",
          "./voice-schema-model",
        ].includes(path)
      )
        return load(`${path.slice(2)}.ts`);
      if (path === "./voice-schema-editor")
        return { VoiceSchemaEditor: "VoiceSchemaEditor" };
      if (path === "./icon") return { Icon: "Icon" };
      if (path === "./retell-panel") return { RetellPanel: "RetellPanel" };
      if (path === "./voice-agent-studio")
        return { VoiceAgentStudio: "VoiceAgentStudio" };
      if (path === "./voice-agent-editor")
        return { VoiceAgentEditor: "VoiceAgentEditor" };
      if (path === "./hermes-panel")
        return {
          ActionOutput: "ActionOutput",
          ActionResultDetails: "ActionResultDetails",
        };
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
  return {
    render,
    nodes,
    click,
    calls,
    exports,
    unmount: () => {
      for (const slot of slots) slot?.cleanup?.();
    },
  };
}

const schemas = JSON.parse(
  readFileSync(
    new URL("../../ops/retell/schemas.json", import.meta.url),
    "utf8",
  ),
);
function snapshot(data, endpoint) {
  const m = { exports: {} };
  new Function(
    "require",
    "module",
    "exports",
    ts.transpileModule(
      readFileSync(
        new URL(
          "../../apps/web/components/crm/voice-schema-model.ts",
          import.meta.url,
        ),
        "utf8",
      ),
      {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          target: ts.ScriptTarget.ES2022,
        },
      },
    ).outputText,
  )(() => {}, m, m.exports);
  return {
    data,
    completeFields: Object.keys(
      m.exports.voiceSchemaProperties(
        m.exports.voiceSchemaProperties(schemas[endpoint]).requestBody,
      ),
    ),
    blockedFields: {},
  };
}
const agent = snapshot(
  {
    agent_id: "agent_local",
    agent_name: "Sara",
    voice_id: "voice_local",
    language: "es-419",
    version: 0,
    response_engine: { type: "retell-llm", llm_id: "llm_local", version: 0 },
  },
  "updateAgent",
);
const instructions = snapshot(
  {
    llm_id: "llm_local",
    version: 0,
    general_prompt: "Entire exact prompt",
    begin_message: "Hello",
    model: "gpt-4.1",
  },
  "updateRetellLLM",
);
const props = {
  agent,
  instructions,
  schemas,
  voices: [{ voice_id: "voice_local", voice_name: "Local voice" }],
  models: [],
  revision: 1,
  available: [
    "updateAgent",
    "updateRetellLLM",
    "createWebCall",
    "agentPlaygroundCompletion",
    "listTestCaseDefinitions",
    "publishAgentVersion",
  ],
  busy: false,
  onPendingChange: () => {},
  onClose: () => {},
  onReload: () => {},
  onChanged: async () => {},
  onResult: async () => {},
};
function studio(overrides = {}, transport) {
  return harness(
    "voice-agent-studio.tsx",
    "VoiceAgentStudio",
    { ...props, ...overrides },
    transport,
  );
}
function field(h, name) {
  return h.nodes().find((n) => n.props?.name === name);
}
function change(h, name, value) {
  const n = field(h, name);
  assert(n, name);
  n.props.onChange({ target: { value } });
  h.render();
}
test("studio opens in three-column agent view with complete prompt and all setting accordions; no provider writes", () => {
  const h = studio();
  assert.equal(
    field(h, "studio_general_prompt").props.value,
    "Entire exact prompt",
  );
  assert.equal(field(h, "studio_general_prompt").props.readOnly, false);
  assert.equal(h.calls.length, 0);
  assert.equal(
    h
      .nodes()
      .filter(
        (n) =>
          n.type === "details" &&
          n.props.className === "voice-studio-accordion",
      ).length,
    11,
  );
  assert(
    h.nodes().some((n) => n.props?.["aria-label"] === "Pruebas del agente"),
  );
});
test("two-resource review validates first, retains draft on partial preparation and never approves automatically", async () => {
  let calls = 0;
  const h = studio({}, async (path, method, body) => {
    assert.equal(path, "hermes/actions");
    calls++;
    if (calls === 2) throw Error("unavailable");
    return {
      proposals: [
        {
          id: "first",
          action: "retell.execute",
          arguments: body.arguments,
          status: "pending",
          version: 1,
        },
      ],
    };
  });
  change(h, "studio_general_prompt", "Changed exact prompt");
  const name = h
    .nodes()
    .find((n) => n.props?.["aria-label"] === "Nombre del agente");
  name.props.onChange({ target: { value: "New name" } });
  h.render();
  h.click("Revisar cambios");
  await tick();
  h.render();
  const output = h.nodes().find((n) => n.type === "ActionOutput");
  assert.equal(output.props.value.proposals.length, 1);
  assert(h.nodes().some((n) => n.props?.role === "alert"));
  h.click("Volver al editor");
  h.render();
  assert.equal(
    field(h, "studio_general_prompt").props.value,
    "Changed exact prompt",
  );
  assert(!h.calls.some(([path]) => path.includes("approve")));
});
test("audio and LLM buttons prepare exact saved-version proposals without executing or approving", async () => {
  const h = studio({}, async (_path, _method, body) => ({
    proposals: [
      {
        id: "p",
        action: "retell.execute",
        arguments: body.arguments,
        status: "pending",
        version: 1,
      },
    ],
  }));
  h.click("Preparar prueba de audio");
  await tick();
  h.render();
  assert.deepEqual(h.calls[0], [
    "hermes/actions",
    "POST",
    {
      action: "retell.execute",
      arguments: {
        endpoint: "createWebCall",
        arguments: {
          requestBody: { agent_id: "agent_local", agent_version: 0 },
        },
      },
    },
  ]);
  assert(h.nodes().some((n) => n.type === "ActionOutput"));
  assert(!h.nodes().some((n) => n.type === "RetellPanel"));
  h.click("Volver al editor");
  h.render();
  h.click("Prueba LLM");
  h.render();
  change(h, "studio_test_message", "Hello");
  h.click("Preparar prueba LLM");
  await tick();
  h.render();
  assert.deepEqual(h.calls[1][2], {
    action: "retell.execute",
    arguments: {
      endpoint: "agentPlaygroundCompletion",
      arguments: {
        agent_id: "agent_local",
        version: 0,
        requestBody: { messages: [{ role: "user", content: "Hello" }] },
      },
    },
  });
  assert(!h.calls.some(([path]) => path.includes("approve")));
});

test("confirmed write invalidates both stale editor snapshots until explicit reload", async () => {
  const h = studio({}, async () => ({ proposals: [] }));
  h.click("Preparar prueba de audio");
  await tick();
  h.render();
  await h
    .nodes()
    .find((n) => n.type === "ActionOutput")
    .props.onResult({
      provider: "retell",
      status: "completed",
      endpoint: "updateAgent",
    });
  h.render();
  h.click("Volver al editor");
  h.render();
  assert.equal(field(h, "studio_general_prompt").props.readOnly, true);
  assert(
    h
      .nodes()
      .find(
        (n) => n.type === "button" && n.props.children === "Revisar cambios",
      ).props.disabled,
  );
});
test("workflow and simulation preserve editing state and fetch cases only for saved linked engine", async () => {
  const h = studio({}, async () => ({
    provider: "retell",
    status: "completed",
    endpoint: "listTestCaseDefinitions",
    data: [],
  }));
  change(h, "studio_general_prompt", "Unsaved prompt");
  h.click("Flujo de trabajo");
  h.render();
  assert(h.nodes().some((n) => n.props?.["aria-label"] === "Flujo de trabajo"));
  h.click("Simulación");
  await tick();
  h.render();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0], [
    "retell/read",
    "POST",
    {
      revision: 1,
      endpoint: "listTestCaseDefinitions",
      arguments: { type: "retell-llm", llm_id: "llm_local", limit: 50 },
    },
  ]);
  h.click("Agente");
  h.render();
  assert.equal(field(h, "studio_general_prompt").props.value, "Unsaved prompt");
});
test("unavailable linked instructions stay read-only while agent settings remain editable", () => {
  const h = studio({ instructions: undefined, warning: "Unavailable" });
  assert.equal(field(h, "studio_general_prompt").props.readOnly, true);
  const voice = field(h, "studio_voice_id");
  assert.equal(voice.props.disabled, false);
});

test("settling a request after studio unmount releases only its owned parent lock", async () => {
  let resolve;
  const pending = new Promise((done) => (resolve = done)),
    events = [];
  const h = studio(
    { onPendingChange: (value, owner) => events.push([value, owner]) },
    () => pending,
  );
  const name = h
    .nodes()
    .find((n) => n.props?.["aria-label"] === "Nombre del agente");
  name.props.onChange({ target: { value: "Changed" } });
  h.render();
  h.click("Revisar cambios");
  await tick();
  assert.equal(events.length, 1);
  assert.equal(events[0][0], true);
  h.unmount();
  resolve({
    proposals: [
      {
        id: "p",
        action: "retell.execute",
        arguments: {},
        status: "pending",
        version: 1,
      },
    ],
  });
  await tick();
  assert.equal(events.length, 2);
  assert.equal(events[1][0], false);
  assert.equal(events[0][1], events[1][1]);
  assert.equal(typeof events[1][1], "symbol");
});

test("unmount stops dependent proposal creation after the current request settles", async () => {
  let resolve;
  const pending = new Promise((done) => (resolve = done));
  const h = studio({}, () => pending);
  change(h, "studio_general_prompt", "Changed prompt");
  h.nodes()
    .find((n) => n.props?.["aria-label"] === "Nombre del agente")
    .props.onChange({ target: { value: "Changed name" } });
  h.render();
  h.click("Revisar cambios");
  await tick();
  assert.equal(h.calls.length, 1);
  h.unmount();
  resolve({
    proposals: [
      {
        id: "p",
        action: "retell.execute",
        arguments: {},
        status: "pending",
        version: 1,
      },
    ],
  });
  await tick();
  assert.equal(h.calls.length, 1);
});

test("toolbar resolves pinned allOf enums so model and language can actually be changed", () => {
  const h = studio();
  for (const name of ["studio_model", "studio_language"]) {
    const control = field(h, name);
    const options = h.nodes(control).filter((n) => n.type === "option");
    assert(options.length > 5, `${name} must expose real approved choices`);
  }
});
