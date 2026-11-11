import assert from "node:assert/strict";
import { test } from "node:test";
import {
  dailyCycleSeconds,
  formatCycle,
} from "../apps/web/lib/launch-cycle.ts";

test("the public daily timer repeats at midnight in Colombia for every visitor", () => {
  assert.equal(dailyCycleSeconds(Date.parse("2026-11-11T05:00:00Z")), 86400);
  assert.equal(dailyCycleSeconds(Date.parse("2026-11-12T04:59:59Z")), 1);
  assert.equal(dailyCycleSeconds(Date.parse("2026-11-12T05:00:00Z")), 86400);
  assert.equal(dailyCycleSeconds(Date.parse("2026-11-12T17:00:00Z")), 43200);
  assert.equal(formatCycle(86400), "24:00:00");
  assert.equal(formatCycle(1), "00:00:01");
  for (let hour = 0; hour < 48; hour++) {
    const seconds = dailyCycleSeconds(
      Date.parse("2026-11-11T00:00:00Z") + hour * 3600000,
    );
    assert.ok(seconds >= 1 && seconds <= 86400);
  }
});
