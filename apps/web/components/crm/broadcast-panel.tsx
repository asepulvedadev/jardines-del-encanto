"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./icon";
import {
  broadcastErrors,
  broadcastStates,
  csvHeaders,
  type BroadcastRecord,
  type BroadcastTemplate,
} from "./broadcast-model";
import "./broadcast-panel.css";

type Preview = {
  recipients: { name: string; phone: string }[];
  duplicates: number;
  invalid: { row: number; reason: string }[];
};
export function BroadcastPanel({
  csrf,
  onChanged,
}: {
  csrf: string;
  onChanged: () => Promise<void>;
}) {
  const [rows, setRows] = useState<BroadcastRecord[]>([]),
    [accounts, setAccounts] = useState<{ id: string; name: string }[]>([]);
  const [selected, setSelected] = useState<BroadcastRecord | null>(null),
    [opened, setOpened] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const [name, setName] = useState(""),
    [account, setAccount] = useState(""),
    [templates, setTemplates] = useState<BroadcastTemplate[]>([]),
    [templateKey, setTemplateKey] = useState("");
  const [csv, setCsv] = useState(""),
    [headers, setHeaders] = useState<string[]>([]),
    [nameColumn, setNameColumn] = useState(""),
    [phoneColumn, setPhoneColumn] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null),
    [values, setValues] = useState<Record<string, string>>({}),
    [consent, setConsent] = useState(false),
    [evidence, setEvidence] = useState(""),
    [confirmation, setConfirmation] = useState("");
  const editor = useRef<HTMLDialogElement>(null),
    review = useRef<HTMLDialogElement>(null),
    lock = useRef(false),
    requestId = useRef("");
  const template = templates.find(
    (t) => `${t.name}:${t.language}` === templateKey,
  );
  const request = useCallback(
    async <T,>(
      path: string,
      method = "GET",
      body?: unknown,
      signal?: AbortSignal,
    ): Promise<T> => {
      const response = await fetch(`/api/crm/broadcasts${path}`, {
        method,
        cache: "no-store",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
        signal: signal ?? AbortSignal.timeout(100000),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          response.status === 401
            ? "Tu sesión finalizó. Recarga e ingresa de nuevo."
            : (broadcastErrors[result.detail] ??
                "No se completó la solicitud. No repitas un envío sin revisar primero su estado."),
        );
      return result;
    },
    [csrf],
  );
  const load = useCallback(async () => {
    const result = await request<{ items: BroadcastRecord[] }>("");
    setRows(result.items);
  }, [request]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    void load()
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [load]);
  useEffect(() => {
    if (!opened) return;
    let active = true;
    void request<{ accounts: { id: string; name: string }[] }>("/catalog")
      .then((r) => {
        if (active) setAccounts(r.accounts);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [opened, request]);
  useEffect(() => {
    setTemplates([]);
    setTemplateKey("");
    setValues({});
    if (!account) return;
    const controller = new AbortController();
    void request<{ items: BroadcastTemplate[] }>(
      "/templates",
      "POST",
      { account_id: account },
      controller.signal,
    )
      .then((r) => setTemplates(r.items))
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [account, request]);
  useEffect(() => {
    if (opened) editor.current?.showModal();
  }, [opened]);
  useEffect(() => {
    if (selected) {
      setConfirmation("");
      review.current?.showModal();
    }
  }, [selected?.id]);
  async function action(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No se pudo completar la solicitud.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function newCampaign() {
    if (lock.current) return;
    requestId.current = crypto.randomUUID();
    setName("");
    setCsv("");
    setHeaders([]);
    setPreview(null);
    setValues({});
    setConsent(false);
    setEvidence("");
    setError("");
    setNotice("");
    setOpened(true);
  }
  async function fileChanged(file?: File) {
    setPreview(null);
    setCsv("");
    setHeaders([]);
    if (!file) return;
    if (file.size > 512000) {
      setError(broadcastErrors.broadcast_csv_too_large);
      return;
    }
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      const cols = csvHeaders(text);
      setCsv(text);
      setHeaders(cols);
      setNameColumn(
        cols.find((c) => /^(nombre|name|nombre completo)$/i.test(c)) ??
          cols[0] ??
          "",
      );
      setPhoneColumn(
        cols.find((c) =>
          /^(celular|telefono|teléfono|phone|whatsapp)$/i.test(c),
        ) ??
          cols[1] ??
          "",
      );
      setError("");
    } catch {
      setError("Guarda el CSV con codificación UTF-8 antes de importarlo.");
    }
  }
  async function save() {
    await action(async () => {
      if (!template || !preview || preview.invalid.length) return;
      const result = await request<BroadcastRecord>("", "POST", {
        id: requestId.current,
        name,
        account_id: account,
        template_name: template.name,
        template_language: template.language,
        values,
        csv_text: csv,
        name_column: nameColumn,
        phone_column: phoneColumn,
        consent_confirmed: consent,
        consent_note: evidence,
      });
      editor.current?.close();
      setOpened(false);
      setSelected(result);
      await load();
      await onChanged();
      setNotice(
        "Leads y etiquetas guardados. Aún no se ha enviado ningún mensaje.",
      );
    });
  }
  async function openRow(id: string) {
    await action(async () =>
      setSelected(await request<BroadcastRecord>(`/${id}`)),
    );
  }
  async function refresh() {
    if (!selected) return;
    await action(async () => {
      setSelected(
        await request<BroadcastRecord>(`/${selected.id}/refresh`, "POST"),
      );
      await load();
    });
  }
  async function send() {
    if (!selected || confirmation !== `ENVIAR ${selected.recipient_count}`)
      return;
    await action(async () => {
      setSelected(
        await request<BroadcastRecord>(`/${selected.id}/send`, "POST", {
          version: selected.version,
          count: selected.recipient_count,
          confirmed: true,
        }),
      );
      setConfirmation("");
      await load();
      await onChanged();
    });
  }
  const cardText = template?.body.replace(
    /\{\{(\d+)\}\}/g,
    (full, n) => values[`body:${n}`] || full,
  );
  return (
    <section className="crm-broadcasts" aria-labelledby="broadcast-title">
      <div className="crm-page-heading">
        <div>
          <span className="crm-eyebrow">WHATSAPP · ZERNIO</span>
          <h1 id="broadcast-title">Envíos masivos</h1>
          <p>Una base, una plantilla aprobada y cada envío en su lugar.</p>
        </div>
        <button className="crm-button" onClick={newCampaign}>
          <Icon name="plus" size={16} />
          Nueva campaña
        </button>
      </div>
      {error && !opened && !selected && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      {notice && !selected && <p role="status">{notice}</p>}
      <div className="crm-broadcast-intro">
        <div>
          <strong>01</strong>
          <span>Importa tu CSV</span>
        </div>
        <div>
          <strong>02</strong>
          <span>Revisa la plantilla</span>
        </div>
        <div>
          <strong>03</strong>
          <span>Confirma el envío</span>
        </div>
      </div>
      <section className="crm-panel">
        <h2>Campañas de WhatsApp</h2>
        {loading ? (
          <p role="status">Cargando campañas…</p>
        ) : rows.length === 0 ? (
          <div className="crm-broadcast-empty">
            <Icon name="message" size={28} />
            <h3>Tu próxima conversación empieza aquí.</h3>
            <p>
              Importa contactos con autorización y conserva cada campaña como
              una etiqueta filtrable.
            </p>
            <button className="crm-button crm-secondary" onClick={newCampaign}>
              Importar CSV
            </button>
          </div>
        ) : (
          <div className="crm-table-scroll">
            <table className="crm-table">
              <thead>
                <tr>
                  <th>Campaña</th>
                  <th>Estado</th>
                  <th>Contactos</th>
                  <th>Enviados</th>
                  <th>Entregados</th>
                  <th>Leídos</th>
                  <th>
                    <span className="sr-only">Abrir</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <button
                        className="crm-broadcast-link"
                        onClick={() => void openRow(row.id)}
                      >
                        {row.name}
                      </button>
                      <small>
                        {row.template_name} · {row.template_language}
                      </small>
                    </td>
                    <td>{broadcastStates[row.state] ?? "Revisar estado"}</td>
                    <td>{row.recipient_count}</td>
                    <td>{row.stats.sentCount ?? "—"}</td>
                    <td>{row.stats.deliveredCount ?? "—"}</td>
                    <td>{row.stats.readCount ?? "—"}</td>
                    <td>
                      <button
                        className="crm-icon-button"
                        aria-label={`Abrir campaña ${row.name}`}
                        onClick={() => void openRow(row.id)}
                      >
                        <Icon name="chevron" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <dialog
        ref={editor}
        className="crm-modal crm-broadcast-modal"
        aria-labelledby="broadcast-editor-title"
        onCancel={(event) => {
          if (busy) event.preventDefault();
        }}
        onClose={() => setOpened(false)}
      >
        <div className="crm-modal-header">
          <div>
            <span className="crm-eyebrow">NUEVA CAMPAÑA</span>
            <h2 id="broadcast-editor-title">De tu base a una conversación.</h2>
          </div>
          <button
            className="crm-icon-button"
            disabled={busy}
            aria-label="Cerrar nueva campaña"
            onClick={() => editor.current?.close()}
          >
            <Icon name="close" />
          </button>
        </div>
        <form
          className="crm-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={busy}>
            <div className="crm-broadcast-fields">
              <label>
                Nombre de la campaña
                <input
                  required
                  maxLength={120}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Invitación feria · noviembre"
                />
              </label>
              <label>
                Número remitente
                <select
                  required
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                >
                  <option value="">Selecciona WhatsApp</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <section className="crm-broadcast-step">
              <h3>1. Tu base de contactos</h3>
              <label>
                Archivo CSV · UTF-8 · hasta 500 filas
                <input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => void fileChanged(e.target.files?.[0])}
                />
              </label>
              <p className="crm-subtle">
                Usa encabezados, por ejemplo: nombre,celular. No incluyas
                personas que hayan solicitado no recibir mensajes.
              </p>
              {!!headers.length && (
                <>
                  <div className="crm-broadcast-fields">
                    <label>
                      Columna de nombre
                      <select
                        value={nameColumn}
                        onChange={(e) => {
                          setNameColumn(e.target.value);
                          setPreview(null);
                        }}
                      >
                        {headers.map((h, i) => (
                          <option key={i} value={h}>
                            {h}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Columna de celular
                      <select
                        value={phoneColumn}
                        onChange={(e) => {
                          setPhoneColumn(e.target.value);
                          setPreview(null);
                        }}
                      >
                        {headers.map((h, i) => (
                          <option key={i} value={h}>
                            {h}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <button
                    type="button"
                    className="crm-button crm-secondary"
                    onClick={() =>
                      void action(async () =>
                        setPreview(
                          await request<Preview>("/preview", "POST", {
                            csv_text: csv,
                            name_column: nameColumn,
                            phone_column: phoneColumn,
                          }),
                        ),
                      )
                    }
                  >
                    Validar archivo
                  </button>
                </>
              )}
              {preview && (
                <div aria-live="polite">
                  <p>
                    <strong>{preview.recipients.length}</strong> contactos
                    únicos · <strong>{preview.duplicates}</strong> duplicados
                    omitidos · <strong>{preview.invalid.length}</strong> filas
                    por corregir
                  </p>
                  {!!preview.invalid.length && (
                    <p className="crm-error">
                      Corrige las filas{" "}
                      {preview.invalid.map((r) => r.row).join(", ")} y vuelve a
                      cargar el archivo.
                    </p>
                  )}
                  <div className="crm-broadcast-sample">
                    {preview.recipients.slice(0, 5).map((r) => (
                      <div key={r.phone}>
                        <span>{r.name}</span>
                        <span>{r.phone}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
            <section className="crm-broadcast-step">
              <h3>2. Plantilla aprobada</h3>
              <label>
                Plantilla
                <select
                  required
                  value={templateKey}
                  onChange={(e) => {
                    setTemplateKey(e.target.value);
                    setValues({});
                  }}
                >
                  <option value="">
                    {account
                      ? "Selecciona una plantilla"
                      : "Primero selecciona el remitente"}
                  </option>
                  {templates.map((t) => (
                    <option
                      disabled={!!t.issue}
                      key={`${t.name}:${t.language}`}
                      value={`${t.name}:${t.language}`}
                    >
                      {t.name} · {t.language}
                      {t.issue ? " · formato no compatible" : ""}
                    </option>
                  ))}
                </select>
              </label>
              {template && (
                <>
                  <div className="crm-broadcast-fields">
                    {template.fields.map((f) => (
                      <label key={f.key}>
                        {f.label}
                        <input
                          type={f.kind === "text" ? "text" : "url"}
                          required
                          maxLength={1024}
                          value={values[f.key] ?? ""}
                          onChange={(e) =>
                            setValues((v) => ({
                              ...v,
                              [f.key]: e.target.value,
                            }))
                          }
                          placeholder={
                            f.kind === "text"
                              ? "Valor para todos los destinatarios"
                              : "https://…"
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <div className="crm-broadcast-preview">
                    <span>VISTA PREVIA · {template.category}</span>
                    <p>{cardText}</p>
                    <small>Los valores son comunes para toda la campaña.</small>
                  </div>
                </>
              )}
            </section>
            <section className="crm-broadcast-step">
              <h3>3. Autorización y trazabilidad</h3>
              <label className="crm-broadcast-check">
                <input
                  type="checkbox"
                  checked={consent}
                  required
                  onChange={(e) => setConsent(e.target.checked)}
                />
                Confirmo que estos contactos autorizaron recibir mensajes
                comerciales por WhatsApp.
              </label>
              <label>
                Origen de la autorización
                <input
                  required
                  minLength={8}
                  maxLength={500}
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                  placeholder="Formulario de autorización de la feria, fecha…"
                />
              </label>
              <p className="crm-subtle">
                Los contactos nuevos entran como leads en frío. Los existentes
                conservan su origen y etapa. Guardar no envía mensajes.
              </p>
            </section>
          </fieldset>
          {error && (
            <p className="crm-error" role="alert">
              {error}
            </p>
          )}
          <div className="crm-form-actions">
            <button
              className="crm-button crm-secondary"
              type="button"
              disabled={busy}
              onClick={() => editor.current?.close()}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="crm-button"
              disabled={
                busy ||
                !preview ||
                !!preview.invalid.length ||
                !template ||
                !!template.issue
              }
            >
              {busy ? "Guardando…" : "Guardar y revisar envío"}
            </button>
          </div>
        </form>
      </dialog>
      <dialog
        ref={review}
        className="crm-modal crm-broadcast-modal"
        aria-labelledby="broadcast-review-title"
        onCancel={(event) => {
          if (busy) event.preventDefault();
        }}
        onClose={() => {
          setSelected(null);
          setError("");
        }}
      >
        {selected && (
          <>
            <div className="crm-modal-header">
              <div>
                <span className="crm-eyebrow">
                  {broadcastStates[selected.state] ?? "CAMPAÑA"}
                </span>
                <h2 id="broadcast-review-title">{selected.name}</h2>
              </div>
              <button
                disabled={busy}
                className="crm-icon-button"
                aria-label="Cerrar campaña"
                onClick={() => review.current?.close()}
              >
                <Icon name="close" />
              </button>
            </div>
            <div className="crm-form">
              <div className="crm-broadcast-fields">
                <p>
                  <strong>{selected.recipient_count}</strong> contactos en el
                  CRM
                </p>
                <p>
                  Etiqueta: <strong>{selected.name}</strong>
                </p>
              </div>
              <div className="crm-broadcast-preview">
                <span>
                  {selected.template_name} · {selected.template_language}
                </span>
                <p>{selected.preview}</p>
              </div>
              {notice && <p role="status">{notice}</p>}
              {error && (
                <p className="crm-error" role="alert">
                  {error}
                </p>
              )}
              {selected.state === "draft" ? (
                <>
                  <p>
                    Al confirmar, Zernio enviará esta plantilla. Se aplican sus
                    tarifas, las de Meta y los límites de tu número. Zernio
                    excluirá del segmento los contactos no suscritos.
                  </p>
                  <label>
                    Escribe ENVIAR {selected.recipient_count} para confirmar
                    <input
                      value={confirmation}
                      disabled={busy}
                      onChange={(e) => setConfirmation(e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                  <button
                    className="crm-button"
                    disabled={
                      busy ||
                      confirmation !== `ENVIAR ${selected.recipient_count}`
                    }
                    onClick={() => void send()}
                  >
                    {busy ? "Procesando en Zernio…" : "Confirmar y enviar"}
                  </button>
                </>
              ) : (
                <>
                  <div className="crm-broadcast-fields">
                    {[
                      ["sentCount", "Enviados"],
                      ["deliveredCount", "Entregados"],
                      ["readCount", "Leídos"],
                      ["failedCount", "Fallidos"],
                    ].map(([key, label]) => (
                      <p key={key}>
                        {label}
                        <strong className="crm-broadcast-count">
                          {selected.stats[key] ?? "—"}
                        </strong>
                      </p>
                    ))}
                  </div>
                  {["preparing", "sending", "unknown"].includes(
                    selected.state,
                  ) && (
                    <p className="crm-error">
                      No repitas esta campaña. Puede existir una operación en
                      Zernio pendiente de verificar. Consulta su estado antes de
                      cualquier nuevo envío.
                    </p>
                  )}
                  <button
                    className="crm-button crm-secondary"
                    disabled={busy}
                    onClick={() => void refresh()}
                  >
                    {busy ? "Consultando…" : "Consultar entrega en Zernio"}
                  </button>
                </>
              )}
              {!!selected.recipients?.length && (
                <details>
                  <summary>Ver contactos y etiquetas</summary>
                  <div className="crm-broadcast-sample">
                    {selected.recipients.map((r) => (
                      <div key={r.contact_id}>
                        <span>
                          {r.name}
                          <small>
                            {r.cold ? "Lead en frío" : "Cliente existente"}
                          </small>
                        </span>
                        <span>{r.phone}</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          </>
        )}
      </dialog>
    </section>
  );
}
