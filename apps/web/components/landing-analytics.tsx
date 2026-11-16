"use client";

import { useEffect } from "react";
import { analyticsContext, classifyAnalyticsClick, type AnalyticsEvent } from "../lib/landing-analytics";

export function LandingAnalytics() {
  useEffect(() => {
    const context = analyticsContext(location.pathname, location.search, document.referrer);
    if (!context || navigator.doNotTrack === "1" || (navigator as Navigator & {globalPrivacyControl?: boolean}).globalPrivacyControl) return;
    const controller = new AbortController();
    let enabled = false;
    const send = (event: AnalyticsEvent) => {
      if (!enabled) return;
      // No cookies leave this origin; the collector also excludes logged-in administrators.
      void fetch("/api/landing/analytics", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...context, event}), credentials: "same-origin", keepalive: true,
      }).catch(() => { /* Analytics must never interrupt navigation or lead capture. */ });
    };
    const click = (event: MouseEvent) => {
      if (!(event.target instanceof Element)) return;
      const target = event.target.closest("a,button");
      if (!target) return;
      const name = classifyAnalyticsClick(target.getAttribute("href") || "", target.hasAttribute("data-lead-capture-trigger"));
      if (name) send(name);
    };
    void fetch("/api/landing/analytics/config", { cache: "no-store", signal: controller.signal })
      .then(async response => response.ok && await response.json())
      .then(config => {
        if (controller.signal.aborted || config?.enabled !== true) return;
        enabled = true;
        send("page_view");
        document.addEventListener("click", click);
      }).catch(() => {});
    return () => { enabled = false; controller.abort(); document.removeEventListener("click", click); };
  }, []);
  return null;
}
