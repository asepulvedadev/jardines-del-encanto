import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
function harness(overrides = {}) {
  let tree,
    cursor = 0,
    focused = 0,
    changes = 0;
  const hooks = [],
    effects = [];
  const trigger = {
    isConnected: true,
    focus() {
      focused++;
    },
  };
  const dialog = {
    open: false,
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
    },
  };
  const react = {
    useId() {
      cursor++;
      return "native";
    },
    useState(initial) {
      const i = cursor++;
      if (!(i in hooks))
        hooks[i] = typeof initial === "function" ? initial() : initial;
      return [
        hooks[i],
        (value) => {
          hooks[i] = typeof value === "function" ? value(hooks[i]) : value;
        },
      ];
    },
    useRef(initial) {
      const i = cursor++;
      return (hooks[i] ??= { current: initial });
    },
    useEffect(effect, deps) {
      const i = cursor++;
      const previous = hooks[i];
      if (
        !previous ||
        deps.some((value, n) => !Object.is(value, previous.deps[n]))
      ) {
        hooks[i] = { deps };
        effects.push(() => {
          previous?.cleanup?.();
          hooks[i].cleanup = effect();
        });
      }
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
    const jsx = (type, props) => {
      if (type === "dialog" && props.ref) props.ref.current = dialog;
      return typeof type === "function" ? type(props) : { type, props };
    };
    new Function("require", "module", "exports", code)(
      (name) =>
        name === "react"
          ? react
          : name === "react/jsx-runtime"
            ? { Fragment: "fragment", jsx, jsxs: jsx }
            : name === "./voice-schema-model"
              ? load("voice-schema-model.ts")
              : (() => {
                  throw Error(name);
                })(),
      module,
      module.exports,
    );
    return module.exports;
  };
  const { VoiceSchemaEditor } = load("voice-schema-editor.tsx");
  const props = {
    schema: {
      type: "object",
      properties: {
        enable_backchannel: { type: "boolean" },
        boosted_keywords: { type: "array", items: { type: "string" } },
        webhook_url: { type: "string" },
        custom_stt_config: {
          type: "object",
          properties: {
            provider: { type: "string", enum: ["azure", "deepgram"] },
            endpointing_ms: { type: "integer" },
          },
          required: ["provider", "endpointing_ms"],
        },
      },
    },
    drafts: {},
    onChange: (drafts) => {
      changes++;
      props.drafts = drafts;
    },
    ...overrides,
  };
  const render = () => {
    cursor = 0;
    tree = VoiceSchemaEditor(props);
    while (effects.length) effects.shift()();
    return tree;
  };
  const all = (node = tree) =>
    !node || typeof node !== "object"
      ? []
      : [
          node,
          ...[node.props?.children ?? []]
            .flat(Infinity)
            .flatMap((child) => (child == null ? [] : all(child))),
        ];
  const find = (name) => all().find((node) => node.props?.name === name);
  const change = (name, value) => {
    find(name).props.onChange({ target: { value, checked: value } });
    render();
  };
  const click = (name) => {
    find(name).props.onClick({ currentTarget: trigger });
    render();
  };
  render();
  return {
    props,
    all,
    find,
    change,
    click,
    render,
    dialog,
    focused: () => focused,
    changes: () => changes,
  };
}
test("clean modal rows edit booleans lists and nested objects; apply changes only the local draft", () => {
  const h = harness();
  assert(
    !h
      .all()
      .some((node) => /^(configure_|replace_)/.test(node.props?.name ?? "")),
  );
  h.click("edit_enable_backchannel");
  assert(h.dialog.open);
  h.change("enable_backchannel", "true");
  assert.equal(h.changes(), 0);
  h.click("apply_voice_field");
  assert(!h.dialog.open);
  assert.equal(h.props.drafts.enable_backchannel.raw, "true");
  h.click("edit_boosted_keywords");
  h.click("add_boosted_keywords");
  h.change("boosted_keywords.0", "Jardines");
  h.click("apply_voice_field");
  assert.equal(h.props.drafts.boosted_keywords.items[0].raw, "Jardines");
  h.click("edit_custom_stt_config");
  h.change("custom_stt_config.provider", "azure");
  h.change("custom_stt_config.endpointing_ms", "100");
  h.click("apply_voice_field");
  assert.equal(
    h.props.drafts.custom_stt_config.children.endpointing_ms.raw,
    "100",
  );
});
test("only complete safe snapshots prefill a modal; partial and blocked roots remain read-only", () => {
  const partial = harness({ record: { boosted_keywords: ["partial"] } });
  assert(partial.find("edit_boosted_keywords").props.disabled);
  partial.click("edit_boosted_keywords");
  assert(!partial.dialog.open);
  assert(!partial.find("boosted_keywords.0"));
  const full = harness({
    record: { boosted_keywords: ["Complete"] },
    completeFields: ["boosted_keywords"],
  });
  full.click("edit_boosted_keywords");
  assert.equal(full.find("boosted_keywords.0").props.value, "Complete");
  full.change("boosted_keywords.0", "Temporary");
  full.click("cancel_voice_field");
  assert.deepEqual(full.props.drafts, {});
  full.click("edit_boosted_keywords");
  assert.equal(full.find("boosted_keywords.0").props.value, "Complete");
  const blocked = harness({
    record: { boosted_keywords: ["must not prefill"] },
    completeFields: ["boosted_keywords"],
    blockedFields: { boosted_keywords: "sensitive" },
  });
  blocked.click("edit_boosted_keywords");
  assert(!blocked.dialog.open);
});
test("union changes are isolated until Apply; cancelling reopens the full original branch", () => {
  const schema = {
    properties: {
      response_engine: {
        oneOf: [
          {
            type: "object",
            properties: {
              type: { type: "string", enum: ["retell-llm"] },
              llm_id: { type: "string" },
            },
            required: ["type", "llm_id"],
          },
          {
            type: "object",
            properties: {
              type: { type: "string", enum: ["conversation-flow"] },
              conversation_flow_id: { type: "string" },
            },
            required: ["type", "conversation_flow_id"],
          },
        ],
      },
      webhook_url: { type: "string" },
    },
  };
  const h = harness({
    schema,
    record: { response_engine: { type: "retell-llm", llm_id: "llm_original" } },
    completeFields: ["response_engine", "webhook_url"],
  });
  h.click("edit_response_engine");
  assert.equal(h.find("response_engine.llm_id").props.value, "llm_original");
  h.change("response_engine.__variant", "1");
  assert(!h.find("response_engine.llm_id"));
  h.change("response_engine.conversation_flow_id", "flow_one");
  h.click("cancel_voice_field");
  assert.equal(h.changes(), 0);
  h.click("edit_response_engine");
  assert.equal(h.find("response_engine.__variant").props.value, "0");
  h.change("voice_schema_search", "Webhook");
  assert(!h.find("edit_response_engine"));
  assert(h.find("edit_webhook_url"));
});
test("credential-bearing URL input is not retained and cannot be applied to the parent draft", () => {
  const h = harness();
  h.click("edit_webhook_url");
  h.change("webhook_url", " https://user:password@example.com?api_key=private");
  assert.equal(h.find("webhook_url").props.value, "");
  h.click("apply_voice_field");
  assert(h.dialog.open);
  assert.equal(h.changes(), 0);
  assert(h.all().some((node) => node.props?.role === "alert"));
});
test("all pinned root fields retain named rows, without JSON or configure checkbox ceremony", () => {
  const schemas = JSON.parse(
    readFileSync(
      new URL("../../ops/retell/schemas.json", import.meta.url),
      "utf8",
    ),
  );
  for (const [endpoint, count] of Object.entries({
    createAgent: 60,
    updateAgent: 59,
    createRetellLLM: 20,
    updateRetellLLM: 20,
  })) {
    const h = harness({ schema: schemas[endpoint] });
    assert.equal(
      h.all().filter((node) => node.props?.["data-voice-field"]).length,
      count,
      endpoint,
    );
    assert(
      !h
        .all()
        .some(
          (node) =>
            node.type === "code" ||
            node.type === "pre" ||
            (node.type === "input" && node.props.type === "checkbox"),
        ),
    );
  }
});
test("child Escape cancels locally and restores the opener without bubbling to its ancestor", () => {
  const h = harness();
  h.click("edit_webhook_url");
  h.change("webhook_url", "https://safe.example.com");
  let prevented = 0,
    stopped = 0;
  h.all()
    .find((node) => node.type === "dialog")
    .props.onCancel({
      preventDefault() {
        prevented++;
      },
      stopPropagation() {
        stopped++;
      },
    });
  h.render();
  assert.equal(prevented, 1);
  assert.equal(stopped, 1);
  assert.equal(h.focused(), 1);
  assert(!h.dialog.open);
  assert.equal(h.changes(), 0);
});
test("untouched complete modal values are omitted; known-absent roots do not become implicit empty writes", () => {
  const h = harness({
    record: { boosted_keywords: ["Complete"] },
    completeFields: ["boosted_keywords", "webhook_url"],
  });
  h.click("edit_webhook_url");
  h.click("apply_voice_field");
  assert.equal(h.changes(), 0);
  h.click("edit_boosted_keywords");
  h.change("boosted_keywords.0", "Complete");
  h.click("apply_voice_field");
  assert.equal(h.props.drafts.boosted_keywords.enabled, false);
});
test("required validation and pending locks keep the child modal open without mutating the parent", () => {
  const h = harness();
  h.click("edit_custom_stt_config");
  h.change("custom_stt_config.provider", "azure");
  h.click("apply_voice_field");
  assert(h.dialog.open);
  assert.equal(h.changes(), 0);
  h.props.disabled = true;
  h.render();
  h.click("cancel_voice_field");
  assert(h.dialog.open);
  h.click("apply_voice_field");
  assert(h.dialog.open);
  assert.equal(h.changes(), 0);
});

test("Enter in a field modal input prevents implicit parent form submission; textarea keeps newline", () => {
  const h = harness();
  h.click("edit_webhook_url");
  const handler = h.all().find((node) => node.type === "dialog")
    .props.onKeyDown;
  let prevented = 0,
    stopped = 0,
    proposals = 0;
  handler({
    key: "Enter",
    target: { tagName: "INPUT" },
    preventDefault() {
      prevented++;
    },
    stopPropagation() {
      stopped++;
    },
  });
  if (!prevented) proposals++;
  assert.equal(prevented, 1);
  assert.equal(stopped, 1);
  assert.equal(proposals, 0);
  handler({
    key: "Enter",
    target: { tagName: "TEXTAREA" },
    preventDefault() {
      prevented++;
    },
    stopPropagation() {
      stopped++;
    },
  });
  assert.equal(prevented, 1);
  assert.equal(stopped, 2);
  assert.equal(h.changes(), 0);
});
