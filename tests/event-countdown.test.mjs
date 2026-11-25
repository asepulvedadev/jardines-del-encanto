import assert from "node:assert/strict";
import { test } from "node:test";
import { soachaEvent } from "../apps/web/lib/soacha-event.ts";
import { eventCountdownSeconds, formatEventCountdown } from "../apps/web/lib/launch-cycle.ts";

test("the campaign event preserves its venue and starts November 29 at 8am in Colombia", () => {
  assert.equal(soachaEvent.date, "2026-11-29");
  assert.equal(soachaEvent.startsAt, "2026-11-29T08:00:00-05:00");
  assert.equal(soachaEvent.dateLabel, "Domingo 29 de noviembre de 2026");
  assert.equal(soachaEvent.venue, "Cámara de Comercio de Bogotá en Soacha");
  assert.match(soachaEvent.message, /domingo 29 de noviembre de 2026/);
});

test("the event clock counts down across midnight, stops at zero and never restarts", () => {
  const target = Date.parse(soachaEvent.startsAt);
  assert.equal(eventCountdownSeconds(Date.parse("2026-11-28T04:59:59Z"), target), 115201);
  assert.equal(eventCountdownSeconds(Date.parse("2026-11-28T05:00:00Z"), target), 115200);
  assert.equal(eventCountdownSeconds(target - 1000, target), 1);
  assert.equal(eventCountdownSeconds(target, target), 0);
  assert.equal(eventCountdownSeconds(target + 86400000, target), 0);
  assert.equal(formatEventCountdown(115201), "1 d · 08:00:01");
  assert.equal(formatEventCountdown(1), "00:00:01");
  assert.equal(formatEventCountdown(0), "00:00:00");
});
