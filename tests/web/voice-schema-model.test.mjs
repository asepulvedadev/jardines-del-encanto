import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const module = { exports: {} };
const source = readFileSync(
  new URL(
    "../../apps/web/components/crm/voice-schema-model.ts",
    import.meta.url,
  ),
  "utf8",
);
new Function(
  "module",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
)(module, module.exports);
const {
  voiceSchemaProperties,
  voiceSchemaInventory,
  voiceSchemaPatch,
  voiceEmptyDraft,
  voiceSchemaVariants,
  voiceSensitivePath,
} = module.exports;
const schemas = JSON.parse(
  readFileSync(
    new URL("../../ops/retell/schemas.json", import.meta.url),
    "utf8",
  ),
);
const scalar = (raw) => ({ enabled: true, raw });
const obj = (children) => ({ enabled: true, children });
const arr = (items) => ({ enabled: true, items });
const body = (endpoint) => voiceSchemaProperties(schemas[endpoint]).requestBody;
test("every pinned editable property has a guided or native inventory path", () => {
  for (const [endpoint, expected] of Object.entries({
    createAgent: 60,
    updateAgent: 59,
    createRetellLLM: 20,
    updateRetellLLM: 20,
  })) {
    const inventory = voiceSchemaInventory(schemas[endpoint]);
    assert.equal(inventory.length, expected, endpoint);
    assert(
      inventory.every(
        (entry) =>
          entry.label &&
          entry.section &&
          ["native", "blocked"].includes(entry.support),
      ),
    );
    assert.deepEqual(
      inventory.map((entry) => entry.key).sort(),
      Object.keys(voiceSchemaProperties(body(endpoint))).sort(),
    );
  }
});
test("schema patches parse booleans numbers enums nullable objects arrays and discriminated unions", () => {
  const schema = body("updateAgent");
  const variants = voiceSchemaVariants(
    voiceSchemaProperties(schema).response_engine,
  );
  const branch = variants.findIndex((v) =>
    voiceSchemaProperties(v).type.enum.includes("conversation-flow"),
  );
  assert.deepEqual(
    voiceSchemaPatch(schema, {
      enable_backchannel: scalar("false"),
      voice_speed: scalar("1.25"),
      fallback_voice_ids: arr([scalar("voice_one"), scalar("voice_two")]),
      call_screening_option: { enabled: true, null: true },
      response_engine: {
        ...obj({
          type: scalar("conversation-flow"),
          conversation_flow_id: scalar("flow_one"),
        }),
        branch,
      },
    }),
    {
      enable_backchannel: false,
      voice_speed: 1.25,
      fallback_voice_ids: ["voice_one", "voice_two"],
      call_screening_option: null,
      response_engine: {
        type: "conversation-flow",
        conversation_flow_id: "flow_one",
      },
    },
  );
});
test("omitted/unchanged primitives stay omitted and complex drafts never copy a partial snapshot", () => {
  const schema = body("updateAgent");
  const record = {
    voice_speed: 1,
    enable_backchannel: false,
    boosted_keywords: ["partial"],
  };
  assert.deepEqual(
    voiceSchemaPatch(
      schema,
      {
        voice_speed: scalar("1.0"),
        enable_backchannel: scalar("false"),
        boosted_keywords: { enabled: false, items: [scalar("partial")] },
      },
      record,
    ),
    {},
  );
  assert.deepEqual(
    voiceSchemaPatch(
      schema,
      { boosted_keywords: arr([scalar("complete")]) },
      record,
    ),
    { boosted_keywords: ["complete"] },
  );
  assert.deepEqual(
    voiceEmptyDraft(voiceSchemaProperties(schema).boosted_keywords).items,
    [],
  );
});
test("required enum range and union validation reject incomplete replacement data", () => {
  const schema = body("updateAgent");
  assert.throws(
    () => voiceSchemaPatch(schema, { voice_speed: scalar("0.1") }),
    /velocidad|voice_speed/i,
  );
  assert.throws(() =>
    voiceSchemaPatch(schema, { denoising_mode: scalar("fake") }),
  );
  assert.throws(() => voiceSchemaPatch(schema, { response_engine: obj({}) }));
  assert.throws(() =>
    voiceSchemaPatch(schema, {
      pronunciation_dictionary: arr([obj({ word: scalar("Name") })]),
    }),
  );
});
test("sensitive declared/dynamic fields and credentials hidden in URLs fail closed", () => {
  for (const path of [
    "headers",
    "tools.0.authorization",
    "custom_sip_headers",
    "api-key",
    "credentials",
    "accessToken",
  ])
    assert(voiceSensitivePath(path), path);
  const schema = {
    type: "object",
    properties: {
      mcps: {
        type: "array",
        items: {
          type: "object",
          properties: {
            url: { type: "string" },
            headers: {
              type: "object",
              additionalProperties: { type: "string" },
            },
            query_params: {
              type: "object",
              additionalProperties: { type: "string" },
            },
          },
        },
      },
    },
  };
  assert.throws(() =>
    voiceSchemaPatch(schema, {
      mcps: arr([obj({ headers: obj({ Authorization: scalar("secret") }) })]),
    }),
  );
  assert.throws(() =>
    voiceSchemaPatch(schema, {
      mcps: arr([obj({ url: scalar("https://user:password@example.com") })]),
    }),
  );
  assert.throws(() =>
    voiceSchemaPatch(schema, {
      mcps: arr([
        obj({
          query_params: {
            enabled: true,
            entries: [{ key: "api_key", draft: scalar("secret") }],
          },
        }),
      ]),
    }),
  );
  assert.throws(() =>
    voiceSchemaPatch(schema, { unknown_security_override: scalar("value") }),
  );
});

test("actual webhook schema rejects private URLs after URL parser whitespace normalization", () => {
  for (const value of [
    " https://user:password@example.com/hook",
    "\nhttps://example.com/hook?api_key=private",
    "ht\ttps://example.com/hook?access_token=private",
    "//user:password@example.com/hook",
    "https:user:password@example.com/hook",
  ]) {
    assert.throws(
      () =>
        voiceSchemaPatch(body("updateAgent"), { webhook_url: scalar(value) }),
      /credenciales/,
    );
  }
  assert.deepEqual(
    voiceSchemaPatch(body("updateAgent"), {
      webhook_url: scalar("https://example.com/hook"),
    }),
    { webhook_url: "https://example.com/hook" },
  );
});
