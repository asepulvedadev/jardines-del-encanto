import type { ReactNode } from "react";
import { whatsappLink } from "../lib/project";

export const soachaEvent = {
  date: "2026-11-22",
  dateLabel: "Domingo 22 de noviembre de 2026",
  venue: "Cámara de Comercio de Bogotá en Soacha",
  message:
    "Hola, quiero información para asistir al evento de Jardines del Encanto el domingo 22 de noviembre de 2026 en la Cámara de Comercio de Bogotá en Soacha. ¿Me comparten el horario, la dirección exacta y cómo coordinar mi asistencia?",
} as const;

export function EventContactLink({
  children = "Quiero asistir · WhatsApp",
  className = "button button-lime",
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <a
      data-soacha-event-contact="true"
      href={whatsappLink(soachaEvent.message)}
      className={className}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <span className="button-arrow" aria-hidden="true">
        ↗
      </span>
      <span className="sr-only"> (abre WhatsApp en otra pestaña)</span>
    </a>
  );
}

export function SoachaEvent() {
  return (
    <section
      id="encuentro-soacha"
      className="soacha-event"
      aria-labelledby="soacha-event-title"
    >
      <div className="container event-invitation">
        <div className="event-copy">
          <p className="eyebrow">BOGOTÁ Y SOACHA, ESTÁN INVITADOS</p>
          <h2 id="soacha-event-title">
            <span>Domingo 22</span>
            <br />
            de noviembre.
          </h2>
          <h3 className="event-main-venue">{soachaEvent.venue}</h3>
          <p className="event-description">
            Una invitación para Bogotá, Soacha y sus alrededores. Ven a conocer
            Jardines del Encanto, conversa con nuestro equipo y resuelve tus
            dudas sobre tu próximo lote en Acacías, Meta.
          </p>
          <EventContactLink />
          <p className="event-detail-note">
            Escríbenos para conocer el horario, la dirección exacta y coordinar
            tu asistencia.
          </p>
        </div>
        <div className="event-date-card">
          <p className="event-date-label">LA CITA ES ESTE DOMINGO</p>
          <time dateTime={soachaEvent.date} aria-label={soachaEvent.dateLabel}>
            <span className="event-weekday">Domingo</span>
            <strong>22</strong>
            <span className="event-month">noviembre · 2026</span>
          </time>
          <p className="event-venue">{soachaEvent.venue}</p>
          <p className="event-place-note">
            El encuentro es en Soacha.
            <br />
            Los lotes están en Acacías, Meta.
          </p>
        </div>
        <div className="event-topics" aria-label="Conversemos sobre tu proyecto">
          <p>
            <span>01</span> Conoce el proyecto y su ubicación
          </p>
          <p>
            <span>02</span> Pregunta por lotes y financiación
          </p>
          <p>
            <span>03</span> Coordina tu próxima visita
          </p>
        </div>
      </div>
    </section>
  );
}

export function SoachaEventQuestions() {
  return (
    <>
      <details>
        <summary>
          ¿Dónde y cuándo es el encuentro en Soacha?
          <span aria-hidden="true">+</span>
        </summary>
        <p>
          Estaremos el {soachaEvent.dateLabel.toLowerCase()} en la{" "}
          {soachaEvent.venue}.
          El evento es en Soacha; los lotes del proyecto están en Acacías, Meta.
          Invitamos a las personas de Bogotá, Soacha y sus alrededores.
        </p>
      </details>
      <details>
        <summary>
          ¿Cómo puedo coordinar mi asistencia?
          <span aria-hidden="true">+</span>
        </summary>
        <p>
          Usa los botones de WhatsApp del evento para hablar con nuestro equipo
          y consultar el horario y la dirección exacta. Abrir el chat no
          confirma tu asistencia ni reserva un lote.
        </p>
      </details>
    </>
  );
}
