"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { settingsError, type SettingsRequest } from "./settings-types";
import "./whatsapp-agent.css";

type Developer = { name: string; phone: string };
type AgentConfig = {
  version: number;
  shared_profile_version?: number;
  enabled: boolean;
  account_id: string;
  phone: string;
  developers: Developer[];
  instructions: string;
  knowledge: string;
  status: { ready: boolean; reason: string | null };
  lessons: {
    id: string;
    content: string;
    author: string;
    state: "pending" | "approved" | "rejected";
    created_at: string;
  }[];
  activity: { state: string; created_at: string; error: string | null }[];
};
type Draft = Pick<
  AgentConfig,
  | "version"
  | "shared_profile_version"
  | "account_id"
  | "phone"
  | "developers"
  | "instructions"
  | "knowledge"
>;
const emptyDraft: Draft = {
  version: 0,
  account_id: "",
  phone: "",
  developers: [],
  instructions: "",
  knowledge: "",
};
const reasons: Record<string, string> = {
  zernio_not_configured: "Conecta Zernio para continuar.",
  webhook_not_registered: "Falta verificar el webhook de WhatsApp.",
  hermes_unavailable: "Sara no está disponible. Revisa su conexión.",
  account_unverified: "La cuenta de WhatsApp no está verificada.",
  connection_disabled: "La conexión de WhatsApp está pausada.",
  agent_not_configured: "Completa y guarda la configuración.",
};
const activityLabels: Record<string, string> = {
  received: "Mensaje recibido",
  pending: "Pendiente",
  processing: "Procesando",
  replied: "Respuesta enviada",
  completed: "Completado",
  failed: "Falló la respuesta",
  error: "Error",
  ignored: "Mensaje omitido",
  rejected: "Mensaje rechazado",
};
function draftFrom(value: AgentConfig): Draft {
  return {
    version: value.version,
    ...(value.shared_profile_version === undefined
      ? {}
      : { shared_profile_version: value.shared_profile_version }),
    account_id: value.account_id,
    phone: value.phone,
    developers: value.developers,
    instructions: value.instructions,
    knowledge: value.knowledge,
  };
}
function dateLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible"
    : date.toLocaleString("es-CO", {
        timeZone: "America/Bogota",
        dateStyle: "short",
        timeStyle: "short",
      });
}

export function WhatsAppAgentPanel({
  request,
  active,
}: {
  request: SettingsRequest;
  active: boolean;
}) {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [consent, setConsent] = useState(false);
  const [needsReview, setNeedsReview] = useState(false);
  const [reviewVersion, setReviewVersion] = useState<number | null>(null);
  const dirty = useRef(false);
  const lock = useRef(false);
  const mounted = useRef(false);

  const load = useCallback(async () => {
    if (lock.current) return;
    lock.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await request<AgentConfig>("social/whatsapp-agent");
      setConfig(result);
      setConsent(false);
      if (dirty.current) {
        setNeedsReview(true);
        setReviewVersion(result.version);
        setNotice(
          "Conservamos tus cambios sin guardar. Revisa la versión del servidor antes de aplicarlos.",
        );
      } else {
        setDraft(draftFrom(result));
        setNeedsReview(false);
        setReviewVersion(null);
      }
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      lock.current = false;
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    if (active && !mounted.current) {
      mounted.current = true;
      void load();
    }
  }, [active, load]);

  function edit<K extends keyof Draft>(key: K, value: Draft[K]) {
    dirty.current = true;
    setDraft((old) => ({ ...old, [key]: value }));
    setConsent(false);
    setNotice("");
  }
  function accept(result: AgentConfig, keepDraft: boolean) {
    setConfig(result);
    setConsent(false);
    if (keepDraft) {
      setNeedsReview(true);
      setReviewVersion(result.version);
      setNotice(
        "Conservamos tus cambios sin guardar. Revisa la versión del servidor antes de aplicarlos.",
      );
    } else {
      dirty.current = false;
      setDraft(draftFrom(result));
      setNeedsReview(false);
      setReviewVersion(null);
      setNotice("Configuración actualizada.");
    }
  }
  async function save(enabled: boolean, pauseOnly = false) {
    if (
      !config ||
      lock.current ||
      (!pauseOnly && (needsReview || (enabled && !consent)))
    )
      return;
    if (enabled && !config.enabled && (!config.status.ready || dirty.current))
      return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<AgentConfig>(
        "social/whatsapp-agent",
        "PATCH",
        {
          ...(pauseOnly ? draftFrom(config) : draft),
          enabled,
          consent_confirmed: enabled && consent,
        },
      );
      accept(result, pauseOnly && dirty.current);
    } catch (cause) {
      setError(settingsError(cause));
      setNeedsReview(true);
      setReviewVersion(null);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function decide(id: string, decision: "approve" | "reject") {
    if (!config || lock.current || needsReview) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<AgentConfig>(
        `social/whatsapp-agent/lessons/${id}/${decision}`,
        "POST",
        { version: config.version },
      );
      accept(result, dirty.current);
    } catch (cause) {
      setError(settingsError(cause));
      setNeedsReview(true);
      setReviewVersion(null);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const disabled = busy || loading;
  const pendingLessons =
    config?.lessons.filter((lesson) => lesson.state === "pending") ?? [];
  return (
    <div className="whatsapp-agent" aria-busy={disabled}>
      <header className="whatsapp-agent-heading">
        <div>
          <h3>Sara WhatsApp</h3>
          <p>Responde mensajes entrantes. No inicia conversaciones.</p>
        </div>
        <button type="button" disabled={disabled} onClick={load}>
          Actualizar estado
        </button>
      </header>
      {loading && <p role="status">Consultando Sara WhatsApp…</p>}
      {error && (
        <p className="crm-error" role="alert">
          {error} Actualiza el estado antes de intentar de nuevo.
        </p>
      )}
      {notice && (
        <p className="whatsapp-agent-notice" role="status">
          {notice}
        </p>
      )}
      {config && (
        <>
          <div className="whatsapp-agent-status" role="status">
            <strong>
              {config.enabled && config.status.ready
                ? "Activa · conexión verificada"
                : config.enabled
                  ? "Habilitada · no disponible"
                  : "Pausada"}
            </strong>
            {!config.status.ready && (
              <span>
                {reasons[config.status.reason ?? ""] ??
                  "No se pudo verificar la conexión."}
              </span>
            )}
          </div>
          {needsReview && (
            <div className="whatsapp-agent-review">
              <p>
                Actualiza y compara antes de guardar. Tu borrador no se ha
                descartado.
              </p>
              {reviewVersion !== null && (
                <>
                  <details>
                    <summary>Versión actual del servidor</summary>
                    <dl>
                      <dt>Cuenta</dt>
                      <dd>{config.account_id || "Sin configurar"}</dd>
                      <dt>Número</dt>
                      <dd>{config.phone || "Sin configurar"}</dd>
                      <dt>Desarrolladores</dt>
                      <dd>
                        {config.developers
                          .map(
                            (developer) =>
                              `${developer.name}: ${developer.phone}`,
                          )
                          .join(" · ") || "Sin configurar"}
                      </dd>
                      <dt>Instrucciones</dt>
                      <dd>{config.instructions || "Sin instrucciones"}</dd>
                      <dt>Conocimiento</dt>
                      <dd>{config.knowledge || "Sin conocimiento"}</dd>
                    </dl>
                  </details>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setDraft((old) => ({
                        ...old,
                        version: reviewVersion,
                        shared_profile_version: config.shared_profile_version,
                      }));
                      setNeedsReview(false);
                      setReviewVersion(null);
                      setConsent(false);
                      setNotice(
                        "Borrador conservado. Guardar reemplazará la versión revisada.",
                      );
                    }}
                  >
                    Revisé la versión actual
                  </button>
                </>
              )}
            </div>
          )}
          <fieldset disabled={disabled} className="whatsapp-agent-fields">
            <legend>Canal de atención</legend>
            <div className="whatsapp-agent-grid">
              <label htmlFor="whatsapp-agent-account">
                ID de cuenta de WhatsApp
                <input
                  id="whatsapp-agent-account"
                  value={draft.account_id}
                  maxLength={160}
                  autoComplete="off"
                  onChange={(event) => edit("account_id", event.target.value)}
                />
              </label>
              <label htmlFor="whatsapp-agent-phone">
                Número de atención
                <input
                  id="whatsapp-agent-phone"
                  type="tel"
                  value={draft.phone}
                  maxLength={30}
                  autoComplete="off"
                  placeholder="Formato internacional"
                  onChange={(event) => edit("phone", event.target.value)}
                />
              </label>
            </div>
          </fieldset>
          <fieldset disabled={disabled} className="whatsapp-agent-fields">
            <legend>Desarrolladores autorizados · máximo 2</legend>
            <p>
              Solo estos números pueden proponer aprendizajes. Los clientes
              tienen un contexto separado.
            </p>
            {draft.developers.map((developer, index) => (
              <div className="whatsapp-agent-developer" key={index}>
                <label htmlFor={`whatsapp-developer-name-${index}`}>
                  Nombre {index + 1}
                  <input
                    id={`whatsapp-developer-name-${index}`}
                    value={developer.name}
                    maxLength={80}
                    onChange={(event) =>
                      edit(
                        "developers",
                        draft.developers.map((item, i) =>
                          i === index
                            ? { ...item, name: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
                <label htmlFor={`whatsapp-developer-phone-${index}`}>
                  Número {index + 1}
                  <input
                    id={`whatsapp-developer-phone-${index}`}
                    type="tel"
                    value={developer.phone}
                    maxLength={30}
                    autoComplete="off"
                    placeholder="Formato internacional"
                    onChange={(event) =>
                      edit(
                        "developers",
                        draft.developers.map((item, i) =>
                          i === index
                            ? { ...item, phone: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  aria-label={`Quitar desarrollador ${index + 1}`}
                  onClick={() =>
                    edit(
                      "developers",
                      draft.developers.filter((_, i) => i !== index),
                    )
                  }
                >
                  Quitar
                </button>
              </div>
            ))}
            <button
              type="button"
              disabled={draft.developers.length >= 2}
              onClick={() =>
                edit("developers", [
                  ...draft.developers,
                  { name: "", phone: "" },
                ])
              }
            >
              Agregar desarrollador
            </button>
          </fieldset>
          <fieldset disabled={disabled} className="whatsapp-agent-fields">
            <legend>Entrenamiento</legend>
            <label htmlFor="whatsapp-agent-instructions">
              Instrucciones de atención
              <textarea
                id="whatsapp-agent-instructions"
                rows={4}
                maxLength={2000}
                value={draft.instructions}
                onChange={(event) => edit("instructions", event.target.value)}
              />
            </label>
            <label htmlFor="whatsapp-agent-knowledge">
              Conocimiento aprobado
              <textarea
                id="whatsapp-agent-knowledge"
                rows={5}
                maxLength={4000}
                value={draft.knowledge}
                onChange={(event) => edit("knowledge", event.target.value)}
              />
            </label>
            <p>No se importan conversaciones de clientes como conocimiento.</p>
          </fieldset>
          <label
            className="whatsapp-agent-consent"
            htmlFor="whatsapp-agent-consent"
          >
            <input
              id="whatsapp-agent-consent"
              type="checkbox"
              checked={consent}
              disabled={disabled}
              onChange={(event) => setConsent(event.target.checked)}
            />
            <span>
              Autorizo respuestas solo a mensajes entrantes en esta cuenta y
              número. No autorizo envíos proactivos.
            </span>
          </label>
          <div className="whatsapp-agent-actions">
            <button
              type="button"
              className="whatsapp-agent-primary"
              disabled={disabled || needsReview || (config.enabled && !consent)}
              onClick={() => save(config.enabled)}
            >
              Guardar cambios
            </button>
            {config.enabled ? (
              <button
                type="button"
                disabled={disabled}
                onClick={() => save(false, true)}
              >
                Pausar
              </button>
            ) : (
              <button
                type="button"
                disabled={
                  disabled ||
                  needsReview ||
                  !config.status.ready ||
                  !consent ||
                  dirty.current
                }
                onClick={() => save(true)}
              >
                Activar
              </button>
            )}
          </div>
          {!config.enabled && !config.status.ready && (
            <p className="whatsapp-agent-hint">
              Guarda la configuración y verifica la conexión antes de activar.
            </p>
          )}
          <section
            className="whatsapp-agent-lessons"
            aria-labelledby="whatsapp-lessons-title"
          >
            <h4 id="whatsapp-lessons-title">Aprendizajes por revisar</h4>
            <p>
              Desde un número autorizado: <code>/aprender &lt;texto&gt;</code>.
              Se publica solo con aprobación web.
            </p>
            {!pendingLessons.length && <p>No hay aprendizajes pendientes.</p>}
            {pendingLessons.map((lesson) => (
              <article key={lesson.id} className="whatsapp-agent-lesson">
                <p>{lesson.content}</p>
                <span>
                  {lesson.author} · {dateLabel(lesson.created_at)} (Bogotá)
                </span>
                <div className="whatsapp-agent-actions">
                  <button
                    type="button"
                    disabled={disabled || needsReview}
                    onClick={() => decide(lesson.id, "approve")}
                  >
                    Aprobar
                  </button>
                  <button
                    type="button"
                    disabled={disabled || needsReview}
                    onClick={() => decide(lesson.id, "reject")}
                  >
                    Rechazar
                  </button>
                </div>
              </article>
            ))}
          </section>
          <details className="whatsapp-agent-activity">
            <summary>Actividad reciente</summary>
            {!config.activity.length && <p>Aún no hay actividad.</p>}
            <ul>
              {config.activity.slice(0, 10).map((item, index) => (
                <li key={`${item.created_at}-${index}`}>
                  <strong>
                    {activityLabels[item.state] ?? "Evento registrado"}
                  </strong>
                  <span>{dateLabel(item.created_at)} (Bogotá)</span>
                  {item.error && (
                    <p>La operación no se completó. Revisa la conexión.</p>
                  )}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </div>
  );
}
