// Deliberately never include free-form query parameters, link text, or form values.
export const analyticsPaths = ["/", "/lotes-acacias-desde-bogota-soacha"] as const;
export const analyticsEvents = ["page_view", "whatsapp_click", "group_click", "visit_click", "plan_open", "registration_open"] as const;
export const analyticsSources = ["facebook", "instagram", "tiktok", "google", "whatsapp", "direct", "other"] as const;
export type AnalyticsEvent = (typeof analyticsEvents)[number];

export function analyticsContext(path: string, search: string, referrer: string) {
  if (!(analyticsPaths as readonly string[]).includes(path)) return null;
  const aliases: Record<string, string> = { fb: "facebook", facebook: "facebook", ig: "instagram", instagram: "instagram", tiktok: "tiktok", tt: "tiktok", google: "google", whatsapp: "whatsapp", wa: "whatsapp" };
  const utm = new URLSearchParams(search).get("utm_source")?.toLowerCase();
  let source = utm ? aliases[utm] || "other" : "direct";
  if (!utm && referrer) {
    try {
      const host = new URL(referrer).hostname;
      source = "other";
      for (const [domain, value] of [["facebook.com", "facebook"], ["instagram.com", "instagram"], ["tiktok.com", "tiktok"], ["google.com", "google"], ["google.com.co", "google"], ["whatsapp.com", "whatsapp"], ["wa.me", "whatsapp"]]) {
        if (host === domain || host.endsWith(`.${domain}`)) source = value;
      }
      if (host === "jardinesdelencanto.site") source = "direct";
    } catch { source = "other"; }
  }
  return { path, source };
}

export function classifyAnalyticsClick(href: string, capture: boolean): AnalyticsEvent | null {
  if (capture) return "registration_open";
  try {
    const url = new URL(href, "https://jardinesdelencanto.site");
    if (url.hostname === "chat.whatsapp.com") return "group_click";
    if (url.hostname === "wa.me" || url.hostname === "api.whatsapp.com") return "whatsapp_click";
    if (url.hostname === "jardinesdelencanto.site" && url.hash === "#plano") return "plan_open";
  } catch { /* Ignore non-web destinations. */ }
  return null;
}
