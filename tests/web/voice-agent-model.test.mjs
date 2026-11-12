import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const source = readFileSync(
  new URL(
    "../../apps/web/components/crm/voice-agent-model.ts",
    import.meta.url,
  ),
  "utf8",
);
const module = { exports: {} };
new Function(
  "require",
  "module",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
)(
  (name) => {
    if (name !== "./voice-schema-model") throw new Error(name);
    const model = { exports: {} };
    new Function(
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
    )(model, model.exports);
    return model.exports;
  },
  module,
  module.exports,
);
const {
  voiceEditorFields,
  voiceInitialValues,
  voiceEditorArguments,
  voiceCatalogOptions,
} = module.exports;
const schemas = JSON.parse(
  readFileSync(
    new URL("../../ops/retell/schemas.json", import.meta.url),
    "utf8",
  ),
);
const build = (kind, record, values, replacements = {}, schema) =>
  voiceEditorArguments(
    kind,
    schema ??
      schemas[
        `${record ? "update" : "create"}${kind === "agent" ? "Agent" : "RetellLLM"}`
      ],
    record,
    values,
    replacements,
  );

test("agent creation uses pinned core fields, composition language enum and actual limits", () => {
  const fields = voiceEditorFields("agent", schemas.createAgent);
  assert(
    fields.find((f) => f.key === "language").schema.enum.includes("es-419"),
  );
  assert(
    !fields.find((f) => f.key === "language").schema.enum.includes("es-CO"),
  );
  assert.equal(fields.find((f) => f.key === "voice_speed").schema.minimum, 0.5);
  assert.deepEqual(
    build("agent", undefined, {
      agent_name: "Sara",
      voice_id: "voice_one",
      llm_id: "llm_one",
      language: "es-419",
      responsiveness: "0",
    }),
    {
      endpoint: "createAgent",
      arguments: {
        requestBody: {
          agent_name: "Sara",
          voice_id: "voice_one",
          language: "es-419",
          responsiveness: 0,
          response_engine: { type: "retell-llm", llm_id: "llm_one" },
        },
      },
    },
  );
  for (const missing of ["agent_name", "voice_id", "llm_id"])
    assert.throws(() =>
      build("agent", undefined, {
        agent_name: "Sara",
        voice_id: "v",
        llm_id: "l",
        [missing]: " ",
      }),
    );
  assert.throws(() =>
    build("agent", undefined, {
      agent_name: "Sara",
      voice_id: "v",
      llm_id: "l",
      voice_speed: "0",
    }),
  );
});
test("edits are minimal, keep identity/version zero and never replay complex engines or unrelated fields", () => {
  for (const type of [
    "custom-llm",
    "conversation-flow",
    "chat",
    "unknown",
    "retell-llm",
  ]) {
    const record = {
      agent_id: "agent_a",
      version: 0,
      agent_name: "Original",
      voice_id: "v",
      response_engine: { type, llm_id: "llm_old", version: 4 },
      webhook_url: "https://invalid.example",
      tools: [{ name: "untouched" }],
    };
    const values = {
      ...voiceInitialValues("agent", record),
      agent_name: "Changed",
      llm_id: "llm_new",
    };
    assert.deepEqual(build("agent", record, values), {
      endpoint: "updateAgent",
      arguments: {
        agent_id: "agent_a",
        version: 0,
        requestBody: { agent_name: "Changed" },
      },
    });
    assert.deepEqual(
      build("agent", record, values, { response_engine: true }).arguments
        .requestBody.response_engine,
      { type: "retell-llm", llm_id: "llm_new" },
    );
  }
  assert.throws(
    () =>
      build("agent", { agent_id: "a", voice_speed: 1 }, { voice_speed: "1.0" }),
    /cambios/i,
  );
});
test("partial instructions and begin message never become editable defaults or implicit patches", () => {
  const record = {
    llm_id: "llm_a",
    version: 3,
    general_prompt: "clipped",
    begin_message: "clipped greeting",
    model_config: {
      type: "cascading",
      primary: { model: "gpt-4.1" },
      temperature: 0,
    },
  };
  const initial = voiceInitialValues("instructions", record);
  assert.equal(initial.general_prompt, "");
  assert.equal(initial.begin_message, "");
  const values = {
    ...initial,
    general_prompt: "replacement",
    begin_message: "new greeting",
    temperature: "0.3",
  };
  assert.deepEqual(build("instructions", record, values).arguments, {
    llm_id: "llm_a",
    version: 3,
    requestBody: { model_config: { temperature: 0.3 } },
  });
  assert.deepEqual(
    build("instructions", record, values, {
      general_prompt: true,
      begin_message: true,
    }).arguments.requestBody,
    {
      general_prompt: "replacement",
      begin_message: "new greeting",
      model_config: { temperature: 0.3 },
    },
  );
  assert.throws(() =>
    build(
      "instructions",
      record,
      { ...initial, general_prompt: "" },
      { general_prompt: true },
    ),
  );
  assert.deepEqual(
    build("instructions", record, initial, { begin_message: true }).arguments
      .requestBody,
    { begin_message: "" },
  );
});
test("instructions model enums and constraints follow the selected pinned model_config branch", () => {
  const fields = voiceEditorFields("instructions", schemas.createRetellLLM);
  assert(fields.find((f) => f.key === "model").schema.enum.includes("gpt-4.1"));
  assert.equal(fields.find((f) => f.key === "temperature").schema.maximum, 1);
  assert.deepEqual(
    build("instructions", undefined, {
      model: "gpt-4.1",
      general_prompt: "Complete instructions",
      temperature: "0",
    }).arguments,
    {
      requestBody: {
        general_prompt: "Complete instructions",
        model_config: {
          type: "cascading",
          primary: { model: "gpt-4.1" },
          temperature: 0,
        },
      },
    },
  );
  assert.throws(() =>
    build("instructions", undefined, {
      model: "fabricated",
      general_prompt: "Full",
    }),
  );
  const record = {
    llm_id: "l",
    general_prompt: "partial",
    model_config: { type: "s2s", primary: { model: "gpt-realtime" } },
  };
  assert(
    voiceEditorFields("instructions", schemas.updateRetellLLM, record)
      .find((f) => f.key === "model")
      .schema.enum.includes("gpt-realtime"),
  );
  assert.deepEqual(
    build("instructions", record, {
      ...voiceInitialValues("instructions", record),
      model: "gpt-realtime-mini",
    }).arguments.requestBody,
    { model_config: { primary: { model: "gpt-realtime-mini" } } },
  );
});
test("malformed catalogue/records and unavailable schemas fail closed without network access", () => {
  assert.deepEqual(
    voiceCatalogOptions(
      [
        null,
        {},
        { voice_id: 5 },
        { voice_id: "v", voice_name: "Voice" },
        { voice_id: "v" },
      ],
      "voice_id",
      "voice_name",
    ),
    [{ value: "v", label: "Voice" }],
  );
  assert.deepEqual(voiceCatalogOptions(null, "llm_id"), []);
  assert.throws(() => build("agent", {}, { agent_name: "Changed" }));
  assert.throws(() =>
    build(
      "agent",
      undefined,
      { agent_name: "A", voice_id: "v", llm_id: "l" },
      {},
      {},
    ),
  );
  assert.throws(() =>
    build(
      "instructions",
      { llm_id: "l", version: NaN },
      { general_prompt: "full" },
      { general_prompt: true },
    ),
  );
});

test("numeric spelling changes are not dirty patches and legacy model edits retain legacy semantics", () => {
  const record = {
    llm_id: "l",
    model_config: {
      type: "cascading",
      primary: { model: "gpt-4.1", tier: "fast" },
      temperature: 0,
    },
  };
  assert.throws(
    () =>
      build("instructions", record, {
        ...voiceInitialValues("instructions", record),
        temperature: "0.0",
      }),
    /cambios/i,
  );
  assert.deepEqual(
    build("instructions", record, {
      ...voiceInitialValues("instructions", record),
      model: "gpt-4.1-mini",
    }).arguments.requestBody,
    { model_config: { primary: { model: "gpt-4.1-mini", tier: "fast" } } },
  );
  const legacy = {
    llm_id: "legacy",
    model: "gpt-4.1",
    backup_model: { model: "gpt-4.1-mini" },
    model_temperature: 0.4,
  };
  assert.deepEqual(
    build("instructions", legacy, {
      ...voiceInitialValues("instructions", legacy),
      model: "gpt-4.1-mini",
    }).arguments.requestBody,
    { model: "gpt-4.1-mini" },
  );
});

test("advanced native drafts extend core forms and explicit complete engines do not force Retell LLM", () => {
  const advanced = {
    response_engine: {
      enabled: true,
      branch: 2,
      children: {
        type: { enabled: true, raw: "conversation-flow" },
        conversation_flow_id: { enabled: true, raw: "flow_1" },
      },
    },
    enable_backchannel: { enabled: true, raw: "false" },
  };
  const created = voiceEditorArguments(
    "agent",
    schemas.createAgent,
    undefined,
    { agent_name: "Flow agent", voice_id: "voice_one" },
    {},
    advanced,
  );
  assert.deepEqual(created.arguments.requestBody.response_engine, {
    type: "conversation-flow",
    conversation_flow_id: "flow_1",
  });
  assert.equal(created.arguments.requestBody.enable_backchannel, false);
  assert.throws(() =>
    voiceEditorArguments(
      "agent",
      schemas.updateAgent,
      { agent_id: "a" },
      {},
      {},
      { unknown_security_override: { enabled: true, raw: "x" } },
    ),
  );
});

test("advanced creation cannot bypass explicit nonempty agent identity or voice", () => {
  for (const key of ["agent_name", "voice_id"]) {
    assert.throws(() =>
      voiceEditorArguments(
        "agent",
        schemas.createAgent,
        undefined,
        { agent_name: "Agent", voice_id: "voice", llm_id: "llm" },
        {},
        { [key]: { enabled: true, raw: "" } },
      ),
    );
  }
});

test("explicit full speech-to-speech model configuration does not require the convenience cascading model", () => {
  const drafts = {
    model_config: {
      enabled: true,
      branch: 1,
      children: {
        type: { enabled: true, raw: "s2s" },
        primary: {
          enabled: true,
          children: { model: { enabled: true, raw: "gpt-realtime" } },
        },
        temperature: { enabled: true, raw: "0.5" },
      },
    },
  };
  const created = voiceEditorArguments(
    "instructions",
    schemas.createRetellLLM,
    undefined,
    { general_prompt: "Complete user instructions" },
    {},
    drafts,
  );
  assert.deepEqual(created.arguments.requestBody, {
    general_prompt: "Complete user instructions",
    model_config: {
      type: "s2s",
      primary: { model: "gpt-realtime" },
      temperature: 0.5,
    },
  });
});
