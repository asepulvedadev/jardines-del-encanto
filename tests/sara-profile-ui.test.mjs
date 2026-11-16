import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const profile = (extra = {}) => ({
  version: 1,
  name: "Sara",
  instructions: "Responde con claridad.",
  knowledge: "",
  greeting: "Hola",
  response_style: "balanced",
  updated_at: "2026-11-15T12:00:00Z",
  ...extra,
});
const job = (extra = {}) => ({
  id: "00000000-0000-4000-8000-000000000001",
  status: "queued",
  synthetic: true,
  profile_version: 1,
  transcript: [],
  ...extra,
});
function harness(request, initialActive = true) {
  const states = [],
    refs = [],
    effectDeps = [],
    callbackDeps = [],
    callbacks = [],
    cleanups = [],
    effects = [],
    timers = new Map();
  let si = 0,
    ri = 0,
    ei = 0,
    ci = 0,
    timerId = 0,
    tree,
    active = initialActive;
  const equal = (old, next) =>
    old && old.length === next.length && next.every((v, i) => v === old[i]);
  const react = {
    useState(initial) {
      const i = si++;
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
      return (refs[ri++] ??= { current: initial });
    },
    useCallback(fn, deps) {
      const i = ci++;
      if (!equal(callbackDeps[i], deps)) {
        callbackDeps[i] = deps;
        callbacks[i] = fn;
      }
      return callbacks[i];
    },
    useEffect(fn, deps) {
      const i = ei++;
      if (!equal(effectDeps[i], deps)) {
        effectDeps[i] = deps;
        effects.push(() => {
          cleanups[i]?.();
          cleanups[i] = fn();
        });
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const compiled = ts.transpileModule(
    readFileSync(
      new URL(
        "../apps/web/components/crm/sara-profile-panel.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const module = { exports: {} };
  new Function(
    "require",
    "module",
    "exports",
    "setTimeout",
    "clearTimeout",
    compiled,
  )(
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
    (fn) => {
      timers.set(++timerId, fn);
      return timerId;
    },
    (id) => timers.delete(id),
  );
  const render = () => {
    si = ri = ei = ci = 0;
    tree = module.exports.SaraProfilePanel({ request, active });
    return tree;
  };
  const descend = (node) =>
    node == null || typeof node !== "object"
      ? []
      : Array.isArray(node)
        ? node.flatMap(descend)
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
    timers,
    active(value) {
      active = value;
      render();
    },
    field: (id) => nodes().find((node) => node.props?.id === id),
    button: (label) =>
      nodes().find((node) => node.type === "button" && text(node) === label),
    async flush() {
      for (const fn of effects.splice(0)) fn();
      await new Promise((resolve) => setImmediate(resolve));
      render();
    },
    async tick() {
      const [id, fn] = timers.entries().next().value ?? [];
      if (fn) {
        timers.delete(id);
        await fn();
        await new Promise((resolve) => setImmediate(resolve));
        render();
      }
    },
  };
}
function responder(calls, custom = () => undefined) {
  return async (path, method = "GET", payload) => {
    calls.push({ path, method, payload });
    const result = custom(path, method, payload);
    if (result !== undefined) return await result;
    if (path === "sara/config") return profile();
    if (path === "sara/config/versions")
      return {
        versions: [
          {
            version: 1,
            document: profile(),
            author: "Administración",
            source: "web",
            created_at: "2026-11-15T12:00:00Z",
          },
        ],
      };
    if (path === "sara/simulations") return { simulations: [] };
    throw new Error(`Unexpected ${path}`);
  };
}

test("profile loads only reads, renders bounded editable fields and readable published history", async () => {
  const calls = [],
    h = harness(responder(calls));
  h.render();
  await h.flush();
  assert.ok(calls.every((call) => call.method === "GET"));
  assert.equal(h.field("sara-profile-name").props.maxLength, 80);
  assert.equal(h.field("sara-profile-instructions").props.maxLength, 2000);
  assert.equal(h.field("sara-profile-knowledge").props.maxLength, 4000);
  assert.equal(h.field("sara-profile-greeting").props.maxLength, 300);
  assert.match(h.text(h.render()), /Versión\s+1/);
  assert.match(h.text(h.render()), /Administración/);
  assert.doesNotMatch(
    h.text(h.render()),
    /API key|Credenciales|Runtime|Permisos de código/,
  );
});

test("stale save retains text and refresh requires explicit review before rebasing", async () => {
  const calls = [],
    h = harness(
      responder(calls, (path, method) => {
        if (method === "PATCH")
          throw new Error("La configuración cambió en otra sesión.");
      }),
    );
  h.render();
  await h.flush();
  h.field("sara-profile-knowledge").props.onChange({
    target: { value: "Borrador local" },
  });
  h.render();
  await h.button("Publicar cambios").props.onClick();
  h.render();
  assert.equal(calls.at(-1).payload.version, 1);
  assert.equal(h.field("sara-profile-knowledge").props.value, "Borrador local");
  assert.equal(h.button("Publicar cambios").props.disabled, true);
  await h.button("Actualizar perfil").props.onClick();
  h.render();
  assert.equal(h.field("sara-profile-knowledge").props.value, "Borrador local");
  assert.ok(h.button("Revisé la versión publicada"));
});

test("simulation validates one to four synthetic turns and reuses request identity after unknown creation", async () => {
  const calls = [],
    h = harness(
      responder(calls, (path, method) => {
        if (path === "sara/simulations" && method === "POST")
          throw new Error("Sin conexión");
      }),
    );
  h.render();
  await h.flush();
  h.field("sara-simulation-title").props.onChange({
    target: { value: "Prueba de atención" },
  });
  h.field("sara-simulation-turn-0").props.onChange({
    target: { value: "¿Dónde queda el proyecto?" },
  });
  h.render();
  await h.button("Simular conversación").props.onClick();
  h.render();
  const first = calls.find((call) => call.method === "POST").payload;
  assert.match(first.request_id, /^[0-9a-f-]{36}$/);
  assert.deepEqual(first.customer_turns, ["¿Dónde queda el proyecto?"]);
  assert.match(h.text(h.render()), /No sabemos si/);
  await h.button("Reintentar misma solicitud").props.onClick();
  h.render();
  assert.deepEqual(calls.at(-1).payload, first);
  assert.match(h.text(h.render()), /No envía mensajes reales/);
});

test("visible queued job polls and renders escaped synthetic transcript without training actions", async () => {
  const calls = [],
    h = harness(
      responder(calls, (path, method) => {
        if (path === "sara/simulations" && method === "POST") return job();
        if (path.startsWith("sara/simulations/"))
          return job({
            status: "completed",
            transcript: [
              { role: "user", content: "<script>cliente</script>" },
              { role: "assistant", content: "Respuesta simulada" },
            ],
          });
      }),
    );
  h.render();
  await h.flush();
  h.field("sara-simulation-title").props.onChange({
    target: { value: "Prueba" },
  });
  h.field("sara-simulation-turn-0").props.onChange({
    target: { value: "Hola" },
  });
  h.render();
  await h.button("Simular conversación").props.onClick();
  h.render();
  await h.flush();
  assert.equal(h.timers.size, 1);
  await h.tick();
  await h.flush();
  assert.match(h.text(h.render()), /Respuesta simulada/);
  assert.match(h.text(h.render()), /Cliente ficticio/);
  assert.equal(h.timers.size, 0);
  assert.ok(
    calls
      .filter((call) => call.method === "POST")
      .every((call) => call.path === "sara/simulations"),
  );
  assert.doesNotMatch(
    readFileSync(
      new URL(
        "../apps/web/components/crm/sara-profile-panel.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    /dangerouslySetInnerHTML|fetch\(/,
  );
});

test("polling stops after bounded failures and inactive panel clears timers", async () => {
  const calls = [],
    h = harness(
      responder(calls, (path, method) => {
        if (path === "sara/simulations" && method === "POST") return job();
        if (path.startsWith("sara/simulations/"))
          throw new Error("Sin conexión");
      }),
    );
  h.render();
  await h.flush();
  h.field("sara-simulation-title").props.onChange({
    target: { value: "Prueba" },
  });
  h.field("sara-simulation-turn-0").props.onChange({
    target: { value: "Hola" },
  });
  h.render();
  await h.button("Simular conversación").props.onClick();
  h.render();
  await h.flush();
  assert.equal(h.timers.size, 1);
  h.active(false);
  await h.flush();
  assert.equal(h.timers.size, 0);
  h.active(true);
  await h.flush();
  assert.equal(h.timers.size, 1);
  for (let i = 0; i < 3; i++) {
    await h.tick();
    await h.flush();
  }
  assert.equal(h.timers.size, 0);
  assert.match(h.text(h.render()), /No pudimos confirmar el estado/);
  await h.button("Consultar resultado").props.onClick();
  h.render();
  await h.flush();
  h.active(false);
  await h.flush();
  assert.equal(h.timers.size, 0);
});

test("successful publication uses only allowed fields and updates the confirmed version", async () => {
  const calls = [],
    h = harness(
      responder(calls, (path, method, payload) =>
        method === "PATCH" ? profile({ ...payload, version: 2 }) : undefined,
      ),
    );
  h.render();
  await h.flush();
  h.field("sara-profile-instructions").props.onChange({
    target: { value: "Nuevas instrucciones" },
  });
  h.render();
  await h.button("Publicar cambios").props.onClick();
  h.render();
  const write = calls.find((call) => call.method === "PATCH");
  assert.deepEqual(
    Object.keys(write.payload).sort(),
    [
      "version",
      "name",
      "instructions",
      "knowledge",
      "greeting",
      "response_style",
    ].sort(),
  );
  assert.equal(write.payload.version, 1);
  assert.match(h.text(h.render()), /Versión\s+2/);
  assert.equal(h.button("Publicar cambios").props.disabled, true);
});

test("blank inputs never publish or launch jobs and synthetic turns cap at four", async () => {
  const calls = [],
    h = harness(responder(calls));
  h.render();
  await h.flush();
  h.field("sara-profile-name").props.onChange({ target: { value: "   " } });
  h.render();
  await h.button("Publicar cambios").props.onClick();
  h.render();
  await h.button("Simular conversación").props.onClick();
  h.render();
  assert.ok(calls.every((call) => call.method === "GET"));
  assert.match(h.text(h.render()), /Escribe el nombre/);
  for (let i = 0; i < 3; i++) {
    h.button("Agregar mensaje").props.onClick();
    h.render();
  }
  assert.equal(h.button("Agregar mensaje").props.disabled, true);
  assert.equal(h.field("sara-simulation-turn-3").props.maxLength, 800);
  assert.equal(h.field("sara-simulation-title").props.maxLength, 120);
});

test("known failed and unknown results remain distinct and do not auto-train", async () => {
  for (const status of ["failed", "unrecognized"]) {
    const calls = [],
      h = harness(
        responder(calls, (path, method) =>
          path === "sara/simulations" && method === "POST"
            ? job({ status })
            : undefined,
        ),
      );
    h.render();
    await h.flush();
    h.field("sara-simulation-title").props.onChange({
      target: { value: "Prueba" },
    });
    h.field("sara-simulation-turn-0").props.onChange({
      target: { value: "Hola" },
    });
    h.render();
    await h.button("Simular conversación").props.onClick();
    h.render();
    await h.flush();
    assert.match(
      h.text(h.render()),
      status === "failed"
        ? /La simulación no se completó/
        : /Estado desconocido/,
    );
    assert.equal(h.timers.size, 0);
    assert.equal(calls.filter((call) => call.method === "POST").length, 1);
  }
});
