import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const m = { exports: {} };
new Function(
  "module",
  "exports",
  ts.transpileModule(
    readFileSync(
      new URL(
        "../../apps/web/components/crm/voice-workspace-data.ts",
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
)(m, m.exports);
const { resourceRows, resourceSeed, sections, mergeConfirmed } = m.exports;
test("approved snapshots require current provider revision and merge detail by real identity", () => {
  const snapshots = [
    {
      endpoint: "listAgents",
      provider_revision: 1,
      data: [
        { agent_id: "a", agent_name: "Old" },
        { agent_id: "b", agent_name: "Other" },
      ],
    },
    {
      endpoint: "getAgent",
      provider_revision: 1,
      data: { agent_id: "a", agent_name: "Current" },
    },
  ];
  assert.deepEqual(
    resourceRows(snapshots, sections[0], 1).map((x) => x.agent_name),
    ["Current", "Other"],
  );
  assert.deepEqual(resourceRows(snapshots, sections[0], 2), []);
});
test("malformed inventories and records without real IDs are ignored", () => {
  assert.deepEqual(
    resourceRows(
      [
        {
          endpoint: "listAgents",
          provider_revision: 1,
          data: { items: [null, {}, "x", { agent_id: "a" }] },
        },
      ],
      sections[0],
      1,
    ),
    [{ agent_id: "a" }],
  );
  assert.deepEqual(
    resourceRows(
      [
        {
          endpoint: "listAgents",
          provider_revision: 1,
          data: { error: "unknown" },
        },
      ],
      sections[0],
      1,
    ),
    [],
  );
});
test("resource seeds never resend partial prompts or cached request bodies", () => {
  assert.deepEqual(
    resourceSeed(
      "updateAgent",
      {
        agent_id: "a",
        general_prompt: "partial",
        response_engine: { type: "custom-llm" },
      },
      sections[0],
    ),
    { agent_id: "a", requestBody: {} },
  );
  assert.deepEqual(
    resourceSeed("createWebCall", { agent_id: "a" }, sections[0]),
    { requestBody: { agent_id: "a" } },
  );
});
test("only confirmed Retell results update resources, never uncertain or other providers", () => {
  const old = [];
  for (const result of [
    {
      provider: "elevenlabs",
      status: "completed",
      endpoint: "listAgents",
      data: [],
    },
    {
      provider: "retell",
      status: "external_outcome_unconfirmed",
      endpoint: "listAgents",
      data: [],
    },
  ])
    assert.equal(mergeConfirmed(old, result, 1), old);
  const next = mergeConfirmed(
    old,
    {
      provider: "retell",
      status: "completed",
      endpoint: "createAgent",
      data: { agent_id: "a" },
    },
    1,
  );
  assert.equal(next[0].endpoint, "getAgent");
  assert.equal(next[0].provider_revision, 1);
});
test("a newer list replaces old inventory and supersedes older details", () => {
  const snapshots = [
    {
      endpoint: "getAgent",
      provider_revision: 1,
      created_at: "2026-11-12T08:00:00Z",
      data: { agent_id: "a", agent_name: "stale" },
    },
    {
      endpoint: "listAgents",
      provider_revision: 1,
      created_at: "2026-11-12T09:00:00Z",
      data: [{ agent_id: "a", agent_name: "fresh" }],
    },
    {
      endpoint: "getAgent",
      provider_revision: 1,
      created_at: "2026-11-12T07:00:00Z",
      data: { agent_id: "deleted" },
    },
  ];
  assert.deepEqual(resourceRows(snapshots, sections[0], 1), [
    { agent_id: "a", agent_name: "fresh" },
  ]);
});
