import { createHash } from "node:crypto";
import { isIP } from "node:net";
import { analyticsConfiguration } from "../../../../lib/analytics-config";
import { analyticsEvents, analyticsPaths, analyticsSources } from "../../../../lib/landing-analytics";

const headers = { "Cache-Control": "no-store, private" };
const empty = () => new Response(null, { status: 204, headers });
const fail = (status: number, detail: string) => Response.json({ detail }, { status, headers });
// Best-effort per-process abuse budget, not a billing/security identity guarantee.
let minute = 0;
let total = 0;
const limits = new Map<string, number>();
function limited(key: string) {
  const now = Math.floor(Date.now() / 60000);
  if (now !== minute) { minute = now; total = 0; limits.clear(); }
  const count = (limits.get(key) || 0) + 1;
  if (++total > 2000 || count > 120) return true;
  limits.set(key, count);
  return false;
}

export async function POST(request: Request) {
  if (!process.env.CRM_ORIGIN || request.headers.get("origin") !== process.env.CRM_ORIGIN) return fail(403, "invalid_origin");
  if (new URL(request.url).search) return fail(422, "invalid_input");
  if (request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") return fail(415, "invalid_content_type");
  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.length;
    if (size > 1024) { await reader.cancel(); return fail(413, "request_too_large"); }
    chunks.push(value);
  }
  let input;
  try {
    input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!input || Array.isArray(input) || Object.keys(input).sort().join(",") !== "event,path,source" || !(analyticsEvents as readonly unknown[]).includes(input.event) || !(analyticsPaths as readonly unknown[]).includes(input.path) || !(analyticsSources as readonly unknown[]).includes(input.source)) throw Error();
  } catch { return fail(422, "invalid_input"); }
  const config = analyticsConfiguration();
  if (!config) return empty();
  const ua = request.headers.get("user-agent") || "";
  if (request.headers.get("DNT") === "1" || request.headers.get("Sec-GPC") === "1" || /(?:^|;\s*)(?:__Host-)?jardines_session=/.test(request.headers.get("cookie") || "") || /bot|crawler|spider|headless/i.test(ua) || !ua || ua.length > 512) return empty();
  // Only enable behind the installed loopback-only Nginx policy, which overwrites this header.
  const ip = process.env.UMAMI_TRUST_PROXY === "1" ? request.headers.get("x-real-ip") || "" : "";
  if (process.env.UMAMI_TRUST_PROXY === "1" && !isIP(ip)) return empty();
  const key = createHash("sha256").update(ip + ua).digest("hex");
  if (limited(key)) return fail(429, "analytics_throttled");
  const payload: Record<string, string> = {
    website: config.website, hostname: config.hostname,
    url: `${input.path}?utm_source=${input.source}`,
    title: input.path === "/" ? "Jardines del Encanto" : "Guía para compradores",
  };
  if (input.event !== "page_view") payload.name = input.event;
  try {
    const upstream = await fetch(`${config.base}/api/send`, {
      method: "POST", headers: { "Content-Type": "application/json", "User-Agent": ua, ...(ip ? { "X-Forwarded-For": ip } : {}) },
      body: JSON.stringify({ type: "event", payload }),
      credentials: "omit", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(2500),
    });
    await upstream.body?.cancel();
    return upstream.ok ? empty() : fail(503, "analytics_unavailable");
  } catch { return fail(503, "analytics_unavailable"); }
}
