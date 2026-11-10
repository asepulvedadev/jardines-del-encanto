"use client";
import { useRef, useState } from "react";
import { photographs } from "../lib/project";
import { ProjectPhoto } from "./project-photo";

const navigation = [
  ["El proyecto", "#proyecto"],
  ["Espacios", "#espacios"],
  ["Plano", "#plano"],
  ["Preguntas", "#preguntas"],
] as const;

export function MobileNavigation() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <div
      className="mobile-navigation"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        className="menu-toggle"
        aria-expanded={open}
        aria-controls="mobile-links"
        onClick={() => setOpen(!open)}
      >
        {open ? "Cerrar" : "Menú"}{" "}
        <span aria-hidden="true">{open ? "×" : "+"}</span>
      </button>
      {open && (
        <nav id="mobile-links" aria-label="Navegación móvil">
          {navigation.map(([label, href]) => (
            <a href={href} key={href} onClick={() => setOpen(false)}>
              {label}
              <span aria-hidden="true">↗</span>
            </a>
          ))}
        </nav>
      )}
    </div>
  );
}

export function PhotoGallery() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [index, setIndex] = useState(0);
  const selected = photographs[index];
  const move = (direction: number) =>
    setIndex(
      (current) =>
        (current + direction + photographs.length) % photographs.length,
    );
  return (
    <>
      <div className="photo-grid">
        {photographs.map((photo, i) => (
          <button
            className={`photo-tile photo-tile-${i}`}
            key={photo.name}
            aria-label={`Ampliar fotografía: ${photo.title}`}
            onClick={() => {
              setIndex(i);
              dialog.current?.showModal();
            }}
          >
            <ProjectPhoto
              name={photo.name}
              alt={photo.alt}
              sizes="(max-width: 767px) 100vw, (max-width: 1279px) 50vw, 640px"
            />
            <span className="photo-caption">
              <span>{photo.title}</span>
              <span aria-hidden="true">↗</span>
            </span>
          </button>
        ))}
      </div>
      <dialog
        className="media-dialog"
        ref={dialog}
        aria-labelledby="photo-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) dialog.current?.close();
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowRight") move(1);
          if (event.key === "ArrowLeft") move(-1);
        }}
      >
        <div className="dialog-toolbar">
          <h2 id="photo-title">{selected.title}</h2>
          <button
            className="dialog-close"
            autoFocus
            onClick={() => dialog.current?.close()}
            aria-label="Cerrar fotografía"
          >
            Cerrar <span aria-hidden="true">×</span>
          </button>
        </div>
        <ProjectPhoto
          name={selected.name}
          alt={selected.alt}
          className="expanded-photo"
          eager
        />
        <div className="gallery-controls">
          <button onClick={() => move(-1)} aria-label="Fotografía anterior">
            ← <span>Anterior</span>
          </button>
          <span aria-live="polite">
            {index + 1} de {photographs.length}
          </span>
          <button onClick={() => move(1)} aria-label="Fotografía siguiente">
            <span>Siguiente</span> →
          </button>
        </div>
      </dialog>
    </>
  );
}

export function ArchitecturalFilm() {
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const [playbackHint, setPlaybackHint] = useState(false);
  function openFilm() {
    dialog.current?.showModal();
    void video.current?.play().catch(() => setPlaybackHint(true));
  }
  return (
    <>
      <button
        className="film-cover"
        onClick={openFilm}
        aria-label="Ver recorrido arquitectónico del proyecto"
      >
        {/* Architectural rendering, not evidence of completed construction. */}
        <img
          src="/media/film-poster.webp"
          width={848}
          height={478}
          loading="lazy"
          alt="Vista ilustrativa de la portería en el video arquitectónico del proyecto."
        />
        <span className="play-control" aria-hidden="true">
          ▷
        </span>
        <span className="film-cover-label">
          Ver recorrido <span aria-hidden="true">↗</span>
        </span>
      </button>
      <dialog
        className="media-dialog film-dialog"
        ref={dialog}
        aria-labelledby="film-title"
        aria-describedby="film-description"
        onClose={() => video.current?.pause()}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialog.current?.close();
        }}
      >
        <div className="dialog-toolbar">
          <h2 id="film-title">Recorrido arquitectónico</h2>
          <button
            className="dialog-close"
            autoFocus
            onClick={() => dialog.current?.close()}
            aria-label="Cerrar video"
          >
            Cerrar <span aria-hidden="true">×</span>
          </button>
        </div>
        <video
          ref={video}
          controls
          muted
          playsInline
          preload="none"
          poster="/media/film-poster.webp"
          aria-label="Visualización arquitectónica de Jardines del Encanto"
          onError={() => setFailed(true)}
        >
          <source src="/media/recorrido-arquitectonico.mp4" type="video/mp4" />
          Tu navegador no puede reproducir este video.
        </video>
        <p id="film-description" className="film-disclaimer">
          Visualización arquitectónica de la portería, las vías y zonas
          sociales. Imágenes ilustrativas: no representan el estado actual de
          obra.
        </p>
        {playbackHint && !failed && (
          <p className="playback-note" role="status">
            Pulsa el control de reproducción del video para comenzar.
          </p>
        )}
        {failed && (
          <p className="playback-note" role="alert">
            No pudimos reproducirlo aquí.{" "}
            <a href="/media/recorrido-arquitectonico.mp4" download>
              Descarga el video para verlo.
            </a>
          </p>
        )}
      </dialog>
    </>
  );
}
