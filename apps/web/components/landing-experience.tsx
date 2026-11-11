"use client";

import { useEffect, useState } from "react";
import { dailyCycleSeconds, formatCycle } from "../lib/launch-cycle";
import { LeadCaptureButton } from "./lead-capture";

export function LaunchBanner() {
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => {
    const update = () => setRemaining(dailyCycleSeconds());
    update();
    const interval = window.setInterval(update, 1000);
    document.addEventListener("visibilitychange", update);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);
  return (
    <aside className="launch-banner" aria-label="Precio de lanzamiento">
      <div className="container launch-content">
        <p className="launch-offer">
          <span>Precio de lanzamiento</span>
          <strong>
            Lotes desde $13 millones <small>COP</small>
          </strong>
        </p>
        <div className="launch-cycle" data-launch-cycle>
          <span
            className="launch-clock"
            role="timer"
            aria-live="off"
            aria-label="Contador de 24 horas"
          >
            {remaining === null ? "— : — : —" : formatCycle(remaining)}
          </span>
        </div>
        <LeadCaptureButton className="button button-lime" />
      </div>
    </aside>
  );
}

export function LandingMotion() {
  useEffect(() => {
    const root = document.getElementById("jardines-landing");
    if (
      !root ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      !("IntersectionObserver" in window)
    )
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).dataset.revealed = "true";
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.08 },
    );
    const sections = root.querySelectorAll("[data-reveal]");
    sections.forEach((section) => observer.observe(section));
    root.dataset.motionReady = "true";
    return () => {
      observer.disconnect();
      delete root.dataset.motionReady;
    };
  }, []);
  return null;
}
