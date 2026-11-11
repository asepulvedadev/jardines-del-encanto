"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import "../app/hero-experience.css";

const Masterplan = dynamic(() => import("./hero-masterplan"), {
  loading: () => (
    <p className="hero-world-loading" role="status">
      Preparando la maqueta…
    </p>
  ),
});

export function HeroExperience() {
  const [mode, setMode] = useState<"film" | "plan">("film");
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const planToggle = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const element = video.current;
    if (!element || mode !== "film") return;
    const motion = window.matchMedia(
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
    if (motion.matches && !constrained && !document.hidden)
      void element.play().catch(() => {});
    const pause = () => element.pause();
    const visibility = () => {
      if (document.hidden) pause();
    };
    const preference = () => {
      if (!motion.matches) pause();
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) pause();
      },
      { threshold: 0.05 },
    );
    observer.observe(element);
    document.addEventListener("visibilitychange", visibility);
    motion.addEventListener("change", preference);
    return () => {
      pause();
      observer.disconnect();
      document.removeEventListener("visibilitychange", visibility);
      motion.removeEventListener("change", preference);
    };
  }, [mode]);

  function changeMode(next: "film" | "plan") {
    video.current?.pause();
    setMode(next);
    if (next === "plan") planToggle.current?.focus({ preventScroll: true });
  }

  function toggleFilm() {
    const element = video.current;
    if (!element) return;
    if (!element.paused) element.pause();
    else
      void element.play().catch((error: unknown) => {
        // Pausing or changing views can abort an otherwise healthy play request.
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        setFailed(true);
      });
  }

  return (
    <figure
      className="hero-experience"
      data-hero-experience
      aria-label="Vistas del proyecto"
    >
      <div className="hero-world" data-view={mode}>
        <div
          className="hero-world-switch"
          role="group"
          aria-label="Vista del proyecto"
        >
          <button
            type="button"
            aria-pressed={mode === "film"}
            onClick={() => changeMode("film")}
          >
            <span aria-hidden="true">▷</span> Recorrido
          </button>
          <button
            ref={planToggle}
            type="button"
            aria-pressed={mode === "plan"}
            onClick={() => changeMode("plan")}
          >
            Maqueta 3D
          </button>
        </div>
        {mode === "film" ? (
          <div className="hero-cinema" data-hero-film>
            <video
              ref={video}
              muted
              playsInline
              loop
              preload="none"
              poster="/media/hero-poster.webp"
              width={848}
              height={478}
              aria-label="Recorrido arquitectónico ilustrativo de Jardines del Encanto"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onError={() => {
                setFailed(true);
                setPlaying(false);
              }}
            >
              <source
                src="/media/hero-loop.mp4"
                type="video/mp4"
                onError={() => setFailed(true)}
              />
              Tu navegador no puede reproducir el recorrido. Puedes explorar el
              plano.
            </video>
            <button
              className="hero-film-control"
              type="button"
              onClick={toggleFilm}
              aria-label={playing ? "Pausar recorrido" : "Reproducir recorrido"}
              disabled={failed}
            >
              <span aria-hidden="true">{playing ? "Ⅱ" : "▷"}</span>
            </button>
            {failed && (
              <p className="hero-cinema-error" role="status">
                El video no está disponible. Explora la maqueta o el plano.
              </p>
            )}
          </div>
        ) : (
          <Masterplan />
        )}
      </div>
      <figcaption className="hero-experience-caption">
        <div>
          <p>
            {mode === "film"
              ? "Visualización arquitectónica. Video ilustrativo: no representa el estado actual de obra."
              : "Maqueta conceptual basada en el plano. Alturas ilustrativas, sin topografía ni disponibilidad en tiempo real."}
          </p>
        </div>
        <a href="#plano" aria-label="Ver el plano original y sus medidas">
          Ver plano <span aria-hidden="true">↗</span>
        </a>
      </figcaption>
      <span className="sr-only">
        Maqueta conceptual disponible por elección del visitante.
      </span>
    </figure>
  );
}
