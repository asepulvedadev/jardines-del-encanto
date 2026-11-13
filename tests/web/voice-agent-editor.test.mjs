import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const schemas = JSON.parse(
  readFileSync(
    new URL("../../ops/retell/schemas.json", import.meta.url),
    "utf8",
  ),
);
function harness(overrides = {}) {
  const hooks = [],
    calls = [];
  let cursor = 0,
    tree;
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
    useRef(initial) {
      const index = cursor++;
      return (hooks[index] ??= { current: initial });
    },
    useId() {
      cursor++;
      return "editor";
    },
  };
  const load = (file) => {
    const module = { exports: {} };
    const code = ts.transpileModule(
      readFileSync(
        new URL(`../../apps/web/components/crm/${file}`, import.meta.url),
        "utf8",
      ),
      {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          jsx: ts.JsxEmit.ReactJSX,
          target: ts.ScriptTarget.ES2022,
        },
      },
    ).outputText;
    new Function("require", "module", "exports", code)(
      (name) => {
        if (name === "react") return react;
        if (name === "react/jsx-runtime")
          return {
            Fragment: "fragment",
            jsx: (type, props) => ({ type, props }),
            jsxs: (type, props) => ({ type, props }),
          };
        if (name === "./voice-agent-model") return load("voice-agent-model.ts");
        if (name === "./voice-schema-model")
          return load("voice-schema-model.ts");
        if (name === "./voice-schema-editor")
          return { VoiceSchemaEditor: "VoiceSchemaEditor" };
        throw new Error(`Unexpected runtime dependency: ${name}`);
      },
      module,
      module.exports,
    );
    return module.exports;
  };
  const { VoiceAgentEditor } = load("voice-agent-editor.tsx");
  const props = {
    kind: "agent",
    schemas,
    voices: [],
    models: [],
    busy: false,
    onSubmit: async (...args) => calls.push(args),
    onCancel() {},
    ...overrides,
  };
  const render = () => {
    cursor = 0;
    tree = VoiceAgentEditor(props);
    return tree;
  };
  function all(node = tree) {
    if (!node || typeof node !== "object") return [];
    return [
      node,
      ...[node.props?.children ?? []]
        .flat(Infinity)
        .flatMap((child) => (child == null ? [] : all(child))),
    ];
  }
  const field = (name) => all().find((node) => node.props?.name === name);
  const change = (name, value) => {
    field(name).props.onChange({
      target: { value, checked: value },
      currentTarget: { value, checked: value },
    });
    render();
  };
  const submit = async () => {
    await all()
      .find((node) => node.type === "form")
      .props.onSubmit({ preventDefault() {} });
    render();
  };
  render();
  return { calls, props, render, all, field, change, submit };
}
test("native agent form only reviews after explicit input; catalogue IDs remain editable", async () => {
  const h = harness({
    voices: [null, { voice_id: "v", voice_name: "Voice" }],
    models: [null],
  });
  assert.equal(h.calls.length, 0);
  for (const [name, value] of Object.entries({
    agent_name: "Sara",
    voice_id: "voice_explicit",
    llm_id: "llm_explicit",
    language: "es-419",
  }))
    h.change(name, value);
  await h.submit();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0][0], "createAgent");
  assert.deepEqual(h.calls[0][1].requestBody.response_engine, {
    type: "retell-llm",
    llm_id: "llm_explicit",
  });
  assert(
    h.all().some((node) => node.props?.children === "Revisar nuevo agente"),
  );
});
test("complete prompt and greeting edit directly, while partial text never becomes an editable prefill", async () => {
  const record = {
    llm_id: "l",
    general_prompt: "Complete prompt",
    begin_message: "Complete greeting",
  };
  const partial = harness({ kind: "instructions", record });
  assert.equal(partial.field("general_prompt").props.readOnly, true);
  assert(!partial.field("replace_general_prompt"));
  partial.change("general_prompt", "Cannot replace a clipped prompt");
  await partial.submit();
  assert.equal(partial.calls.length, 0);
  const full = harness({
    kind: "instructions",
    record,
    completeFields: ["general_prompt", "begin_message"],
  });
  assert.equal(full.field("general_prompt").props.value, "Complete prompt");
  assert.equal(full.field("general_prompt").props.readOnly, false);
  assert(!full.field("replace_general_prompt"));
  full.change("general_prompt", "Edited full prompt");
  await full.submit();
  assert.deepEqual(full.calls[0], [
    "updateRetellLLM",
    { llm_id: "l", requestBody: { general_prompt: "Edited full prompt" } },
  ]);
});
test("custom engine remains omitted without explicit replacement; cancel/create-model are separate events", async () => {
  let cancelled = 0,
    created = 0;
  const h = harness({
    completeFields: ["agent_name"],
    record: {
      agent_id: "a",
      agent_name: "Old",
      response_engine: { type: "custom-llm" },
    },
    onCancel: () => cancelled++,
    onCreateModel: () => created++,
  });
  h.change("agent_name", "New");
  await h.submit();
  assert.deepEqual(h.calls[0][1].requestBody, { agent_name: "New" });
  assert(!h.field("llm_id"));
  h.all()
    .find((node) => node.props?.children === "Cancelar")
    .props.onClick();
  assert.equal(cancelled, 1);
  assert.equal(created, 0);
  const fresh = harness({ onCreateModel: () => created++ });
  fresh
    .all()
    .find((node) => node.props?.children === "Crear instrucciones primero")
    .props.onClick();
  assert.equal(created, 1);
  assert.equal(fresh.calls.length, 0);
});
test("busy/missing schemas/failures do not submit or discard the draft", async () => {
  const busy = harness({ busy: true });
  await busy.submit();
  assert.equal(busy.calls.length, 0);
  const unavailable = harness({ schemas: {} });
  await unavailable.submit();
  assert.equal(unavailable.calls.length, 0);
  const h = harness({
    onSubmit: async () => {
      throw new Error("Approval unavailable");
    },
  });
  for (const [name, value] of Object.entries({
    agent_name: "Sara",
    voice_id: "v",
    llm_id: "l",
  }))
    h.change(name, value);
  await h.submit();
  assert.equal(h.field("agent_name").props.value, "Sara");
  assert(h.all().some((node) => node.props?.role === "alert"));
});
test("restoring complete prompt text omits it, and explicit empty/null actions remain exact", async () => {
  const record = {
    llm_id: "l",
    general_prompt: "Original",
    begin_message: "Hello",
  };
  const h = harness({
    kind: "instructions",
    record,
    completeFields: ["general_prompt", "begin_message"],
  });
  h.change("general_prompt", "Temporary");
  h.change("general_prompt", "Original");
  h.change("begin_message", "Updated greeting");
  await h.submit();
  assert.deepEqual(h.calls[0][1].requestBody, {
    begin_message: "Updated greeting",
  });
  const empty = harness({
    kind: "instructions",
    record,
    completeFields: ["general_prompt", "begin_message"],
  });
  empty.change("general_prompt", "");
  await empty.submit();
  assert.deepEqual(empty.calls[0][1].requestBody, { general_prompt: "" });
  const dynamic = harness({
    kind: "instructions",
    record,
    completeFields: ["general_prompt", "begin_message"],
  });
  dynamic
    .all()
    .find((node) => node.props?.children === "Generar saludo dinámico")
    .props.onClick();
  dynamic.render();
  await dynamic.submit();
  assert.deepEqual(dynamic.calls[0][1].requestBody, { begin_message: null });
});
test("pending review handoff is single-flight and user draft remains intact", async () => {
  let release;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  let submitted = 0;
  const h = harness({
    onSubmit: async () => {
      submitted++;
      await pending;
    },
  });
  for (const [name, value] of Object.entries({
    agent_name: "Sara",
    voice_id: "v",
    llm_id: "l",
  }))
    h.change(name, value);
  const submit = h.all().find((node) => node.type === "form").props.onSubmit;
  const first = submit({ preventDefault() {} });
  const second = submit({ preventDefault() {} });
  assert.equal(submitted, 1);
  release();
  await Promise.all([first, second]);
  h.render();
  assert.equal(h.field("agent_name").props.value, "Sara");
});

test("voice picker presents names and keeps manual identifiers in a closed disclosure", () => {
  const h = harness({
    record: { agent_id: "a", agent_name: "Sara", voice_id: "v-current" },
    completeFields: ["agent_name", "voice_id"],
    voices: [{ voice_id: "v", voice_name: "Voz de prueba" }],
  });
  assert.equal(h.field("voice_id").type, "select");
  assert(
    h
      .all()
      .some(
        (node) =>
          node.type === "option" &&
          node.props.value === "v" &&
          node.props.children === "Voz de prueba",
      ),
  );
  assert(
    h
      .all()
      .some(
        (node) =>
          node.type === "option" &&
          node.props.value === "v-current" &&
          node.props.children === "Voz actual",
      ),
  );
  const manual = h
    .all()
    .find(
      (node) =>
        node.type === "details" &&
        String(node.props.children?.[0]?.props?.children).includes(
          "identificador",
        ),
    );
  assert(manual);
  assert(!manual.props.open);
  h.change("voice_id_manual", "voice_explicit");
  assert.equal(h.field("voice_id").props.value, "voice_explicit");
});

test("blocked complete prompt roots never collect or display hidden credential-bearing text", async () => {
  const h = harness({
    kind: "instructions",
    record: { llm_id: "l", general_prompt: "Hidden private configuration" },
    completeFields: ["general_prompt"],
    blockedFields: { general_prompt: "sensitive" },
  });
  assert.equal(h.field("general_prompt").props.value, "");
  assert.equal(h.field("general_prompt").props.readOnly, true);
  h.change("general_prompt", "Forged edit");
  await h.submit();
  assert.equal(h.calls.length, 0);
});

test("oversized proposal errors remain explicit without truncating the complete prompt draft", async () => {
  const original = "Full original prompt";
  const h = harness({
    kind: "instructions",
    record: { llm_id: "l", general_prompt: original },
    completeFields: ["general_prompt"],
    onSubmit: async () => {
      throw new Error("Arguments exceed 16KiB");
    },
  });
  const draft = "User authored full draft ".repeat(700);
  h.change("general_prompt", draft);
  await h.submit();
  assert.equal(h.field("general_prompt").props.value, draft);
  assert(
    h
      .all()
      .some(
        (node) =>
          node.props?.role === "alert" &&
          /límite de tamaño/.test(node.props.children),
      ),
  );
});
