"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  campaignMedia,
  campaignReviewLabels,
  renderCampaignText,
  type CampaignRecord,
  type CampaignReview,
} from "./campaign-types";

type Request = <T>(
  path: string,
  method?: string,
  payload?: unknown,
  signal?: AbortSignal,
) => Promise<T>;
type Account = { id: string; label: string };
type Preview = {
  name: string;
  version: number;
  account: Account;
  category: string;
  language: string;
  components: unknown[];
};
type Props = {
  record: CampaignRecord;
  disabled: boolean;
  request: Request;
  onReview: (review: CampaignReview) => void;
};

export function CampaignReviews({
  record,
  disabled,
  request,
  onReview,
}: Props) {
  const [history, setHistory] = useState<CampaignReview[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [account, setAccount] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const lock = useRef(false);
  const prefix = `campaigns/${record.id}`;
  const hasSubmission = history.some(
    (row) => row.version === record.version && row.account_id === account,
  );
  const latest = history[0];

  const loadHistory = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const result = await request<{ items: CampaignReview[] }>(
          `${prefix}/reviews`,
          "GET",
          undefined,
          signal,
        );
        if (!signal?.aborted) {
          setHistory(result.items);
          setLoaded(true);
        }
      } catch (cause) {
        if (!signal?.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "No pudimos cargar el historial.",
          );
      }
    },
    [prefix, request],
  );
  useEffect(() => {
    const controller = new AbortController();
    void loadHistory(controller.signal);
    return () => controller.abort();
  }, [loadHistory]);

  useEffect(() => {
    if (!isOpen || !dialog.current?.open) return;
    if (busy) dialog.current.focus();
    else closeButton.current?.focus();
  }, [isOpen, busy]);

  async function open() {
    if (disabled || lock.current || !loaded) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    setAccount("");
    setAccounts([]);
    setIsOpen(true);
    setPreview(null);
    setConfirmed(false);
    setAttempted(false);
    dialog.current?.showModal();
    try {
      const result = await request<{ items: Account[] }>(
        "campaigns/review-accounts",
      );
      setAccounts(result.items);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos consultar las cuentas.",
      );
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  async function prepare() {
    if (!account || lock.current || hasSubmission) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await request<Preview>(
        `${prefix}/review-preview`,
        "POST",
        { version: record.version, account_id: account },
      );
      setPreview(result);
      setConfirmed(false);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos preparar la revisión.",
      );
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  async function submit() {
    if (!preview || !confirmed || attempted || lock.current || hasSubmission)
      return;
    lock.current = true;
    setBusy(true);
    setError("");
    setAttempted(true);
    try {
      const result = await request<CampaignReview>(
        `${prefix}/reviews`,
        "POST",
        { version: record.version, account_id: account, confirm: true },
      );
      setHistory((previous) =>
        [result, ...previous.filter((row) => row.id !== result.id)].slice(
          0,
          20,
        ),
      );
      onReview(result);
      setMessage(
        result.status === "UNKNOWN" || result.status === "SUBMITTING"
          ? "Solicitud registrada. Falta confirmar el resultado: actualiza su estado, no la reenvíes."
          : "Solicitud registrada en Zernio. El estado mostrado corresponde a su respuesta; no se envió ningún mensaje.",
      );
      dialog.current?.close();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos confirmar el resultado. Consulta el historial antes de continuar.",
      );
      await loadHistory();
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  async function refresh(row: CampaignReview) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await request<CampaignReview>(
        `${prefix}/reviews/${row.id}/refresh`,
        "POST",
        {},
      );
      setHistory((previous) =>
        previous.map((item) => (item.id === result.id ? result : item)),
      );
      if (result.id === latest?.id) onReview(result);
      setMessage(
        "Estado consultado en Zernio. No se volvió a enviar la plantilla.",
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos consultar el estado.",
      );
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  const errorNode = error ? (
    <p className="crm-error" role="alert">
      {error}
    </p>
  ) : null;
  return (
    <section className="campaign-reviews" aria-label="Revisión de Meta">
      <div className="campaign-review-heading">
        <div>
          <strong>Revisión de Meta</strong>
          <small>
            {latest
              ? `${campaignReviewLabels[latest.status] ?? latest.status} · Versión ${latest.version}${latest.version !== record.version ? " · Hay cambios locales posteriores" : ""}`
              : "Sin solicitudes · El borrador sigue siendo privado"}
          </small>
        </div>
        <button
          className="crm-button crm-secondary"
          disabled={disabled || busy || !loaded || record.version < 1}
          onClick={() => void open()}
        >
          Enviar a revisión
        </button>
      </div>
      {(disabled || record.version < 1) && (
        <p className="campaign-muted">
          Guarda los cambios antes de preparar la revisión.
        </p>
      )}
      {!isOpen && errorNode}
      {!loaded && (
        <button
          className="crm-button crm-secondary"
          disabled={busy}
          onClick={() => void loadHistory()}
        >
          Cargar historial
        </button>
      )}
      <p role="status" className="campaign-muted">
        {message || (busy && !isOpen ? "Consultando…" : "")}
      </p>
      {!!history.length && (
        <details className="campaign-review-history">
          <summary>Historial de revisiones ({history.length})</summary>
          {history.map((row) => (
            <article key={row.id}>
              <div className="campaign-review-heading">
                <div>
                  <strong>
                    {campaignReviewLabels[row.status] ?? row.status}
                  </strong>
                  <small>
                    Versión {row.version} · {row.account_label}
                  </small>
                </div>
                <button
                  className="crm-button crm-secondary"
                  disabled={busy}
                  onClick={() => void refresh(row)}
                >
                  Actualizar estado
                </button>
              </div>
              <p className="campaign-muted">
                {row.name}
                <br />
                {row.category ?? "MARKETING"} · es_CO ·{" "}
                {row.checked_at
                  ? `Consultada: ${new Date(row.checked_at).toLocaleString("es-CO")}`
                  : "Resultado aún no confirmado"}
              </p>
              {(row.status === "UNKNOWN" || row.status === "SUBMITTING") && (
                <p className="campaign-review-warning">
                  La solicitud podría existir en Meta. Consulta el estado; esta
                  versión no se reenviará.
                </p>
              )}
              {row.status === "REJECTED" && (
                <p className="campaign-muted">
                  Consulta el motivo en WhatsApp Manager. Corrige y guarda una
                  nueva versión para solicitar otra revisión.
                </p>
              )}
              <details>
                <summary>Ver contenido enviado</summary>
                {row.snapshot.image_id && (
                  <img
                    className="campaign-review-image"
                    src={campaignMedia(row.snapshot.image_id)}
                    alt="Imagen de la versión enviada"
                    loading="lazy"
                  />
                )}
                <p className="campaign-review-body">
                  {renderCampaignText(
                    row.snapshot.body,
                    row.snapshot.variables,
                  )}
                </p>
                {row.snapshot.buttons.map((button, index) => (
                  <p key={index} className="campaign-muted">
                    {button.label} ·{" "}
                    {button.kind === "url"
                      ? renderCampaignText(button.value, row.snapshot.variables)
                      : `Respuesta: ${button.value}`}
                  </p>
                ))}
              </details>
            </article>
          ))}
        </details>
      )}
      <dialog
        ref={dialog}
        tabIndex={-1}
        className="campaign-review-dialog"
        onClose={() => setIsOpen(false)}
        aria-labelledby="campaign-review-title"
        onCancel={(event) => {
          if (lock.current) event.preventDefault();
        }}
      >
        <header>
          <h2 id="campaign-review-title">Enviar esta versión a Meta</h2>
          <button
            ref={closeButton}
            autoFocus
            className="crm-button crm-secondary"
            disabled={busy}
            onClick={() => dialog.current?.close()}
            aria-label="Cerrar revisión"
          >
            Cerrar
          </button>
        </header>
        <p>
          Se enviará únicamente la versión guardada {record.version} a revisión,
          usando la conexión de Zernio. No se enviarán mensajes ni se
          programarán campañas.
        </p>
        <label>
          Cuenta de WhatsApp
          <select
            value={account}
            disabled={busy || attempted}
            onChange={(event) => {
              setAccount(event.target.value);
              setPreview(null);
              setConfirmed(false);
              setError("");
            }}
          >
            <option value="">Selecciona una cuenta</option>
            {accounts.map((item) => (
              <option value={item.id} key={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {!busy && !accounts.length && (
          <p className="campaign-review-warning">
            No hay cuentas disponibles. Conecta una cuenta de WhatsApp Business
            en Configuración → Conexiones.
          </p>
        )}
        {hasSubmission && (
          <p className="campaign-review-warning">
            Esta versión ya tiene una solicitud para esta cuenta. Cierra este
            panel y actualiza su estado en el historial.
          </p>
        )}
        {!preview && (
          <button
            className="crm-button"
            disabled={busy || !account || hasSubmission || attempted}
            onClick={() => void prepare()}
          >
            {busy ? "Consultando…" : "Revisar contenido"}
          </button>
        )}
        {preview && (
          <div className="campaign-review-confirmation">
            <p className="campaign-muted">
              Nombre en Meta: <code>{preview.name}</code>
              <br />
              Marketing · Español (Colombia) · {preview.account.label}
            </p>
            {record.document.image_id && (
              <img
                className="campaign-review-image"
                src={campaignMedia(record.document.image_id)}
                alt="Imagen que se compartirá para revisión"
              />
            )}
            <p className="campaign-review-body">
              {renderCampaignText(
                record.document.body,
                record.document.variables,
              )}
            </p>
            {record.document.buttons.map((button, index) => (
              <p className="campaign-muted" key={index}>
                <strong>{button.label}</strong> ·{" "}
                {button.kind === "url"
                  ? renderCampaignText(button.value, record.document.variables)
                  : "Respuesta rápida"}
              </p>
            ))}
            <p className="campaign-muted">
              Los valores de las variables son ejemplos para Meta. Los enlaces
              variables conservan su dominio y permiten variar la ruta al
              enviar. Las claves de respuesta se conservan en el CRM; no crean
              automatizaciones.
            </p>
            {record.document.image_id && (
              <p className="campaign-review-warning">
                La imagen seleccionada se compartirá con Zernio y Meta mediante
                un enlace exclusivo que vence en 15 minutos.
              </p>
            )}
            <label className="campaign-review-consent">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={busy || attempted}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              Confirmo enviar esta versión y sus ejemplos a revisión de Meta.
            </label>
            <button
              className="crm-button"
              disabled={!confirmed || busy || attempted || hasSubmission}
              onClick={() => void submit()}
            >
              {busy ? "Registrando solicitud…" : "Confirmar envío a revisión"}
            </button>
          </div>
        )}
        {errorNode}
        {attempted && error && (
          <p className="campaign-review-warning">
            No se reintentará automáticamente. Cierra este panel y consulta el
            historial antes de continuar.
          </p>
        )}
      </dialog>
    </section>
  );
}
