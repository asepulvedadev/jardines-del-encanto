"use client";

import { useEffect, useRef, useState } from "react";
import { dailyCycleSeconds, formatCycle } from "../lib/launch-cycle";
import { whatsappLink } from "../lib/project";

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
        <a
          className="button button-lime"
          href={whatsappLink(
            "Hola, quiero mi cupo para conocer Jardines del Encanto. Me interesa el precio de lanzamiento desde $13 millones COP.",
          )}
          target="_blank"
          rel="noopener noreferrer"
        >
          Quiero mi cupo <span aria-hidden="true">↗</span>
          <span className="sr-only"> (abre WhatsApp en otra pestaña)</span>
        </a>
      </div>
    </aside>
  );
}

export function HeroFilm() {
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const element = video.current;
    if (!element) return;
    const media = window.matchMedia(
      "(min-width: 1024px) and (prefers-reduced-motion: no-preference)",
    );
    const connection = (
      navigator as Navigator & {
        connection?: { saveData?: boolean; effectiveType?: string };
      }
    ).connection;
    const constrained =
      connection?.saveData ||
      ["slow-2g", "2g", "3g"].includes(connection?.effectiveType ?? "");
    if (media.matches && !constrained && document.visibilityState === "visible")
      void element.play().catch(() => {
        /* Native controls remain available when autoplay is blocked. */
      });
    const observer =
      "IntersectionObserver" in window
        ? new IntersectionObserver(
            ([entry]) => {
              if (!entry.isIntersecting) element.pause();
            },
            { threshold: 0.05 },
          )
        : null;
    observer?.observe(element);
    const pauseHidden = () => {
      if (document.hidden) element.pause();
    };
    const reduceMotion = () => {
      if (!media.matches) element.pause();
    };
    document.addEventListener("visibilitychange", pauseHidden);
    media.addEventListener("change", reduceMotion);
    return () => {
      observer?.disconnect();
      element.pause();
      document.removeEventListener("visibilitychange", pauseHidden);
      media.removeEventListener("change", reduceMotion);
    };
  }, []);
  return (
    <figure className="hero-film" data-hero-film>
      <div className="hero-film-frame">
        <video
          ref={video}
          controls
          muted
          playsInline
          loop
          preload="none"
          poster="/media/film-poster.webp"
          width={848}
          height={478}
          aria-label="Recorrido arquitectónico de Jardines del Encanto"
          onError={() => setFailed(true)}
        >
          <source
            src="/media/recorrido-arquitectonico.mp4"
            type="video/mp4"
            onError={() => setFailed(true)}
          />
          Tu navegador no puede reproducir este video.
        </video>
        <span className="hero-film-badge">
          RECORRIDO DEL PROYECTO <span aria-hidden="true">↗</span>
        </span>
      </div>
      <figcaption>
        <strong>Una mirada a lo que viene.</strong>
        <span>
          Visualización arquitectónica. Video ilustrativo: no representa el
          estado actual de obra.
        </span>
      </figcaption>
      {failed && (
        <p className="hero-film-error" role="alert">
          No pudimos cargar el recorrido. Puedes ver las fotografías reales del
          proyecto más abajo.
        </p>
      )}
    </figure>
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
