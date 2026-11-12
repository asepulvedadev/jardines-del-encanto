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
        (options.component ?? "retell-result.tsx"),
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
      ? module.exports.ElevenLabsPanel({
          request,
          onChanged: async () => {},
          active: true,
        })
      : module.exports.RetellVoiceResult({
          result: { provider: "retell", status: "ready", session_id: id },
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
async function start(h) {
  h.click("Iniciar sesión de voz");
  await tick();
  h.claim.resolve({ access_token: "synthetic-one-shot-token" });
  await tick();
}
async function connect(h) {
  await start(h);
  h.sdk.resolve(h.session);
  await tick();
}
test("session is idle until explicit start, double activation claims once, mute and stop clean up", async () => {
  const h = harness();
  await tick();
  assert.equal(h.calls.length, 0);
  assert.equal(h.sdkCalls.length, 0);
  h.click("Iniciar sesión de voz");
  h.button("Iniciando…").props.onClick();
  await tick();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0], [`retell/sessions/${id}/claim`, "POST", {}]);
  h.claim.resolve({ access_token: "synthetic-one-shot-token" });
  await tick();
  assert.equal(h.sdkCalls.length, 1);
  assert.equal(h.sdkCalls[0].accessToken, "synthetic-one-shot-token");
  h.sdk.resolve(h.session);
  await tick();
  h.click("Silenciar micrófono");
  assert.equal(h.button("Activar micrófono").props["aria-pressed"], true);
  h.click("Activar micrófono");
  assert.deepEqual(h.muted, [true, false]);
  assert.equal([...h.timers.values()][0].ms, 300000);
  h.click("Finalizar");
  assert.equal(h.ended, 1);
  assert.equal(h.timers.size, 0);
  h.button("Sesión finalizada").props.onClick();
  await tick();
  assert.equal(h.calls.length, 1);
  h.unmount();
  assert.equal(h.ended, 1);
});
for (const mode of ["cancel", "unmount"]) {
  test(`${mode} while claim is pending never starts SDK`, async () => {
    const h = harness();
    h.click("Iniciar sesión de voz");
    await tick();
    if (mode === "cancel") h.click("Finalizar");
    else h.unmount();
    h.claim.resolve({ access_token: "synthetic" });
    await tick();
    assert.equal(h.sdkCalls.length, 0);
    assert.equal(h.timers.size, 0);
  });
  test(`${mode} while SDK start is pending ends the eventual session`, async () => {
    const h = harness();
    await start(h);
    if (mode === "cancel") h.click("Finalizar");
    else h.unmount();
    h.sdk.resolve(h.session);
    await tick();
    assert.ok(h.ended >= 1);
    assert.equal(h.timers.size, 0);
  });
}
test("SDK error closes live session and disconnect removes timer", async () => {
  const h = harness();
  await connect(h);
  h.listeners.error("synthetic");
  await tick();
  assert.equal(h.ended, 1);
  assert.equal(h.timers.size, 0);
  assert.ok(h.button("Sesión finalizada"));
  const other = harness();
  await connect(other);
  other.listeners.call_ended();
  await tick();
  assert.equal(other.timers.size, 0);
  assert.ok(other.button("Sesión finalizada"));
  other.unmount();
});
test("SDK disconnect before start resolves cannot resurrect a closed session", async () => {
  const h = harness();
  await start(h);
  h.listeners.call_ended();
  h.sdk.resolve(h.session);
  await tick();
  assert.ok(h.button("Sesión finalizada"));
  assert.ok(h.ended >= 1);
  assert.equal(h.timers.size, 0);
});
test("five-minute timer, dialog close, details collapse and unmount stop active sessions", async () => {
  for (const mode of [
    "timer",
    "dialog",
    "details",
    "outerDetails",
    "unmount",
  ]) {
    const h = harness();
    await connect(h);
    if (mode === "timer") [...h.timers.values()][0].fn();
    else if (mode === "unmount") h.unmount();
    else {
      if (["details", "outerDetails"].includes(mode))
        h.parents[mode].open = false;
      h.emit(mode, mode === "dialog" ? "close" : "toggle");
    }
    await tick();
    assert.equal(h.ended, 1, mode);
    assert.equal(h.timers.size, 0, mode);
  }
});
test("claim failure is single-use and never starts the microphone SDK", async () => {
  const h = harness();
  h.click("Iniciar sesión de voz");
  await tick();
  h.claim.reject(new Error("fixture"));
  await tick();
  assert.equal(h.sdkCalls.length, 0);
  assert.ok(h.button("Sesión finalizada"));
  h.button("Sesión finalizada").props.onClick();
  await tick();
  assert.equal(h.calls.length, 1);
});
