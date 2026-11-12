import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const module = { exports: {} };
const source = readFileSync(
  new URL("../../apps/web/components/crm/retell-schema.tsx", import.meta.url),
  "utf8",
);
new Function(
  "require",
  "module",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
)(
  (s) => {
    throw new Error(s);
  },
  module,
  module.exports,
);
const {
  retellFields,
  retellArguments,
  retellInitialArguments,
  retellOutbound,
} = module.exports;
const schema = {
  type: "object",
  required: ["agent_id", "requestBody"],
  properties: {
    agent_id: { type: "string" },
    limit: { type: "integer", minimum: 1, maximum: 10 },
    requestBody: {
      type: "object",
      required: ["message"],
      properties: {
        message: { type: "string", minLength: 2 },
        active: { type: "boolean" },
        metadata: { type: "object" },
      },
    },
  },
};
test("schema fields preserve parameter location and flag complex inputs", () => {
  assert.deepEqual(
    retellFields(schema).map((f) => [f.path, f.required, f.type]),
    [
      ["agent_id", true, "string"],
      ["limit", false, "integer"],
      ["requestBody.message", true, "string"],
      ["requestBody.active", false, "boolean"],
    ],
  );
});
test("guided values retain optional omissions and validate primitives", () => {
  assert.deepEqual(
    retellArguments(schema, {
      agent_id: "a",
      "requestBody.message": "hi",
      "requestBody.active": "false",
    }),
    { agent_id: "a", requestBody: { message: "hi", active: false } },
  );
  assert.throws(
    () =>
      retellArguments(schema, {
        agent_id: "a",
        limit: "11",
        "requestBody.message": "hi",
      }),
    /limit/,
  );
  assert.throws(
    () =>
      retellArguments(schema, { agent_id: "a", "requestBody.message": "x" }),
    /message/,
  );
  assert.throws(
    () => retellArguments(schema, { "requestBody.message": "hi" }),
    /agent_id/,
  );
});
test("advanced JSON rejects nonobjects, dangerous keys and oversized drafts", () => {
  assert.deepEqual(
    retellArguments(
      schema,
      {},
      '{"agent_id":"a","requestBody":{"message":"hi","metadata":{"ok":true}}}',
    ),
    { agent_id: "a", requestBody: { message: "hi", metadata: { ok: true } } },
  );
  for (const json of [
    "[]",
    "null",
    '{"__proto__":{}}',
    '{"requestBody":{"constructor":{}}}',
    "x".repeat(33000),
  ])
    assert.throws(() => retellArguments(schema, {}, json));
});
test("defaults only populate fields that exist and outbound stays exact", () => {
  assert.deepEqual(
    retellInitialArguments(schema, {
      agent_id: "a",
      chat_agent_id: "b",
      from_number: "+15555555555",
    }),
    { agent_id: "a" },
  );
  assert.equal(retellOutbound("createPhoneCall"), true);
  assert.equal(retellOutbound("createSmsChat"), true);
  assert.equal(retellOutbound("getCall"), false);
});
