// Server-only runtime configuration; no vendor credentials are returned to browsers.
export function analyticsConfiguration() {
  if (process.env.UMAMI_ENABLED !== "1" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(process.env.UMAMI_WEBSITE_ID || "")) return null;
  try {
    const base = new URL(process.env.UMAMI_BASE_URL || "http://umami:3000");
    const origin = new URL(process.env.CRM_ORIGIN || "");
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password || base.search || base.hash || base.pathname !== "/") return null;
    return { base: base.origin, origin: origin.origin, hostname: origin.hostname, website: process.env.UMAMI_WEBSITE_ID! };
  } catch { return null; }
}
