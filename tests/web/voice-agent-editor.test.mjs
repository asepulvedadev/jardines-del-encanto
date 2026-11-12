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
test("rendered cached instructions are read-only and replacement starts blank", async () => {
  const h = harness({
    kind: "instructions",
    record: {
      llm_id: "l",
      general_prompt: "clipped prompt",
      begin_message: "clipped greeting",
      model_config: {
        type: "cascading",
        primary: { model: "gpt-4.1" },
        temperature: 0.1,
      },
    },
  });
  const preview = h
    .all()
    .find((node) => node.props?.value === "clipped prompt");
  assert.equal(preview.props.readOnly, true);
  assert(!h.field("general_prompt"));
  h.change("replace_general_prompt", true);
  assert.equal(h.field("general_prompt").props.value, "");
  h.change("general_prompt", "Full replacement written by user");
  await h.submit();
  assert.deepEqual(h.calls[0], [
    "updateRetellLLM",
    {
      llm_id: "l",
      requestBody: { general_prompt: "Full replacement written by user" },
    },
  ]);
  assert(!h.field("begin_message"));
});
test("custom engine remains omitted without explicit replacement; cancel/create-model are separate events", async () => {
  let cancelled = 0,
    created = 0;
  const h = harness({
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
test("prompt replacement can be cancelled and re-enabling never restores a fragment or prior draft", async () => {
  const h = harness({
    kind: "instructions",
    record: {
      llm_id: "l",
      general_prompt: "partial original",
      begin_message: "partial hello",
      model_config: { type: "cascading", primary: { model: "gpt-4.1" } },
    },
  });
  h.change("replace_general_prompt", true);
  h.change("general_prompt", "Draft replacement");
  h.change("replace_general_prompt", false);
  h.change("temperature", "0.2");
  await h.submit();
  assert.deepEqual(h.calls[0][1].requestBody, {
    model_config: { temperature: 0.2 },
  });
  h.change("replace_general_prompt", true);
  assert.equal(h.field("general_prompt").props.value, "");
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
