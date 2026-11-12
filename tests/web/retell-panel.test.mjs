import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";
const require = createRequire(import.meta.url);
const id = "00000000-0000-4000-8000-000000000001";
const tick = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function harness(options = {}) {
  let cursor = 0,
    tree,
    mounted = true;
  const hooks = [],
    effects = [],
    timers = new Map(),
    calls = [],
    sdkCalls = [],
    muted = [];
  const claim = deferred(),
    sdk = deferred();
  let ended = 0,
    timerId = 0;
  const listeners = {};
  const session = {
    on: (event, fn) => {
      listeners[event] = fn;
      return session;
    },
    removeAllListeners: () => {},
    startCall: (options) => {
      sdkCalls.push(options);
      return sdk.promise;
    },
    stopCall: () => {
      ended++;
    },
    mute: () => muted.push(true),
    unmute: () => muted.push(false),
  };
  const parents = Object.fromEntries(
    ["dialog", "details", "outerDetails"].map((name) => [
      name,
      {
        open: true,
        listeners: new Map(),
        addEventListener(event, fn) {
          this.listeners.set(event, fn);
        },
        removeEventListener(event) {
          this.listeners.delete(event);
        },
      },
    ]),
  );
  parents.details.tagName = parents.outerDetails.tagName = "DETAILS";
  parents.details.parentElement = parents.outerDetails;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks))
        hooks[index] = typeof initial === "function" ? initial() : initial;
      return [
        hooks[index],
        (value) => {
          hooks[index] =
            typeof value === "function" ? value(hooks[index]) : value;
        },
      ];
    },
    useCallback(fn, deps) {
      const index = cursor++;
      return (hooks[index] ??= fn);
    },
    useRef(initial) {
      const index = cursor++;
      return (hooks[index] ??= { current: initial });
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!(index in hooks)) {
        hooks[index] = { deps };
        effects.push(() => {
          hooks[index].cleanup = effect();
        });
      }
    },
  };
  const module = { exports: {} };
  const source = readFileSync(
    new URL(
      "../../apps/web/components/crm/" +
        (options.component ?? "retell-panel.tsx"),
      import.meta.url,
    ),
    "utf8",
  );
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const fakeRequire = (name) => {
    if (name === "react") return react;
    if (name === "react/jsx-runtime")
      return {
        Fragment: "fragment",
        jsx: (type, props) => ({ type, props }),
        jsxs: (type, props) => ({ type, props }),
      };
    if (name === "retell-client-js-sdk")
      return {
        RetellWebClient: class {
          constructor() {
            return session;
          }
        },
      };
    if (name === "./hermes-panel") return { ActionOutput: "ActionOutput" };
    if (name === "./sara-types") return {};
    if (name === "./retell-schema") {
      const module = { exports: {} };
      const schemaCode = ts.transpileModule(
        readFileSync(
          new URL(
            "../../apps/web/components/crm/retell-schema.tsx",
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
      ).outputText;
      new Function("require", "module", "exports", schemaCode)(
        fakeRequire,
        module,
        module.exports,
      );
      return module.exports;
    }
    if (name === "./settings-types")
      return { settingsError: (cause) => cause.message };
    return require(name);
  };
  new Function(
    "require",
    "module",
    "exports",
    "setTimeout",
    "clearTimeout",
    code,
  )(
    fakeRequire,
    module,
    module.exports,
    (fn, ms) => {
      const timer = ++timerId;
      timers.set(timer, { fn, ms });
      return timer;
    },
    (timer) => timers.delete(timer),
  );
  const request = async (...args) => {
    calls.push(args);
    return options.request ? options.request(...args) : claim.promise;
  };
  function render() {
    cursor = 0;
    tree = options.component
      ? module.exports.RetellPanel({
          request,
          onChanged: async () => {},
          active: options.active ?? true,
          connectionEnabled: options.connectionEnabled,
        })
      : module.exports.RetellVoiceResult({
          result: { status: "ready", session_id: id },
          request,
        });
    if (tree.props.ref)
      tree.props.ref.current = {
        closest: (name) => parents[name],
        parentElement: parents.details,
      };
    while (effects.length) effects.shift()();
    return tree;
  }
  function nodes(node) {
    if (!arguments.length) node = tree;
    if (!node || typeof node !== "object") return [];
    return [
      node,
      ...[node.props?.children].flat(Infinity).flatMap((child) => nodes(child)),
    ];
  }
  function button(text) {
    render();
    return nodes().find(
      (node) => node.type === "button" && node.props.children === text,
    );
  }
  function click(text) {
    const value = button(text);
    assert.ok(value, `Button ${text} exists`);
    value.props.onClick();
  }
  function unmount() {
    mounted = false;
    for (const hook of hooks) hook?.cleanup?.();
  }
  function emit(parent, event) {
    parents[parent].listeners.get(event)?.();
  }
  render();
  return {
    render,
    nodes,
    setConnectionEnabled(value) {
      options.connectionEnabled = value;
      return render();
    },
    change(id, value) {
      render();
      const node = nodes().find((n) => n.props?.id === id);
      assert.ok(node, id);
      node.props.onChange({ target: { value, checked: !!value } });
    },
    submit() {
      render();
      const node = nodes()
        .filter((n) => n.type === "form")
        .at(-1);
      node.props.onSubmit({ preventDefault() {} });
    },
    click,
    button,
    claim,
    sdk,
    session,
    calls,
    sdkCalls,
    listeners,
    timers,
    muted,
    parents,
    emit,
    unmount,
    get ended() {
      return ended;
    },
    get mounted() {
      return mounted;
    },
  };
}
const defaults = { agent_id: "agent", chat_agent_id: "", from_number: "" };
const operation = {
  endpoint: "getCall",
  method: "GET",
  path: "/v2/get-call/{call_id}",
  summary: "Retrieve call",
  group: "Calls",
  risk: "read",
  available: true,
};
function fixture(extra = {}) {
  let revision = 1;
  return harness({
    component: "retell-panel.tsx",
    request: async (path, method, body) => {
      if (extra.request) {
        const value = extra.request(path, method, body);
        if (value !== undefined) return value;
      }
      if (path === "retell/settings" && method === "POST") revision++;
      if (path === "retell/settings")
        return {
          available: true,
          configured: true,
          verified: true,
          enabled: true,
          revision,
          defaults: extra.defaults ?? defaults,
        };
      if (path === "retell/catalog")
        return {
          revision,
          registry_revision: "fixture",
          operations: [operation, ...(extra.operations ?? [])],
          new_operations: [],
        };
      if (path === "retell/schema")
        return {
          revision,
          endpoint: body.endpoint,
          input_schema: {
            type: "object",
            required: ["call_id"],
            properties: { call_id: { type: "string" } },
          },
          schema_hash: "fixture",
          metadata: operation,
        };
      if (path === "hermes/actions") return { proposals: [] };
      if (path === "workspace")
        return { contacts: [{ id, name: "Cliente", phone: "+573001234567" }] };
      throw new Error(path);
    },
  });
}
test("settings key is empty and saving clears it while refreshing the revision", async () => {
  const h = fixture();
  await tick();
  h.change("retell-key", "synthetic-private-key");
  h.change("retell-replace", true);
  h.click("Guardar conexión");
  await tick();
  h.render();
  assert.equal(
    h.nodes().find((n) => n.props?.id === "retell-key").props.value,
    "",
  );
  assert.equal(
    h.calls.find((c) => c[0] === "retell/settings" && c[1] === "POST")[2]
      .api_key,
    "synthetic-private-key",
  );
  assert.equal(
    h.calls.findLast((c) => c[0] === "retell/catalog")[2].revision,
    2,
  );
});
test("operation prepares shared broker proposal only after explicit review action", async () => {
  const h = fixture();
  await tick();
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "getCall");
  await tick();
  h.change("retell-field-call_id", "call_example");
  assert.equal(h.calls.filter((c) => c[0] === "hermes/actions").length, 0);
  h.submit();
  await tick();
  assert.deepEqual(h.calls.find((c) => c[0] === "hermes/actions")[2], {
    action: "retell.execute",
    arguments: { endpoint: "getCall", arguments: { call_id: "call_example" } },
  });
});
test("blocked multipart operations never request schema or draft actions", async () => {
  const h = fixture({
    operations: [
      {
        ...operation,
        endpoint: "uploadAudio",
        available: false,
        blocked_reason: "requires_file_adapter",
      },
    ],
  });
  await tick();
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "uploadAudio");
  await tick();
  assert.equal(h.button("Preparar propuesta").props.disabled, true);
  assert.equal(
    h.calls.filter((c) => c[0] === "retell/schema" || c[0] === "hermes/actions")
      .length,
    0,
  );
});
test("outbound JSON always binds one exact CRM recipient instead of a typed number", async () => {
  const call = { ...operation, endpoint: "createPhoneCall", risk: "paid" };
  const h = fixture({
    operations: [call],
    request: (path, method, body) => {
      if (path === "retell/schema")
        return {
          revision: 1,
          endpoint: body.endpoint,
          input_schema: {
            type: "object",
            required: ["requestBody"],
            properties: {
              requestBody: {
                type: "object",
                required: ["to_number"],
                properties: {
                  to_number: { type: "string" },
                  agent_id: { type: "string" },
                },
              },
            },
          },
          schema_hash: "fixture",
          metadata: call,
        };
    },
  });
  await tick();
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "createPhoneCall");
  await tick();
  assert.equal(
    h.nodes().some((n) => n.props?.id === "retell-field-requestBody.to_number"),
    false,
  );
  h.change("retell-contact", id);
  h.click("JSON avanzado");
  h.change(
    "retell-json",
    '{"requestBody":{"to_number":"+15550000000","agent_id":"agent"}}',
  );
  h.submit();
  await tick();
  assert.deepEqual(h.calls.find((c) => c[0] === "hermes/actions")[2], {
    action: "retell.execute",
    arguments: {
      endpoint: "createPhoneCall",
      arguments: {
        requestBody: { to_number: "+573001234567", agent_id: "agent" },
      },
      contacts: [{ contact_id: id, expected_phone: "+573001234567" }],
    },
  });
});
test("bulk operation is honest unavailable in one-recipient editor", async () => {
  const h = fixture({
    operations: [{ ...operation, endpoint: "createBatchCall", risk: "paid" }],
  });
  await tick();
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "createBatchCall");
  await tick();
  assert.equal(h.button("Preparar propuesta").props.disabled, true);
  h.submit();
  await tick();
  assert.equal(
    h.calls.some((c) => c[0] === "hermes/actions"),
    false,
  );
});
test("disconnect only happens after named confirmation", async () => {
  const h = fixture({
    request: (path) => (path === "retell/disconnect" ? {} : undefined),
  });
  await tick();
  h.click("Desconectar");
  await tick();
  assert.equal(
    h.calls.some((c) => c[0] === "retell/disconnect"),
    false,
  );
  h.click("Confirmar desconexión");
  await tick();
  assert.deepEqual(
    h.calls.find((c) => c[0] === "retell/disconnect"),
    ["retell/disconnect", "POST", { revision: 1 }],
  );
});
test("malformed advanced JSON reports error without sending a broker request", async () => {
  const h = fixture();
  await tick();
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "getCall");
  await tick();
  h.click("JSON avanzado");
  h.change("retell-json", "null");
  h.submit();
  await tick();
  h.render();
  assert.equal(
    h.calls.some((c) => c[0] === "hermes/actions"),
    false,
  );
  assert.ok(h.nodes().some((n) => n.props?.role === "alert"));
});

test("chat operations seed the configured chat agent rather than voice agent", async () => {
  const chat = { ...operation, endpoint: "createChat", group: "Chat" };
  const h = fixture({
    operations: [chat],
    defaults: { ...defaults, chat_agent_id: "chat-agent" },
    request: (path, method, body) => {
      if (path === "retell/schema")
        return {
          revision: 1,
          endpoint: body.endpoint,
          input_schema: {
            type: "object",
            properties: {
              requestBody: {
                type: "object",
                properties: { agent_id: { type: "string" } },
              },
            },
          },
          schema_hash: "fixture",
          metadata: chat,
        };
    },
  });
  await tick();
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "createChat");
  await tick();
  h.render();
  assert.equal(
    h.nodes().find((n) => n.props?.id === "retell-field-requestBody.agent_id")
      .props.value,
    "chat-agent",
  );
});

test("replacing an existing key requires explicit confirmation", async () => {
  const h = fixture();
  await tick();
  h.change("retell-key", "synthetic-replacement");
  h.click("Guardar conexión");
  await tick();
  assert.equal(
    h.calls.some((c) => c[0] === "retell/settings" && c[1] === "POST"),
    false,
  );
});

test("parent connection toggles update status and proposal controls without losing the draft", async () => {
  const h = fixture({
    request: (path, method) =>
      path === "retell/settings" && method !== "POST"
        ? {
            available: true,
            configured: true,
            verified: true,
            enabled: false,
            revision: 1,
            defaults,
          }
        : undefined,
  });
  await tick();
  h.setConnectionEnabled(false);
  h.click("Consultar catálogo");
  await tick();
  h.change("retell-operation", "getCall");
  await tick();
  h.change("retell-field-call_id", "retained-call");
  const status = () => {
    h.render();
    return h.nodes().find((n) => n.props?.className === "social-status").props
      .children;
  };
  assert.equal(status(), "Pausado");
  assert.equal(h.button("Preparar propuesta").props.disabled, true);
  const count = h.calls.length;
  h.setConnectionEnabled(true);
  assert.equal(status(), "Verificado");
  assert.equal(h.button("Preparar propuesta").props.disabled, false);
  assert.equal(
    h.nodes().find((n) => n.props?.id === "retell-field-call_id").props.value,
    "retained-call",
  );
  assert.equal(
    h.nodes().find((n) => n.props?.id === "retell-key").props.value,
    "",
  );
  assert.equal(h.calls.length, count);
  h.submit();
  await tick();
  assert.equal(h.calls.filter((c) => c[0] === "hermes/actions").length, 1);
  h.setConnectionEnabled(false);
  assert.equal(status(), "Pausado");
  assert.equal(h.button("Preparar propuesta").props.disabled, true);
  assert.equal(
    h.nodes().find((n) => n.props?.id === "retell-field-call_id").props.value,
    "retained-call",
  );
  h.submit();
  await tick();
  assert.equal(h.calls.filter((c) => c[0] === "hermes/actions").length, 1);
});
