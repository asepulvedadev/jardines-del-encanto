/** A transparent calendar cycle, not an offer deadline or stock reservation. */
export const CYCLE_SECONDS = 24 * 60 * 60;
const COLOMBIA_OFFSET_MS = -5 * 60 * 60 * 1000;

export function dailyCycleSeconds(now: number = Date.now()): number {
  const day = CYCLE_SECONDS * 1000;
  const elapsed = (((now + COLOMBIA_OFFSET_MS) % day) + day) % day;
  return Math.max(1, Math.ceil((day - elapsed) / 1000));
}

export function formatCycle(seconds: number): string {
  return [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  ]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}
