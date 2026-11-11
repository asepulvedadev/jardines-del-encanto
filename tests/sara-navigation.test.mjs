import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (p) => readFileSync(new URL("../" + p, import.meta.url), "utf8");
test("Dashboard is first and Sara IA is immediately below it in CRM navigation", () => {
  const types = read("apps/web/components/crm/types.ts"),
    workspace = read("apps/web/components/crm/workspace.tsx");
  assert.match(types, /overview: "Dashboard"/);
  assert.match(types, /sara: "Sara IA"/);
  assert.match(workspace, /\["overview", "home"\],\s*\["sara", "message"\]/);
  assert.match(workspace, /<SaraPanel/);
});
test("Sara skills management opens existing customization settings without duplicating OAuth consumers", () => {
  const workspace = read("apps/web/components/crm/workspace.tsx"),
    settings = read("apps/web/components/crm/settings-modal.tsx");
  assert.match(workspace, /setSettingsTab\("customizations"\)/);
  assert.match(workspace, /initialTab=\{settingsTab\}/);
  assert.match(settings, /initialTab/);
  assert.equal((settings.match(/<SocialPanel/g) || []).length, 1);
});
