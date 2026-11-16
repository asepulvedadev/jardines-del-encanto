"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./icon";
import { CampaignReviews } from "./campaign-reviews";
import { shortDate } from "./types";
import {
  campaignAudiences,
  campaignReviewErrors,
  campaignReviewLabels,
  campaignIssues,
  campaignMedia,
  emptyCampaign,
  renderCampaignText,
  safeCampaignLink,
  type CampaignButton,
  type CampaignDocument,
  type CampaignRecord,
} from "./campaign-types";
import "../../app/crm/campaigns.css";

type Collection = { items: CampaignRecord[]; limited: boolean };
type Props = { csrf: string; onDirtyChange?: (dirty: boolean) => void };

export function CampaignPanel({ csrf, onDirtyChange }: Props) {
  const [collection, setCollection] = useState<Collection | null>(null);
  const [selected, setSelected] = useState("");
  const [form, setForm] = useState<CampaignDocument | null>(null);
  const [query, setQuery] = useState("");
  const [audience, setAudience] = useState("all");
  const [tab, setTab] = useState<"edit" | "preview">("preview");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reply, setReply] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  const bodyInput = useRef<HTMLTextAreaElement>(null);
  const lock = useRef(false);
  const current = collection?.items.find((item) => item.id === selected);
  const dirty =
    !!form &&
    (!current || JSON.stringify(form) !== JSON.stringify(current.document));
  const issues = form ? campaignIssues(form) : [];

  const request = useCallback(
    async <T,>(
      path: string,
      method = "GET",
      payload?: unknown,
      signal?: AbortSignal,
    ): Promise<T> => {
      const response = await fetch(`/api/crm/${path}`, {
        method,
        cache: "no-store",
        signal,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: method === "GET" ? undefined : JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        if (
          typeof result.detail === "string" &&
          campaignReviewErrors[result.detail]
        )
          throw new Error(campaignReviewErrors[result.detail]);
        if (response.status === 401)
          throw new Error("Tu sesión finalizó. Recarga e ingresa de nuevo.");
        if (response.status === 409)
          throw new Error(
            "Otra sesión modificó esta plantilla. Exporta tus cambios antes de recargar; no se sobrescribió nada.",
          );
        if (response.status === 422)
          throw new Error(
            "Revisa las variables, enlaces, fechas y botones antes de guardar.",
          );
        throw new Error(
          "No se pudo completar la solicitud. Tus cambios siguen en el editor.",
        );
      }
      return result as T;
    },
    [csrf],
  );

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError("");
      try {
        const result = await request<Collection>(
          "campaigns",
          "GET",
          undefined,
          signal,
        );
        if (signal?.aborted) return;
        setCollection(result);
        setSelected(result.items[0]?.id ?? "");
        setForm(result.items[0]?.document ?? null);
        setReply("");
        setImageFailed(false);
      } catch (cause) {
        if (!signal?.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "No pudimos cargar las plantillas.",
          );
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [request],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function canLeave() {
    return (
      !dirty ||
      window.confirm("Hay cambios sin guardar en la plantilla. ¿Descartarlos?")
    );
  }
  function choose(item?: CampaignRecord, discardConfirmed = false) {
    if (lock.current || (!discardConfirmed && !canLeave())) return;
    if (!item) {
      setAudience("all");
      setQuery("");
    }
    setSelected(item?.id ?? "new");
    setForm(item?.document ?? emptyCampaign());
    setError("");
    setNotice("");
    setReply("");
    setImageFailed(false);
    setTab(item ? "preview" : "edit");
  }
  function edit(patch: Partial<CampaignDocument>) {
    setForm((previous) => (previous ? { ...previous, ...patch } : previous));
    setNotice("");
    setReply("");
    if ("image_id" in patch) setImageFailed(false);
  }
  async function save() {
    if (
      !form ||
      (!dirty && current?.version !== 0) ||
      issues.length ||
      lock.current
    )
      return;
    lock.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await request<CampaignRecord>(
        current ? `campaigns/${current.id}` : "campaigns",
        current ? "PATCH" : "POST",
        current
          ? { version: current.version, document: form }
          : { document: form },
      );
      setCollection((previous) => ({
        limited: previous?.limited ?? false,
        items: current
          ? (previous?.items ?? []).map((item) =>
              item.id === saved.id ? saved : item,
            )
          : [...(previous?.items ?? []), saved],
      }));
      setSelected(saved.id);
      setForm(saved.document);
      setNotice(
        "Borrador guardado en el CRM. No se envió a Meta ni a contactos.",
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos guardar el borrador.",
      );
    } finally {
      lock.current = false;
      setSaving(false);
    }
  }
  function insertVariable(key: string) {
    if (!form) return;
    const start = bodyInput.current?.selectionStart ?? form.body.length;
    const end = bodyInput.current?.selectionEnd ?? start;
    const token = `{{${key}}}`;
    edit({ body: form.body.slice(0, start) + token + form.body.slice(end) });
    requestAnimationFrame(() => {
      bodyInput.current?.focus();
      bodyInput.current?.setSelectionRange(
        start + token.length,
        start + token.length,
      );
    });
  }
  function exportDraft() {
    if (!form) return;
    const blob = new Blob(
      [
        JSON.stringify(
          {
            format: "jardines-internal-draft-v1",
            status: "local_draft",
            document: form,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${selected || "plantilla"}.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Borrador exportado. No es una plantilla aprobada por Meta.");
  }
  async function copyText() {
    if (!form) return;
    try {
      await navigator.clipboard.writeText(
        renderCampaignText(form.body, form.variables),
      );
      setNotice("Texto de ejemplo copiado. No se envió ningún mensaje.");
    } catch {
      setError(
        "El navegador no permitió copiar. Puedes seleccionar el texto de la vista previa.",
      );
    }
  }
  function editButton(index: number, patch: Partial<CampaignButton>) {
    if (form)
      edit({
        buttons: form.buttons.map((button, position) =>
          position === index ? { ...button, ...patch } : button,
        ),
      });
  }
  const visible =
    collection?.items.filter(
      ({ document: doc }) =>
        (audience === "all" || doc.audience === audience) &&
        `${doc.name} ${doc.body}`
          .toLocaleLowerCase("es")
          .includes(query.toLocaleLowerCase("es").trim()),
    ) ?? [];

  return (
    <section
      className="campaign-workspace"
      aria-label="Biblioteca de plantillas"
    >
      <div className="campaign-toolbar">
        <label className="campaign-search">
          <Icon name="search" />
          <span className="sr-only">Buscar plantilla</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar…"
            type="search"
          />
        </label>
        <label>
          <span className="sr-only">Filtrar audiencia</span>
          <select
            value={audience}
            onChange={(event) => setAudience(event.target.value)}
          >
            <option value="all">Todas las audiencias</option>
            {Object.entries(campaignAudiences).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="crm-button"
          onClick={() => choose()}
          disabled={loading || saving || !collection}
        >
          <Icon name="plus" />
          Nueva plantilla
        </button>
      </div>
      <div className="campaign-safety">
        <span className="campaign-status-dot" />
        <strong>Biblioteca de plantillas</strong>
        <span>Revisión con confirmación · Sin envíos a contactos</span>
      </div>
      {error && (
        <div className="crm-error crm-message" role="alert">
          {error}
          <button
            className="crm-button crm-secondary"
            disabled={saving}
            onClick={() => {
              if (canLeave()) void load();
            }}
          >
            Recargar plantillas
          </button>
        </div>
      )}
      <p className="campaign-feedback" role="status">
        {saving ? "Guardando borrador…" : notice}
      </p>
      {loading ? (
        <p role="status">Cargando plantillas…</p>
      ) : (
        collection && (
          <div className="campaign-layout">
            <aside
              className="campaign-library"
              aria-label="Plantillas disponibles"
            >
              <div className="campaign-library-heading">
                <strong>Biblioteca</strong>
                <span>
                  {visible.length} de {collection.items.length}
                </span>
              </div>
              <div className="campaign-list">
                {visible.length ? (
                  visible.map((item) => (
                    <button
                      key={item.id}
                      className={`campaign-card ${selected === item.id ? "is-selected" : ""}`}
                      aria-pressed={selected === item.id}
                      disabled={saving}
                      onClick={() => choose(item)}
                    >
                      {item.document.image_id ? (
                        <img
                          src={campaignMedia(item.document.image_id)}
                          alt=""
                          width={44}
                          height={64}
                          loading="lazy"
                        />
                      ) : (
                        <span className="campaign-card-placeholder">
                          <Icon name="message" />
                        </span>
                      )}
                      <span>
                        <small>
                          {campaignAudiences[item.document.audience]}
                        </small>
                        <strong>{item.document.name}</strong>
                        <small>
                          {item.review
                            ? `${campaignReviewLabels[item.review.status] ?? item.review.status} · v${item.review.version}${item.review.version !== item.version ? " · Editada" : ""}`
                            : "Borrador privado"}
                        </small>
                        <small>
                          {item.document.suggested_date
                            ? `Sugerida: ${shortDate(item.document.suggested_date)}`
                            : "Sin fecha sugerida"}
                        </small>
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="campaign-muted">
                    No hay coincidencias. Prueba otra búsqueda.
                  </p>
                )}
              </div>
              {collection.limited && (
                <p className="campaign-muted">
                  Se muestran hasta 100 borradores guardados, además de la
                  colección inicial.
                </p>
              )}
            </aside>
            {form ? (
              <div className="campaign-studio">
                <div className="campaign-studio-bar">
                  <div>
                    <strong>
                      {current ? "Editar plantilla" : "Nueva plantilla"}
                    </strong>
                    <small>
                      {dirty
                        ? "Cambios sin guardar"
                        : current?.version === 0
                          ? "Colección inicial · Sin guardar"
                          : "Guardada · Borrador interno"}
                    </small>
                  </div>
                  <button
                    className="crm-button"
                    disabled={
                      saving ||
                      (!dirty && current?.version !== 0) ||
                      !!issues.length
                    }
                    onClick={() => void save()}
                  >
                    <Icon name="check" />
                    {saving ? "Guardando…" : "Guardar borrador"}
                  </button>
                </div>
                {current && (
                  <CampaignReviews
                    key={`${current.id}:${current.version}`}
                    record={current}
                    disabled={dirty || saving || !!issues.length}
                    request={request}
                    onReview={(review) => {
                      setNotice("");
                      setCollection((previous) =>
                        previous
                          ? {
                              ...previous,
                              items: previous.items.map((item) =>
                                item.id === current.id
                                  ? {
                                      ...item,
                                      review: {
                                        id: review.id,
                                        version: review.version,
                                        status: review.status,
                                      },
                                    }
                                  : item,
                              ),
                            }
                          : previous,
                      );
                    }}
                  />
                )}
                <div
                  className="campaign-tabs"
                  role="group"
                  aria-label="Vista de plantilla"
                >
                  <button
                    aria-pressed={tab === "edit"}
                    onClick={() => setTab("edit")}
                  >
                    Editar
                  </button>
                  <button
                    aria-pressed={tab === "preview"}
                    onClick={() => setTab("preview")}
                  >
                    Vista previa
                  </button>
                </div>
                <div className="campaign-studio-grid">
                  <form
                    className={`campaign-editor ${tab === "edit" ? "is-visible" : ""}`}
                    onSubmit={(event) => {
                      event.preventDefault();
                      void save();
                    }}
                  >
                    <fieldset disabled={saving}>
                      <label>
                        Nombre de la plantilla
                        <input
                          value={form.name}
                          maxLength={100}
                          required
                          onChange={(event) =>
                            edit({ name: event.target.value })
                          }
                        />
                      </label>
                      <div className="campaign-field-pair">
                        <label>
                          Audiencia
                          <select
                            value={form.audience}
                            onChange={(event) =>
                              edit({
                                audience: event.target
                                  .value as CampaignDocument["audience"],
                              })
                            }
                          >
                            {Object.entries(campaignAudiences).map(
                              ([key, label]) => (
                                <option key={key} value={key}>
                                  {label}
                                </option>
                              ),
                            )}
                          </select>
                        </label>
                        <label>
                          Fecha sugerida
                          <input
                            type="date"
                            value={form.suggested_date ?? ""}
                            onChange={(event) =>
                              edit({
                                suggested_date: event.target.value || null,
                              })
                            }
                          />
                        </label>
                      </div>
                      <p className="campaign-muted">
                        La fecha organiza el borrador; no programa envíos.
                      </p>
                      <label>
                        Imagen
                        <select
                          value={form.image_id ?? ""}
                          onChange={(event) =>
                            edit({ image_id: event.target.value || null })
                          }
                        >
                          <option value="">Sin imagen</option>
                          {Array.from({ length: 16 }, (_, index) => {
                            const id = `campaign-${String(index + 1).padStart(2, "0")}`;
                            const name =
                              collection.items.find((item) => item.id === id)
                                ?.document.name ?? `Pieza ${index + 1}`;
                            return (
                              <option key={id} value={id}>
                                {name}
                              </option>
                            );
                          })}
                        </select>
                      </label>
                      <p className="campaign-muted">
                        Cambiar el mensaje no modifica los textos integrados en
                        la imagen.
                      </p>
                      <label>
                        Mensaje{" "}
                        <span className="campaign-count">
                          {form.body.length}/1.024
                        </span>
                        <textarea
                          ref={bodyInput}
                          value={form.body}
                          maxLength={1024}
                          rows={7}
                          required
                          onChange={(event) =>
                            edit({ body: event.target.value })
                          }
                        />
                      </label>
                      <details className="campaign-section">
                        <summary>
                          Variables y enlaces{" "}
                          <span>{form.variables.length}/12</span>
                        </summary>
                        <p className="campaign-muted">
                          Los valores son ejemplos de vista previa, no datos de
                          contactos. Pulsa Insertar para añadir una variable al
                          mensaje.
                        </p>
                        {form.variables.map((variable, index) => (
                          <div className="campaign-variable" key={index}>
                            <div className="campaign-field-pair">
                              <label>
                                Nombre de variable
                                <input
                                  aria-label={`Variable ${index + 1}`}
                                  value={variable.key}
                                  maxLength={40}
                                  onChange={(event) =>
                                    edit({
                                      variables: form.variables.map(
                                        (item, n) =>
                                          n === index
                                            ? {
                                                ...item,
                                                key: event.target.value,
                                              }
                                            : item,
                                      ),
                                    })
                                  }
                                />
                              </label>
                              <label>
                                Tipo
                                <select
                                  value={variable.kind}
                                  onChange={(event) =>
                                    edit({
                                      variables: form.variables.map(
                                        (item, n) =>
                                          n === index
                                            ? {
                                                ...item,
                                                kind: event.target.value as
                                                  | "text"
                                                  | "link",
                                              }
                                            : item,
                                      ),
                                    })
                                  }
                                >
                                  <option value="text">Texto</option>
                                  <option value="link">Enlace HTTPS</option>
                                </select>
                              </label>
                            </div>
                            <label>
                              {variable.kind === "link"
                                ? "Enlace de ejemplo"
                                : "Valor de ejemplo"}
                              <input
                                value={variable.example}
                                maxLength={1000}
                                type={variable.kind === "link" ? "url" : "text"}
                                onChange={(event) =>
                                  edit({
                                    variables: form.variables.map((item, n) =>
                                      n === index
                                        ? {
                                            ...item,
                                            example: event.target.value,
                                          }
                                        : item,
                                    ),
                                  })
                                }
                              />
                            </label>
                            <div className="campaign-inline-actions">
                              <button
                                type="button"
                                className="campaign-text-button"
                                onClick={() => insertVariable(variable.key)}
                              >{`Insertar {{${variable.key}}}`}</button>
                              <button
                                type="button"
                                className="campaign-text-button"
                                onClick={() =>
                                  edit({
                                    variables: form.variables.filter(
                                      (_, n) => n !== index,
                                    ),
                                  })
                                }
                              >
                                Quitar variable
                              </button>
                            </div>
                          </div>
                        ))}
                        <button
                          type="button"
                          className="crm-button crm-secondary"
                          disabled={form.variables.length >= 12}
                          onClick={() => {
                            let number = 1;
                            while (
                              form.variables.some(
                                (v) => v.key === `variable_${number}`,
                              )
                            )
                              number++;
                            edit({
                              variables: [
                                ...form.variables,
                                {
                                  key: `variable_${number}`,
                                  kind: "text",
                                  example: "Ejemplo",
                                },
                              ],
                            });
                          }}
                        >
                          <Icon name="plus" />
                          Añadir variable
                        </button>
                      </details>
                      <details className="campaign-section">
                        <summary>
                          Botones de elección{" "}
                          <span>{form.buttons.length}/3</span>
                        </summary>
                        <p className="campaign-muted">
                          Define respuestas o enlaces para preparar el envío
                          futuro. No ejecutan automatizaciones.
                        </p>
                        {form.buttons.map((button, index) => (
                          <div className="campaign-variable" key={index}>
                            <div className="campaign-field-pair">
                              <label>
                                Tipo
                                <select
                                  value={button.kind}
                                  onChange={(event) =>
                                    editButton(index, {
                                      kind: event.target
                                        .value as CampaignButton["kind"],
                                      value:
                                        event.target.value === "url"
                                          ? "https://jardinesdelencanto.site/"
                                          : `respuesta_${index + 1}`,
                                    })
                                  }
                                >
                                  <option value="reply">Respuesta</option>
                                  <option value="url">Abrir enlace</option>
                                </select>
                              </label>
                              <label>
                                Texto del botón
                                <input
                                  value={button.label}
                                  maxLength={25}
                                  onChange={(event) =>
                                    editButton(index, {
                                      label: event.target.value,
                                    })
                                  }
                                />
                              </label>
                            </div>
                            <label>
                              {button.kind === "url"
                                ? "URL o {{variable_de_enlace}}"
                                : "Clave de respuesta"}
                              <input
                                value={button.value}
                                maxLength={button.kind === "url" ? 1000 : 80}
                                onChange={(event) =>
                                  editButton(index, {
                                    value: event.target.value,
                                  })
                                }
                              />
                            </label>
                            <button
                              type="button"
                              className="campaign-text-button"
                              onClick={() =>
                                edit({
                                  buttons: form.buttons.filter(
                                    (_, n) => n !== index,
                                  ),
                                })
                              }
                            >
                              Quitar botón
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          className="crm-button crm-secondary"
                          disabled={form.buttons.length >= 3}
                          onClick={() =>
                            edit({
                              buttons: [
                                ...form.buttons,
                                {
                                  kind: "reply",
                                  label: `Opción ${form.buttons.length + 1}`,
                                  value: `opcion_${form.buttons.length + 1}`,
                                },
                              ],
                            })
                          }
                        >
                          <Icon name="plus" />
                          Añadir botón
                        </button>
                      </details>
                    </fieldset>
                    {issues.length > 0 && (
                      <div className="campaign-validation" role="status">
                        <strong>Antes de guardar</strong>
                        <ul>
                          {issues.map((issue) => (
                            <li key={issue}>{issue}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div className="campaign-inline-actions">
                      <button
                        type="button"
                        className="crm-button crm-secondary"
                        onClick={exportDraft}
                      >
                        <Icon name="download" />
                        Exportar borrador
                      </button>
                      <button
                        type="button"
                        className="campaign-text-button"
                        disabled={!dirty || saving}
                        onClick={() => {
                          if (canLeave()) {
                            if (current) choose(current, true);
                            else {
                              setSelected(collection.items[0]?.id ?? "");
                              setForm(collection.items[0]?.document ?? null);
                            }
                          }
                        }}
                      >
                        Descartar cambios
                      </button>
                    </div>
                    <p className="campaign-muted">
                      Usar solo con autorización de contacto válida. La
                      aprobación y compatibilidad de Meta se validarán antes de
                      cualquier envío.
                    </p>
                  </form>
                  <aside
                    className={`campaign-preview ${tab === "preview" ? "is-visible" : ""}`}
                    aria-label="Vista previa de WhatsApp"
                  >
                    <div className="campaign-preview-heading">
                      <strong>Vista previa</strong>
                      <span>Datos de ejemplo</span>
                    </div>
                    <div className="campaign-phone">
                      <div className="campaign-phone-header">
                        <img
                          src="/brand/jardines-del-encanto-refinado.svg"
                          alt=""
                          width={34}
                          height={40}
                        />
                        <div>
                          <strong>Jardines del Encanto</strong>
                          <small>Borrador · Sin enviar</small>
                        </div>
                      </div>
                      <div className="campaign-phone-body" key={selected}>
                        <div className="campaign-bubble">
                          {form.image_id &&
                            (!imageFailed ? (
                              <img
                                className="campaign-creative"
                                src={campaignMedia(form.image_id)}
                                alt={`Imagen de ${form.name}`}
                                onError={() => setImageFailed(true)}
                              />
                            ) : (
                              <p className="campaign-validation">
                                No se pudo cargar la imagen. Recarga las
                                plantillas para intentarlo de nuevo.
                              </p>
                            ))}
                          <p className="campaign-message-text">
                            {renderCampaignText(form.body, form.variables)}
                          </p>
                          <span className="campaign-message-time">
                            Vista de ejemplo
                          </span>
                          {form.buttons.map((button, index) => {
                            const url = renderCampaignText(
                              button.value,
                              form.variables,
                            );
                            return button.kind === "url" ? (
                              <a
                                key={index}
                                className="campaign-message-button"
                                href={safeCampaignLink(url) ? url : undefined}
                                aria-disabled={!safeCampaignLink(url)}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                ↗ {button.label || "Botón de enlace"}
                              </a>
                            ) : (
                              <button
                                key={index}
                                type="button"
                                className="campaign-message-button"
                                onClick={() =>
                                  setReply(
                                    `Respuesta simulada: ${button.label} · Clave: ${button.value}. No se envió nada.`,
                                  )
                                }
                              >
                                ↩ {button.label || "Botón de respuesta"}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                    <p className="campaign-preview-reply" role="status">
                      {reply ||
                        "Los botones de respuesta solo simulan una elección aquí."}
                    </p>
                    <div className="campaign-preview-actions">
                      <button
                        type="button"
                        className="crm-button crm-secondary"
                        onClick={() => void copyText()}
                      >
                        Copiar texto
                      </button>
                      {form.image_id && (
                        <a
                          className="crm-button crm-secondary"
                          href={campaignMedia(form.image_id)}
                          download={`${form.image_id}.png`}
                        >
                          <Icon name="download" />
                          Imagen
                        </a>
                      )}
                    </div>
                    <p className="campaign-muted">
                      Representación orientativa; WhatsApp puede mostrar otra
                      distribución.
                    </p>
                  </aside>
                </div>
              </div>
            ) : (
              <p>Selecciona una plantilla o crea una nueva.</p>
            )}
          </div>
        )
      )}
    </section>
  );
}
