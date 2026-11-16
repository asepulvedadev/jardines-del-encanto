"use client";
import { useRef, useState } from "react";
import { galleryMedia } from "../lib/project";

type GalleryItem = (typeof galleryMedia)[number];

function GalleryPreview({ item, expanded = false }: { item: GalleryItem; expanded?: boolean }) {
  const isVideo = item.type === "video";
  return (
    <picture>
      {!isVideo && (
        <source
          type="image/webp"
          srcSet={`/media/${item.name}-640.webp 640w, /media/${item.name}-1280.webp 1280w`}
          sizes={expanded ? "100vw" : "(max-width: 767px) 100vw, 50vw"}
        />
      )}
      <img
        src={`/media/${item.name}${isVideo ? "-poster" : "-1280"}.webp`}
        alt={item.alt}
        width={isVideo ? 720 : 1280}
        height={isVideo ? 1280 : 720}
        loading={expanded ? "eager" : "lazy"}
        className={expanded ? "expanded-photo" : undefined}
      />
    </picture>
  );
}

export function PhotoGallery() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [index, setIndex] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const selected = galleryMedia[index];
  const move = (direction: number) =>
    setIndex(current => (current + direction + galleryMedia.length) % galleryMedia.length);
  return (
    <>
      <div className="photo-grid">
        {galleryMedia.map((item, i) => (
          <button
            type="button"
            className={`photo-tile photo-tile-${i}`}
            key={item.name}
            aria-label={`${item.type === "video" ? "Ver video" : "Ampliar fotografía"}: ${item.title}`}
            aria-haspopup="dialog"
            onClick={() => {
              setIndex(i);
              setIsOpen(true);
              dialog.current?.showModal();
            }}
          >
            <GalleryPreview item={item} />
            {item.type === "video" && (
              <span className="gallery-video-badge" aria-hidden="true">
                <span>▶</span> Video · {item.duration}
              </span>
            )}
            <span className="photo-caption">
              <span>{item.title}</span>
              <span aria-hidden="true">{item.type === "video" ? "▷" : "↗"}</span>
            </span>
          </button>
        ))}
      </div>
      <dialog
        className="media-dialog gallery-dialog"
        ref={dialog}
        aria-labelledby="photo-title"
        onClose={() => setIsOpen(false)}
        onClick={event => {
          if (event.target === event.currentTarget) dialog.current?.close();
        }}
        onKeyDown={event => {
          // Keep seeking and volume keys available to the native video player.
          if (event.target instanceof HTMLVideoElement) return;
          if (event.key === "ArrowRight") move(1);
          if (event.key === "ArrowLeft") move(-1);
        }}
      >
        <div className="dialog-toolbar">
          <h2 id="photo-title">{selected.title}</h2>
          <button
            type="button"
            className="dialog-close"
            autoFocus
            onClick={() => dialog.current?.close()}
            aria-label="Cerrar galería"
          >
            Cerrar <span aria-hidden="true">×</span>
          </button>
        </div>
        {isOpen && selected.type === "video" ? (
          <video
            key={selected.name}
            className="expanded-photo gallery-video"
            controls
            playsInline
            preload="metadata"
            poster={`/media/${selected.name}-poster.webp`}
            aria-label={selected.alt}
          >
            <source src={`/media/${selected.name}.mp4`} type="video/mp4" />
            Tu navegador no puede reproducir este video.{" "}
            <a href={`/media/${selected.name}.mp4`}>Abrir video</a>
          </video>
        ) : isOpen ? (
          <GalleryPreview item={selected} expanded />
        ) : null}
        <div className="gallery-controls">
          <button type="button" onClick={() => move(-1)} aria-label="Contenido anterior">
            ← <span>Anterior</span>
          </button>
          <span aria-live="polite">{index + 1} de {galleryMedia.length}</span>
          <button type="button" onClick={() => move(1)} aria-label="Contenido siguiente">
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
