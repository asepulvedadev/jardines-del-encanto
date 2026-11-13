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
const modules = {};
function load(name) {
  if (modules[name]) return modules[name];
  const m = { exports: {} };
  const source = readFileSync(
    new URL(`../../apps/web/components/crm/${name}.ts`, import.meta.url),
    "utf8",
  );
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
  )((path) => load(path.slice(2)), m, m.exports);
  return (modules[name] = m.exports);
}
const { studioGroups, studioChanges, studioTestArguments } = load(
  "voice-agent-studio-model",
);
const snapshot = (kind, data) => ({
  data,
  completeFields: Object.keys(
    load("voice-schema-model").voiceSchemaProperties(
      load("voice-schema-model").voiceSchemaProperties(
        schemas[kind === "agent" ? "updateAgent" : "updateRetellLLM"],
      ).requestBody,
    ),
  ),
  blockedFields: {},
});
const agent = snapshot("agent", {
  agent_id: "agent_local",
  version: 0,
  agent_name: "Sara",
  voice_id: "voice_local",
  language: "es-419",
  response_engine: { type: "retell-llm", llm_id: "llm_local", version: 0 },
});
const llm = snapshot("instructions", {
  llm_id: "llm_local",
  version: 0,
  general_prompt: "Full prompt",
  begin_message: "Hello",
  model: "gpt-4.1",
});
test("all pinned editable roots occur once in the studio groups or toolbar", () => {
  for (const [kind, endpoint] of [
    ["agent", "updateAgent"],
    ["instructions", "updateRetellLLM"],
  ]) {
    const keys = studioGroups.flatMap((g) => g[kind]);
    assert.equal(new Set(keys).size, keys.length);
    assert.deepEqual(
      [...keys].sort(),
      [...snapshot(kind, {}).completeFields].sort(),
    );
  }
});
test("studio keeps two exact records independent and omits unchanged drafts", () => {
  assert.deepEqual(studioChanges(schemas, agent, llm, {}, {}), []);
  const changes = studioChanges(
    schemas,
    agent,
    llm,
    { voice_speed: { enabled: true, raw: "1.2" } },
    { general_prompt: { enabled: true, raw: "Changed full prompt" } },
  );
  assert.deepEqual(
    changes.map((x) => x.endpoint),
    ["updateAgent", "updateRetellLLM"],
  );
  assert.deepEqual(changes[0].arguments, {
    agent_id: "agent_local",
    version: 0,
    requestBody: { voice_speed: 1.2 },
  });
  assert.deepEqual(changes[1].arguments, {
    llm_id: "llm_local",
    version: 0,
    requestBody: { general_prompt: "Changed full prompt" },
  });
  assert.deepEqual(
    studioChanges(
      schemas,
      agent,
      llm,
      {},
      { general_prompt: { enabled: true, raw: "Full prompt" } },
    ),
    [],
  );
});
test("blocked or missing LLM data never falls back to inventory or changes engines", () => {
  const blocked = {
    ...llm,
    blockedFields: { general_prompt: "editor_field_private" },
  };
  assert.throws(() =>
    studioChanges(
      schemas,
      agent,
      blocked,
      {},
      { general_prompt: { enabled: true, raw: "replacement" } },
    ),
  );
  assert.throws(() =>
    studioChanges(
      schemas,
      agent,
      undefined,
      {},
      { general_prompt: { enabled: true, raw: "replacement" } },
    ),
  );
  const changes = studioChanges(
    schemas,
    agent,
    undefined,
    { voice_speed: { enabled: true, raw: "1.1" } },
    {},
  );
  assert(!("response_engine" in changes[0].arguments.requestBody));
});
test("test seeds use saved agent/version, never silently include unsaved overrides", () => {
  assert.deepEqual(studioTestArguments("audio", agent.data), {
    requestBody: { agent_id: "agent_local", agent_version: 0 },
  });
  assert.deepEqual(studioTestArguments("llm", agent.data, "Hello"), {
    agent_id: "agent_local",
    version: 0,
    requestBody: { messages: [{ role: "user", content: "Hello" }] },
  });
  assert.throws(() => studioTestArguments("llm", agent.data, "   "));
});
test("engine rebinding cannot silently combine with edits to the previously linked instructions", () => {
  const model = load("voice-schema-model");
  const hydrated = model.voiceHydrateField(
    model.voiceSchemaProperties(schemas.updateAgent).requestBody,
    "response_engine",
    {
      ...agent.data,
      response_engine: { type: "retell-llm", llm_id: "different_llm" },
    },
    agent.completeFields,
    {},
  );
  assert(hydrated.editable);
  assert.throws(
    () =>
      studioChanges(
        schemas,
        agent,
        llm,
        { response_engine: hydrated.draft },
        { general_prompt: { enabled: true, raw: "Changed old instructions" } },
      ),
    /motor/,
  );
});
