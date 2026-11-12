import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
function harness(overrides = {}) {
  let tree,
    cursor = 0;
  const hooks = [];
  const react = {
    useId() {
      cursor++;
      return "native";
    },
    useState(initial) {
      const i = cursor++;
      hooks[i] ??= typeof initial === "function" ? initial() : initial;
      return [
        hooks[i],
        (v) => {
          hooks[i] = typeof v === "function" ? v(hooks[i]) : v;
        },
      ];
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
    const jsx = (type, props) =>
      typeof type === "function" ? type(props) : { type, props };
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
      props.drafts = drafts;
    },
    ...overrides,
  };
  const render = () => {
    cursor = 0;
    tree = VoiceSchemaEditor(props);
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
  const find = (name) => all().find((n) => n.props?.name === name);
  const change = (name, value) => {
    find(name).props.onChange({ target: { value, checked: value } });
    render();
  };
  render();
  return { props, all, find, change, render };
}
test("native section controls edit booleans repeatable lists and nested objects without JSON input", () => {
  const h = harness();
  assert(
    !h
      .all()
      .some((n) => n.type === "textarea" && /json/i.test(n.props?.name ?? "")),
  );
  h.change("enable_backchannel", "true");
  assert.equal(h.props.drafts.enable_backchannel.raw, "true");
  h.change("configure_boosted_keywords", true);
  h.all()
    .find((n) => n.props?.name === "add_boosted_keywords")
    .props.onClick();
  h.render();
  h.change("boosted_keywords.0", "Jardines");
  assert.equal(h.props.drafts.boosted_keywords.items[0].raw, "Jardines");
  h.change("configure_custom_stt_config", true);
  h.change("custom_stt_config.provider", "azure");
  h.change("custom_stt_config.endpointing_ms", "100");
  assert.equal(
    h.props.drafts.custom_stt_config.children.endpointing_ms.raw,
    "100",
  );
});
test("partial complex snapshots cannot prefill replacement; blocked headers cannot collect credentials", () => {
  const h = harness({
    record: { boosted_keywords: ["partial"] },
    schema: {
      properties: {
        boosted_keywords: { type: "array", items: { type: "string" } },
        headers: { type: "object", additionalProperties: { type: "string" } },
      },
    },
  });
  assert(!h.find("boosted_keywords.0"));
  assert(!h.find("configure_headers"));
  h.change("configure_boosted_keywords", true);
  assert.deepEqual(h.props.drafts.boosted_keywords.items, []);
  assert(!h.find("boosted_keywords.0"));
});
test("search filters named sections and union selection resets the full replacement draft", () => {
  const h = harness({
    schema: {
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
    },
  });
  h.change("configure_response_engine", true);
  h.change("response_engine.__variant", "0");
  h.change("response_engine.llm_id", "llm_draft");
  h.change("response_engine.__variant", "1");
  assert(!h.props.drafts.response_engine.children.llm_id);
  h.change("voice_schema_search", "Webhook");
  assert(!h.find("response_engine.__variant"));
  assert(h.find("configure_webhook_url"));
});

test("URLs containing credential material are rejected without retaining their secret in a draft", () => {
  const h = harness();
  h.change("configure_webhook_url", true);
  for (const value of [
    "https://user:password@example.com?api_key=private",
    " https://user:password@example.com/hook",
    "\nhttps://example.com/hook?api_key=private",
    "//user:password@example.com/hook",
  ]) {
    h.change("webhook_url", value);
    assert.equal(h.props.drafts.webhook_url.blocked, true);
    assert.equal(h.props.drafts.webhook_url.raw, undefined);
  }
  assert.equal(h.props.drafts.webhook_url.blocked, true);
  assert.equal(h.props.drafts.webhook_url.raw, undefined);
  assert(h.all().some((node) => node.props?.role === "alert"));
});

test("all pinned top-level fields render a native or explicitly blocked named configuration path", () => {
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
      !h.all().some((node) => node.type === "code" || node.type === "pre"),
    );
  }
});
