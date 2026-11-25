"use client";

import { useEffect, useState } from "react";
import { eventCountdownSeconds, formatEventCountdown } from "../lib/launch-cycle";
import { soachaEvent } from "../lib/soacha-event";
import { LeadCaptureButton } from "./lead-capture";

export function LaunchBanner() {
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => {
    const target = Date.parse(soachaEvent.startsAt);
    const update = () => setRemaining(eventCountdownSeconds(Date.now(), target));
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
        <div className="launch-cycle" data-launch-cycle data-event-start={soachaEvent.startsAt}>
          <span
            className="launch-clock"
            role="timer"
            aria-live="off"
            aria-label={`Tiempo restante para la feria: ${soachaEvent.dateLabel}, 8:00 a. m., hora de Colombia`}
          >
            {remaining === null ? "— : — : —" : remaining === 0 ? "La feria ya comenzó" : formatEventCountdown(remaining)}
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
