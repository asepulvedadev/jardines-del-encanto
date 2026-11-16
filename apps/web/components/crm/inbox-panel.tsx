"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { Icon } from "./icon";
import { InboxFields, inboxFieldValues } from "./inbox-fields";
import { LeadCaptureStatus } from "./lead-capture-status";
import {
  inboxSections,
  inboxPlatforms,
  inboxOperationLabels,
  inboxStates,
  inboxErrors,
  inboxRows,
  inboxCursor,
  inboxPartial,
  inboxTitle,
  inboxBody,
  inboxText,
  inboxRowId,
  inboxTime,
  inboxSafeLink,
  type InboxAccount,
  type InboxCommand,
  type InboxOperation,
  type InboxPlan,
  type InboxResult,
  type InboxRow,
  type InboxSection,
} from "./inbox-types";
import "../../app/crm/inbox.css";

type Request = <T>(
  path: string,
  payload?: unknown,
  signal?: AbortSignal,
) => Promise<T>;
const listOperations: Record<InboxSection, string> = {
  messages: "listInboxConversations",
  comments: "listInboxComments",
  mentions: "listInboxMentions",
  reviews: "listInboxReviews",
};
const operationName = (key: string) => inboxOperationLabels[key] ?? key;
function InboxDialog({
  open,
  title,
  onClose,
  busy = false,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  busy?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const trigger = useRef<Element | null>(null);
  useEffect(() => {
    if (open) {
      trigger.current = document.activeElement;
      ref.current?.showModal();
    } else if (ref.current?.open) {
      ref.current.close();
      if (trigger.current instanceof HTMLElement) trigger.current.focus();
    }
  }, [open]);
  return (
    <dialog
      className="inbox-dialog"
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button
          className="crm-icon-button"
          aria-label="Cerrar"
          disabled={busy}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </header>
      {children}
    </dialog>
  );
}
function RawDetails({
  value,
  title = "Datos de Zernio",
}: {
  value: unknown;
  title?: string;
}) {
  return (
    <details className="inbox-raw">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function InboxPanel({
  csrf,
  active = true,
  onDirtyChange,
  onOpenConnections,
}: {
  csrf: string;
  active?: boolean;
  onDirtyChange: (dirty: boolean) => void;
  onOpenConnections: () => void;
}) {
  const router = useRouter();
  const [accounts, setAccounts] = useState<InboxAccount[]>([]);
  const [catalog, setCatalog] = useState<Record<string, InboxOperation>>({});
  const [accountId, setAccountId] = useState("");
  const [channel, setChannel] = useState("all");
  const [section, setSection] = useState<InboxSection>("messages");
  const [filter, setFilter] = useState("");
  const [status, setStatus] = useState("active");
  const [folder, setFolder] = useState("inbox");
  const [items, setItems] = useState<InboxRow[]>([]);
  const [result, setResult] = useState<InboxResult>({});
  const [selected, setSelected] = useState<InboxRow | null>(null);
  const [thread, setThread] = useState<InboxResult>({});
  const [loading, setLoading] = useState(true);
  const [threadLoading, setThreadLoading] = useState(false);
  const [error, setError] = useState("");
  const [threadError, setThreadError] = useState("");
  const [notice, setNotice] = useState("");
  const [listBusy, setListBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [updated, setUpdated] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [attachments, setAttachments] = useState<
    Record<string, { url: string; kind: string }>
  >({});
  const [replyComment, setReplyComment] = useState<InboxRow | null>(null);
  const [plan, setPlan] = useState<InboxPlan | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [tools, setTools] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<InboxPlan[]>([]);
  const lock = useRef(false);
  const listSequence = useRef(0);
  const threadSequence = useRef(0);
  const scroll = useRef<HTMLDivElement>(null);
  const confirmedDraft = useRef<{
    key: string;
    text: string;
    attachment: string;
  } | null>(null);
  const account = accounts.find((a) => a.id === accountId);
  const visibleAccounts = accounts.filter(
    (a) => channel === "all" || a.platform === channel,
  );
  const threadKey = `${accountId}:${section}:${selected ? inboxRowId(selected) : ""}`;
  const draft = drafts[threadKey] ?? "";
  const attachment = attachments[threadKey]?.url ?? "";
  const attachmentType = attachments[threadKey]?.kind ?? "image";
  const setAttachment = (url: string) =>
    setAttachments((old) => ({
      ...old,
      [threadKey]: { url, kind: old[threadKey]?.kind ?? "image" },
    }));
  const setAttachmentType = (kind: string) =>
    setAttachments((old) => ({
      ...old,
      [threadKey]: { url: old[threadKey]?.url ?? "", kind },
    }));
  const dirty =
    Object.values(drafts).some(Boolean) ||
    Object.values(attachments).some((item) => !!item.url);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const before = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, [dirty]);
  const request: Request = useCallback(
    async (path, payload, signal) => {
      const response = await fetch(`/api/crm/inbox/${path}`, {
        method: payload === undefined ? "GET" : "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal,
      });
      if (response.status === 401) {
        router.replace("/login");
        router.refresh();
        throw new Error("La sesión expiró. Vuelve a ingresar.");
      }
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          inboxErrors[data.detail] ??
            "No pudimos completar la operación. Revisa el historial antes de repetir un envío.",
        );
      return data;
    },
    [csrf, router],
  );
  const read = useCallback(
    (
      operation: string,
      path: Record<string, unknown> = {},
      query: Record<string, unknown> = {},
      signal?: AbortSignal,
    ) =>
      request<InboxResult>(
        "read",
        { operation, account_id: accountId, path, query },
        signal,
      ),
    [accountId, request],
  );
  const loadAccounts = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError("");
      try {
        const [config, rows] = await Promise.all([
          request<{ operations: Record<string, InboxOperation> }>(
            "catalog",
            undefined,
            signal,
          ),
          request<{ items: InboxAccount[] }>("accounts", undefined, signal),
        ]);
        if (signal?.aborted) return;
        setCatalog(config.operations);
        setAccounts(rows.items);
        setAccountId((old) =>
          rows.items.some((a) => a.id === old)
            ? old
            : (rows.items.find((a) => a.active)?.id ?? ""),
        );
      } catch (cause) {
        if (!signal?.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "No pudimos cargar las cuentas.",
          );
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [request],
  );
  useEffect(() => {
    const c = new AbortController();
    void loadAccounts(c.signal);
    return () => c.abort();
  }, [loadAccounts]);
  const list = useCallback(
    async (cursor?: string, signal?: AbortSignal) => {
      if (!accountId) return;
      const version = ++listSequence.current;
      setListBusy(true);
      setError("");
      try {
        const query: Record<string, unknown> = {
          limit: 30,
          sortOrder: "desc",
          ...(cursor ? { cursor } : {}),
        };
        if (section === "messages") {
          query.status = status;
          query.folder = folder;
        }
        const data = await read(listOperations[section], {}, query, signal);
        if (signal?.aborted || version !== listSequence.current) return;
        const rows = inboxRows(data);
        setResult(data);
        setItems((old) =>
          cursor
            ? [
                ...old,
                ...rows.filter(
                  (row) =>
                    !old.some((item) => inboxRowId(item) === inboxRowId(row)),
                ),
              ]
            : rows,
        );
        setUpdated(new Date().toISOString());
      } catch (cause) {
        if (!signal?.aborted && version === listSequence.current)
          setError(
            cause instanceof Error
              ? cause.message
              : "No pudimos cargar la bandeja.",
          );
      } finally {
        if (!signal?.aborted && version === listSequence.current)
          setListBusy(false);
      }
    },
    [accountId, section, status, folder, read],
  );
  useEffect(() => {
    setItems([]);
    setResult({});
    setSelected(null);
    setThread({});
    setReplyComment(null);
    const c = new AbortController();
    void list(undefined, c.signal);
    return () => {
      c.abort();
      listSequence.current++;
    };
  }, [list]);
  const loadThread = useCallback(
    async (cursor?: string, signal?: AbortSignal) => {
      if (!selected || !accountId) return;
      const version = ++threadSequence.current;
      setThreadLoading(true);
      setThreadError("");
      if (section === "reviews" || section === "mentions") {
        setThread({ data: selected });
        setThreadLoading(false);
        return;
      }
      try {
        const data = await read(
          section === "messages"
            ? "getInboxConversationMessages"
            : "getInboxPostComments",
          section === "messages"
            ? { conversationId: inboxRowId(selected) }
            : { postId: inboxRowId(selected) },
          {
            limit: 50,
            ...(section === "messages" ? { sortOrder: "desc" } : {}),
            ...(cursor ? { cursor } : {}),
          },
          signal,
        );
        if (signal?.aborted || version !== threadSequence.current) return;
        if (cursor) {
          const key = section === "messages" ? "messages" : "comments";
          setThread((old) => ({
            ...data,
            [key]: [
              ...inboxRows(old, key),
              ...inboxRows(data, key).filter(
                (row) =>
                  !inboxRows(old, key).some(
                    (item) => inboxRowId(item) === inboxRowId(row),
                  ),
              ),
            ],
          }));
        } else setThread(data);
      } catch (cause) {
        if (!signal?.aborted && version === threadSequence.current)
          setThreadError(
            cause instanceof Error
              ? cause.message
              : "No pudimos cargar los mensajes.",
          );
      } finally {
        if (!signal?.aborted && version === threadSequence.current)
          setThreadLoading(false);
      }
    },
    [accountId, selected, section, read],
  );
  useEffect(() => {
    setThread({});
    setReplyComment(null);
    const c = new AbortController();
    void loadThread(undefined, c.signal);
    return () => {
      c.abort();
      threadSequence.current++;
    };
  }, [loadThread]);
  useEffect(() => {
    if (!active || !accountId || busy || tools || plan || dirty) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void list();
        if (selected) void loadThread();
      }
    }, 30000);
    return () => window.clearInterval(timer);
  }, [active, accountId, busy, tools, plan, dirty, list, loadThread, selected]);
  useEffect(() => {
    if (refreshKey) {
      void list();
      if (selected) void loadThread();
    }
  }, [refreshKey, list, loadThread, selected]);
  const choose = (row: InboxRow) => {
    setSelected(row);
    setThreadError("");
  };
  async function prepare(command: InboxCommand) {
    if (lock.current || !account?.active) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await request<InboxPlan>("prepare", command);
      setPlan(next);
      setConfirmed(false);
      setAttempted(false);
      setTools(false);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos preparar la acción.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function send() {
    if (!plan || !confirmed || attempted || lock.current) return;
    lock.current = true;
    setBusy(true);
    setAttempted(true);
    setError("");
    try {
      const response = await request<{ state: string; error?: string }>(
        `actions/${plan.id}/confirm`,
        { confirmed: true },
      );
      setNotice(inboxStates[response.state] ?? response.state);
      setPlan({ ...plan, state: response.state, error: response.error });
      if (response.state === "sent") {
        const saved = confirmedDraft.current;
        if (saved)
          setDrafts((old) =>
            old[saved.key] === saved.text ? { ...old, [saved.key]: "" } : old,
          );
        if (saved)
          setAttachments((old) =>
            old[saved.key]?.url === saved.attachment
              ? { ...old, [saved.key]: { url: "", kind: "image" } }
              : old,
          );
        confirmedDraft.current = null;
        setRefreshKey((k) => k + 1);
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos confirmar el resultado.",
      );
      setNotice(
        "No repitas la acción. Consulta el historial y actualiza la conversación.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function reply() {
    if (!selected || (!draft.trim() && !attachment)) return;
    const path: Record<string, unknown> = {};
    const body: Record<string, unknown> = { message: draft };
    let operation = "sendInboxMessage";
    if (section === "messages") {
      path.conversationId = inboxRowId(selected);
      if (attachment) {
        body.attachmentUrl = attachment;
        body.attachmentType = attachmentType;
      }
      if (!draft.trim()) delete body.message;
    } else if (section === "comments") {
      operation = "replyToInboxPost";
      path.postId = inboxRowId(selected);
      if (replyComment) body.commentId = inboxRowId(replyComment);
    } else if (section === "reviews") {
      operation = "replyToInboxReview";
      path.reviewId = inboxRowId(selected);
    } else {
      operation = "replyToMention";
      body.mediaId = selected.mediaId;
      if (selected.commentId) body.commentId = selected.commentId;
    }
    confirmedDraft.current = { key: threadKey, text: draft, attachment };
    void prepare({ operation, account_id: accountId, path, body });
  }
  async function showHistory() {
    setError("");
    setHistoryOpen(true);
    try {
      setHistory((await request<{ items: InboxPlan[] }>("actions")).items);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos cargar el historial.",
      );
    }
  }
  function openTools() {
    setTools(true);
  }
  const rows = items.filter((row) =>
    `${inboxTitle(row)} ${inboxBody(row)}`
      .toLocaleLowerCase("es")
      .includes(filter.toLocaleLowerCase("es")),
  );
  const messages = inboxRows(
    thread,
    section === "messages" ? "messages" : "comments",
  );
  const orderedMessages =
    section === "messages"
      ? [...messages].sort((a, b) =>
          inboxText(a.createdAt).localeCompare(inboxText(b.createdAt)),
        )
      : messages;
  const replyAllowed =
    section !== "mentions" || account?.platform === "instagram";
  return (
    <section className="inbox-workspace" aria-label="Inbox multicanal">
      <div className="inbox-toolbar">
        <div>
          <strong>Una bandeja. Cada canal en su lugar.</strong>
          <span>
            {updated
              ? `Actualizado ${inboxTime(updated)} · Hora de Colombia`
              : "Mensajes y respuestas a través de Zernio"}
          </span>
        </div>
        <div className="inbox-toolbar-actions">
          <button
            className="crm-button crm-secondary"
            onClick={() => {
              void loadAccounts();
              setRefreshKey((k) => k + 1);
            }}
            disabled={loading || busy}
          >
            <Icon name="refresh" />
            Actualizar
          </button>
          <button className="crm-button crm-secondary" onClick={showHistory}>
            <Icon name="history" />
            Historial
          </button>
          <button
            className="crm-button"
            onClick={openTools}
            disabled={!account?.active || busy}
          >
            <Icon name="plus" />
            Herramientas
          </button>
        </div>
      </div>
      <LeadCaptureStatus request={request} active={active} />
      {error && (
        <p className="inbox-error" role="alert">
          {error}{" "}
          <button className="inbox-text-button" onClick={onOpenConnections}>
            Revisar conexiones
          </button>
        </p>
      )}
      {notice && (
        <p className="inbox-notice" role="status">
          {notice}
          <button
            className="inbox-text-button"
            aria-label="Cerrar resultado"
            onClick={() => setNotice("")}
          >
            Cerrar
          </button>
        </p>
      )}
      {loading ? (
        <p role="status">Consultando las cuentas conectadas…</p>
      ) : !accounts.length ? (
        <div className="inbox-empty">
          <Icon name="message" size={32} />
          <h2>Revisa la conexión de mensajería.</h2>
          <p>
            Revisa la clave API, el perfil y sus cuentas en Conexiones. Las
            redes vinculadas por OAuth no se desconectan ni se reemplazan.
          </p>
          <button className="crm-button" onClick={onOpenConnections}>
            Configurar Zernio
          </button>
        </div>
      ) : (
        <>
          <nav className="inbox-channel-tabs" aria-label="Canales conectados">
            {["all", ...new Set(accounts.map((a) => a.platform))].map(
              (platform) => (
                <button
                  key={platform}
                  aria-pressed={channel === platform}
                  onClick={() => {
                    setChannel(platform);
                    const next = accounts.find(
                      (a) =>
                        (platform === "all" || a.platform === platform) &&
                        a.active,
                    );
                    if (next) setAccountId(next.id);
                  }}
                >
                  {platform === "all"
                    ? "Todos los canales"
                    : (inboxPlatforms[platform] ?? platform)}
                  <span>
                    {platform === "all"
                      ? accounts.length
                      : accounts.filter((a) => a.platform === platform).length}
                  </span>
                </button>
              ),
            )}
          </nav>
          <div className="inbox-controls">
            <label>
              Cuenta
              <select
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              >
                {visibleAccounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} · {inboxPlatforms[a.platform] ?? a.platform}
                    {a.active ? "" : " · Requiere reconexión"}
                  </option>
                ))}
              </select>
            </label>
            <div
              role="group"
              aria-label="Tipo de entrada"
              className="inbox-section-tabs"
            >
              {Object.entries(inboxSections).map(([key, label]) => (
                <button
                  key={key}
                  aria-pressed={section === key}
                  onClick={() => setSection(key as InboxSection)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {!account?.active ? (
            <p className="inbox-error">
              Esta cuenta necesita reconexión antes de consultar o responder.
            </p>
          ) : (
            <div className={`inbox-layout ${selected ? "has-selection" : ""}`}>
              <aside
                className="inbox-thread-list"
                aria-label="Entradas del canal"
              >
                <div className="inbox-list-toolbar">
                  <label className="sr-only" htmlFor="inbox-search">
                    Filtrar entradas cargadas
                  </label>
                  <input
                    id="inbox-search"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Buscar en esta página…"
                  />
                  {section === "messages" && (
                    <div>
                      <label>
                        Estado
                        <select
                          value={status}
                          onChange={(e) => setStatus(e.target.value)}
                        >
                          <option value="active">Activas</option>
                          <option value="archived">Archivadas</option>
                        </select>
                      </label>
                      <label>
                        Carpeta
                        <select
                          value={folder}
                          onChange={(e) => setFolder(e.target.value)}
                        >
                          <option value="inbox">Principal</option>
                          <option value="requests">
                            Solicitudes · Facebook
                          </option>
                        </select>
                      </label>
                    </div>
                  )}
                </div>
                {listBusy && !items.length ? (
                  <p role="status">
                    Cargando {inboxSections[section].toLowerCase()}…
                  </p>
                ) : !rows.length ? (
                  <div className="inbox-empty">
                    <Icon name="message" size={28} />
                    <h3>
                      {filter
                        ? "Sin coincidencias"
                        : "No hay entradas disponibles"}
                    </h3>
                    <p>
                      {filter
                        ? "Prueba con otra búsqueda."
                        : "Zernio puede no tener mensajes para esta cuenta o no ofrecer este tipo de entrada. Revisa los permisos si esperabas contenido."}
                    </p>
                  </div>
                ) : (
                  rows.map((row, index) => (
                    <button
                      className={`inbox-thread-item ${selected && inboxRowId(selected) === inboxRowId(row) ? "is-selected" : ""}`}
                      key={`${inboxRowId(row)}:${index}`}
                      aria-pressed={
                        !!selected && inboxRowId(selected) === inboxRowId(row)
                      }
                      onClick={() => choose(row)}
                    >
                      <span className="inbox-avatar">
                        {inboxTitle(row).slice(0, 2).toUpperCase()}
                      </span>
                      <span className="inbox-thread-copy">
                        <strong>{inboxTitle(row)}</strong>
                        <span>
                          {inboxBody(row) ||
                            "Contenido no retenido o sin texto"}
                        </span>
                        <small>
                          {inboxTime(
                            row.updatedTime ??
                              row.publishedAt ??
                              row.createdAt ??
                              row.createdTime ??
                              row.created ??
                              row.date,
                          )}
                          {row.rating ? ` · ${inboxText(row.rating)} ★` : ""}
                        </small>
                      </span>
                      {Number(row.unreadCount) > 0 && (
                        <b className="inbox-unread">
                          {inboxText(row.unreadCount)}
                        </b>
                      )}
                    </button>
                  ))
                )}
                {inboxPartial(result) && (
                  <p className="inbox-warning">
                    Resultado parcial: algunos datos no están disponibles. No
                    significa que no haya mensajes.
                  </p>
                )}
                {inboxCursor(result) && (
                  <button
                    className="crm-button crm-secondary"
                    disabled={listBusy}
                    onClick={() => void list(inboxCursor(result)!)}
                  >
                    Cargar más entradas
                  </button>
                )}
                {!!(result.pagination as InboxRow | undefined)?.hasMore &&
                  !inboxCursor(result) && (
                    <p className="inbox-warning">
                      Zernio informa más entradas, sin cursor disponible. Acota
                      la cuenta o revisa el canal.
                    </p>
                  )}
                <RawDetails value={result} title="Estado de sincronización" />
              </aside>
              <div
                className="inbox-conversation"
                aria-label="Conversación seleccionada"
              >
                {!selected ? (
                  <div className="inbox-empty inbox-welcome">
                    <Icon name="message" size={40} />
                    <h2>Abre una conversación.</h2>
                    <p>
                      Lee el contexto y responde sin salir del CRM. Cada envío
                      requiere tu confirmación.
                    </p>
                    <span>
                      Las funciones disponibles dependen del canal, los permisos
                      y tu plan de Zernio.
                    </span>
                  </div>
                ) : (
                  <>
                    <header className="inbox-conversation-header">
                      <button
                        className="inbox-mobile-back crm-icon-button"
                        aria-label="Volver a las entradas"
                        onClick={() => setSelected(null)}
                      >
                        ←
                      </button>
                      <div>
                        <strong>{inboxTitle(selected)}</strong>
                        <span>
                          {account.name} ·{" "}
                          {inboxPlatforms[account.platform] ?? account.platform}
                        </span>
                      </div>
                      <div className="inbox-thread-actions">
                        {section === "messages" && (
                          <>
                            <button
                              className="inbox-text-button"
                              disabled={busy}
                              onClick={() =>
                                void prepare({
                                  operation: "markConversationRead",
                                  account_id: accountId,
                                  path: {
                                    conversationId: inboxRowId(selected),
                                  },
                                })
                              }
                            >
                              Marcar leído
                            </button>
                            <button
                              className="inbox-text-button"
                              disabled={busy}
                              onClick={() =>
                                void prepare({
                                  operation: "updateInboxConversation",
                                  account_id: accountId,
                                  path: {
                                    conversationId: inboxRowId(selected),
                                  },
                                  body: {
                                    status:
                                      status === "active"
                                        ? "archived"
                                        : "active",
                                  },
                                })
                              }
                            >
                              {status === "active" ? "Archivar" : "Reabrir"}
                            </button>
                          </>
                        )}
                        <button
                          className="inbox-text-button"
                          onClick={openTools}
                        >
                          Más acciones
                        </button>
                      </div>
                    </header>
                    {threadError && (
                      <p role="alert" className="inbox-error">
                        {threadError}
                        <button
                          className="inbox-text-button"
                          onClick={() => void loadThread()}
                        >
                          Actualizar
                        </button>
                      </p>
                    )}
                    <div className="inbox-message-scroll" ref={scroll}>
                      {inboxCursor(thread) && (
                        <button
                          className="inbox-text-button"
                          disabled={threadLoading}
                          onClick={() => void loadThread(inboxCursor(thread)!)}
                        >
                          Cargar más{" "}
                          {section === "messages" ? "mensajes" : "comentarios"}
                        </button>
                      )}
                      {threadLoading && !messages.length ? (
                        <p role="status">Cargando el contenido…</p>
                      ) : section === "messages" || section === "comments" ? (
                        <>
                          {section === "comments" && (
                            <article className="inbox-post">
                              <strong>Publicación</strong>
                              <p>{inboxBody(selected)}</p>
                            </article>
                          )}
                          {!orderedMessages.length && (
                            <p className="inbox-muted">
                              {section === "messages"
                                ? "Sin mensajes accesibles en esta página."
                                : "Sin comentarios accesibles en esta página."}
                            </p>
                          )}
                          {orderedMessages.map((row, index) => (
                            <InboxMessage
                              key={`${inboxRowId(row)}:${index}`}
                              row={row}
                              comments={section === "comments"}
                              onReply={() => setReplyComment(row)}
                              onAction={(operation, extra) =>
                                void prepare({
                                  operation,
                                  account_id: accountId,
                                  path:
                                    section === "messages"
                                      ? {
                                          conversationId: inboxRowId(selected),
                                          messageId: inboxRowId(row),
                                        }
                                      : {
                                          postId: inboxRowId(selected),
                                          commentId: inboxRowId(row),
                                        },
                                  ...extra,
                                })
                              }
                              onAttachment={async (index) => {
                                try {
                                  const value = await read(
                                    "getMessageAttachment",
                                    {
                                      conversationId: inboxRowId(selected),
                                      messageId: inboxRowId(row),
                                      index,
                                    },
                                    { format: "json" },
                                  );
                                  setThread((old) => ({
                                    ...old,
                                    resolvedAttachment: value,
                                  }));
                                } catch (cause) {
                                  setThreadError(
                                    cause instanceof Error
                                      ? cause.message
                                      : "No pudimos abrir el adjunto.",
                                  );
                                }
                              }}
                            />
                          ))}
                        </>
                      ) : (
                        <article className="inbox-post">
                          <h3>{inboxTitle(selected)}</h3>
                          <p>
                            {inboxBody(selected) ||
                              "Zernio no conserva el contenido de esta entrada."}
                          </p>
                          {selected.reply ? (
                            <RawDetails
                              value={selected.reply}
                              title="Respuesta existente"
                            />
                          ) : null}
                          {inboxSafeLink(
                            selected.permalink ??
                              selected.reviewUrl ??
                              selected.url,
                          ) && (
                            <a
                              href={inboxSafeLink(
                                selected.permalink ??
                                  selected.reviewUrl ??
                                  selected.url,
                              )!}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              Ver en el canal ↗
                            </a>
                          )}
                        </article>
                      )}
                      {thread.resolvedAttachment ? (
                        <AttachmentResult value={thread.resolvedAttachment} />
                      ) : null}
                      <RawDetails
                        value={selected}
                        title="Detalles de la entrada"
                      />
                      <RawDetails
                        value={thread}
                        title="Detalles del contenido"
                      />
                    </div>
                    <div className="inbox-composer">
                      <p className="inbox-compose-context">
                        {section === "comments"
                          ? replyComment
                            ? `Respuesta a ${inboxTitle(replyComment)}`
                            : "Comentario público en la publicación"
                          : section === "reviews"
                            ? "Respuesta pública a la reseña"
                            : section === "mentions"
                              ? "Respuesta pública a la mención"
                              : "Respuesta privada"}
                        {replyComment && (
                          <button
                            className="inbox-text-button"
                            onClick={() => setReplyComment(null)}
                          >
                            Cancelar selección
                          </button>
                        )}
                      </p>
                      {replyAllowed ? (
                        <>
                          <label className="sr-only" htmlFor="inbox-message">
                            Respuesta
                          </label>
                          <textarea
                            id="inbox-message"
                            value={draft}
                            onChange={(e) =>
                              setDrafts((old) => ({
                                ...old,
                                [threadKey]: e.target.value,
                              }))
                            }
                            maxLength={16000}
                            rows={3}
                            placeholder="Escribe tu respuesta…"
                          />
                          {section === "messages" && (
                            <details className="inbox-attachment">
                              <summary>
                                <Icon name="paperclip" size={15} />
                                Adjunto por enlace
                              </summary>
                              <label>
                                URL pública HTTPS
                                <input
                                  value={attachment}
                                  onChange={(e) =>
                                    setAttachment(e.target.value)
                                  }
                                  type="url"
                                  placeholder="https://…"
                                />
                              </label>
                              <label>
                                Tipo
                                <select
                                  value={attachmentType}
                                  onChange={(e) =>
                                    setAttachmentType(e.target.value)
                                  }
                                >
                                  {["image", "video", "audio", "file"].map(
                                    (type) => (
                                      <option key={type}>{type}</option>
                                    ),
                                  )}
                                </select>
                              </label>
                              <small>
                                La plataforma descargará el archivo desde este
                                enlace. Para botones, plantillas y ubicaciones,
                                abre Herramientas.
                              </small>
                            </details>
                          )}
                          <div className="inbox-composer-bottom">
                            <span>
                              {draft.length.toLocaleString("es-CO")}/16.000 · No
                              se envía al escribir
                            </span>
                            <button
                              className="crm-button"
                              disabled={
                                busy ||
                                threadLoading ||
                                !!threadError ||
                                (!draft.trim() && !attachment)
                              }
                              onClick={reply}
                            >
                              <Icon name="send" />
                              Revisar respuesta
                            </button>
                          </div>
                        </>
                      ) : (
                        <p>
                          Esta red no permite responder esta mención mediante el
                          endpoint de Instagram. Consulta las acciones de
                          comentarios o abre el canal.
                        </p>
                      )}
                      {account.platform === "whatsapp" && (
                        <p className="inbox-channel-note">
                          WhatsApp aplica una ventana de atención de 24 horas.
                          Fuera de ella usa una plantilla aprobada desde
                          Herramientas. No se envían borradores sin aprobar.
                        </p>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </>
      )}
      <InboxTools
        open={tools}
        busy={busy}
        onClose={() => setTools(false)}
        catalog={catalog}
        account={account}
        selected={selected}
        section={section}
        request={request}
        onPrepare={(command) => {
          confirmedDraft.current = null;
          return prepare(command);
        }}
      />
      <InboxDialog
        open={!!plan}
        title="Confirmar acción en el canal"
        busy={busy}
        onClose={() => {
          setPlan(null);
          setConfirmed(false);
        }}
      >
        {plan && (
          <div className="inbox-confirm-content">
            <p>
              <strong>{operationName(plan.operation)}</strong>
            </p>
            <p>
              Cuenta: <strong>{plan.account_label}</strong> · {plan.account_id}
            </p>
            <p className="inbox-warning">
              Esta acción modifica el canal real. Las respuestas a comentarios,
              menciones y reseñas son públicas. En Meta, enviar puede recuperar
              el control de la conversación. Una nueva conversación o plantilla
              puede tener costo.
            </p>
            <p>
              Destinatario:{" "}
              <strong>
                {inboxText(plan.context?.participantName) ||
                  inboxText(plan.context?.participantId) ||
                  inboxText(plan.arguments.body.participantId) ||
                  inboxText(plan.arguments.body.participantUsername) ||
                  "Entrada identificada abajo"}
              </strong>
            </p>
            <p>
              Revisa el destinatario, los identificadores y el contenido exacto:
            </p>
            <pre>{JSON.stringify(plan.arguments, null, 2)}</pre>
            <p>
              Válida hasta {inboxTime(plan.expires_at)} ·{" "}
              {inboxStates[plan.state] ?? plan.state}
            </p>
            {plan.error && (
              <p className="inbox-error">
                {inboxErrors[plan.error] ??
                  "Revisa el resultado en Zernio antes de repetir."}
              </p>
            )}
            {plan.state === "prepared" && !attempted && (
              <label className="inbox-check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                Confirmo la cuenta, el destinatario, el contenido y las
                consecuencias de esta acción.
              </label>
            )}
            <div className="inbox-dialog-actions">
              <button
                className="crm-button crm-secondary"
                disabled={busy}
                onClick={() => setPlan(null)}
              >
                Cerrar
              </button>
              <button
                className="crm-button"
                disabled={
                  !confirmed || busy || attempted || plan.state !== "prepared"
                }
                onClick={send}
              >
                {busy ? "Confirmando…" : "Confirmar y ejecutar"}
              </button>
            </div>
            {error && (
              <p role="alert" className="inbox-error">
                {error}
              </p>
            )}
          </div>
        )}
      </InboxDialog>
      <InboxDialog
        open={historyOpen}
        title="Historial de acciones del inbox"
        onClose={() => setHistoryOpen(false)}
      >
        <div className="inbox-history">
          {error && (
            <p role="alert" className="inbox-error">
              {error}
            </p>
          )}
          {!history.length ? (
            <p>No hay acciones preparadas por este usuario.</p>
          ) : (
            history.map((item) => (
              <article key={item.id}>
                <strong>{operationName(item.operation)}</strong>
                <p>
                  {item.account_label} · {inboxTime(item.created_at)}
                </p>
                <span>{inboxStates[item.state] ?? item.state}</span>
                {item.state === "prepared" && (
                  <button
                    className="inbox-text-button"
                    onClick={async () => {
                      try {
                        setPlan(await request<InboxPlan>(`actions/${item.id}`));
                        setConfirmed(false);
                        setAttempted(false);
                        setHistoryOpen(false);
                      } catch (cause) {
                        setError(
                          cause instanceof Error
                            ? cause.message
                            : "No pudimos abrir la acción.",
                        );
                      }
                    }}
                  >
                    Revisar acción
                  </button>
                )}
                {["unknown", "sending"].includes(item.state) && (
                  <p>
                    No repetir: comprueba el canal. Un timeout no demuestra que
                    el envío falló.
                  </p>
                )}
              </article>
            ))
          )}
        </div>
      </InboxDialog>
    </section>
  );
}

function AttachmentResult({ value }: { value: unknown }) {
  const data = value as InboxRow;
  const nested = data.data as InboxRow | undefined;
  const url = inboxSafeLink(data.url ?? nested?.url);
  return (
    <div className="inbox-attachment-result">
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
        >
          Abrir adjunto verificado por Zernio ↗
        </a>
      ) : (
        <p>Zernio no devolvió un enlace HTTPS utilizable.</p>
      )}
    </div>
  );
}
function InboxMessage({
  row,
  comments,
  onReply,
  onAction,
  onAttachment,
}: {
  row: InboxRow;
  comments: boolean;
  onReply: () => void;
  onAction: (operation: string, extra?: Partial<InboxCommand>) => void;
  onAttachment: (index: number) => void;
}) {
  const outgoing = row.direction === "outgoing";
  const attachments = Array.isArray(row.attachments)
    ? (row.attachments as InboxRow[])
    : [];
  return (
    <article className={`inbox-bubble ${outgoing ? "is-outgoing" : ""}`}>
      <strong>
        {comments
          ? inboxTitle(row)
          : outgoing
            ? "Tu equipo"
            : inboxText(row.senderName) || "Contacto"}
      </strong>
      <p>
        {row.isDeleted
          ? "Mensaje eliminado"
          : inboxBody(row) || "Contenido sin texto o no retenido"}
      </p>
      {attachments.map((item, index) => (
        <button
          className="inbox-text-button"
          key={index}
          onClick={() => onAttachment(index)}
        >
          <Icon name="paperclip" size={14} />
          {inboxText(item.filename ?? item.name ?? item.type) || "Adjunto"} ·
          Abrir
        </button>
      ))}
      <small>
        {inboxTime(row.createdAt ?? row.createdTime ?? row.timestamp)}
        {row.status ? ` · ${inboxText(row.status)}` : ""}
      </small>
      {row.reactions ? (
        <RawDetails value={row.reactions} title="Reacciones" />
      ) : null}
      {Array.isArray(row.replies) && row.replies.length > 0 && (
        <RawDetails
          value={row.replies}
          title={`${row.replies.length} respuestas`}
        />
      )}
      {comments ? (
        <div className="inbox-bubble-actions">
          <button disabled={row.canReply === false} onClick={onReply}>
            Responder
          </button>
          <button
            disabled={row.canLike === false}
            onClick={() =>
              onAction(
                row.isLiked ? "unlikeInboxComment" : "likeInboxComment",
                row.isLiked && row.likeUri
                  ? { query: { likeUri: row.likeUri } }
                  : undefined,
              )
            }
          >
            {row.isLiked ? "Quitar me gusta" : "Me gusta"}
          </button>
          <button
            disabled={row.canHide === false}
            onClick={() =>
              onAction(row.isHidden ? "unhideInboxComment" : "hideInboxComment")
            }
          >
            {row.isHidden ? "Mostrar" : "Ocultar"}
          </button>
        </div>
      ) : null}
    </article>
  );
}

function InboxTools({
  open,
  busy,
  onClose,
  catalog,
  account,
  selected,
  section,
  request,
  onPrepare,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  catalog: Record<string, InboxOperation>;
  account: InboxAccount | undefined;
  selected: InboxRow | null;
  section: InboxSection;
  request: Request;
  onPrepare: (command: InboxCommand) => Promise<void>;
}) {
  const [operation, setOperation] = useState("sendInboxMessage");
  const [search, setSearch] = useState("");
  const [values, setValues] = useState<Record<string, Record<string, string>>>({
    path: {},
    query: {},
    body: {},
  });
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const spec = catalog[operation];
  useEffect(() => {
    if (!open) return;
    const path: Record<string, string> = {};
    if (selected) {
      if (section === "messages") path.conversationId = inboxRowId(selected);
      if (section === "comments") path.postId = inboxRowId(selected);
      if (section === "reviews") path.reviewId = inboxRowId(selected);
    }
    setValues({ path, query: {}, body: {} });
    setResult(null);
    setError("");
  }, [open, operation, selected, section]);
  async function execute() {
    if (!spec || !account || reading) return;
    setError("");
    try {
      const command: InboxCommand = { operation, account_id: account.id };
      for (const location of ["path", "query", "body"] as const)
        command[location] = inboxFieldValues(
          spec.input[location],
          values[location],
        );
      if (spec.method === "GET") {
        setReading(true);
        setResult(await request("read", command));
      } else await onPrepare(command);
    } catch (cause) {
      setError(
        cause instanceof SyntaxError
          ? "Revisa la estructura JSON de los campos avanzados."
          : cause instanceof Error
            ? cause.message
            : "No pudimos completar la acción.",
      );
    } finally {
      setReading(false);
    }
  }
  return (
    <InboxDialog
      open={open}
      title="Herramientas de Zernio"
      busy={busy || reading}
      onClose={onClose}
    >
      <div className="inbox-tools-content">
        <p>
          Funciones del inbox publicadas por Zernio. La plataforma y los
          permisos de <strong>{account?.name}</strong> determinan cuáles acepta.
          No se ejecuta ninguna acción al seleccionarla.
        </p>
        {account?.platform === "whatsapp" && (
          <button
            className="crm-button crm-secondary"
            disabled={reading}
            onClick={async () => {
              setReading(true);
              setError("");
              try {
                setResult(
                  await request("templates", { account_id: account.id }),
                );
              } catch (cause) {
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "No pudimos consultar las plantillas aprobadas.",
                );
              } finally {
                setReading(false);
              }
            }}
          >
            Consultar plantillas aprobadas
          </button>
        )}
        <label>
          Buscar función
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Reacciones, etiquetas, plantillas…"
          />
        </label>
        <label>
          Función
          <select
            value={operation}
            onChange={(e) => setOperation(e.target.value)}
          >
            {Object.entries(catalog)
              .filter(
                ([key]) =>
                  key === operation ||
                  operationName(key)
                    .toLowerCase()
                    .includes(search.toLowerCase()),
              )
              .map(([key, value]) => (
                <option key={key} value={key}>
                  {value.method === "GET" ? "Consultar" : "Modificar"} ·{" "}
                  {operationName(key)}
                </option>
              ))}
          </select>
        </label>
        {spec && (
          <>
            <p className="inbox-operation-kind">
              {spec.method === "GET"
                ? "Consulta privada · Sin cambios en el canal"
                : "Cambio real · Requiere confirmación posterior"}
            </p>
            <details>
              <summary>Referencia y restricciones de esta función</summary>
              <p className="inbox-provider-doc">
                {spec.description || spec.summary}
              </p>
              <p>
                {spec.method} {spec.path}
              </p>
              <a
                href="https://docs.zernio.com/cli/inbox"
                target="_blank"
                rel="noopener noreferrer"
              >
                Documentación oficial ↗
              </a>
            </details>
            {(["path", "query", "body"] as const).map((location) => (
              <fieldset key={location}>
                <legend>
                  {location === "path"
                    ? "Identificadores"
                    : location === "query"
                      ? "Filtros de consulta"
                      : "Contenido y opciones"}
                </legend>
                <InboxFields
                  schema={spec.input[location]}
                  values={values[location]}
                  prefix={location}
                  compact={location === "body"}
                  onChange={(key, value) =>
                    setValues((old) => ({
                      ...old,
                      [location]: { ...old[location], [key]: value },
                    }))
                  }
                />
              </fieldset>
            ))}
            {error && (
              <p className="inbox-error" role="alert">
                {error}
              </p>
            )}
            <div className="inbox-dialog-actions">
              <button
                className="crm-button"
                disabled={busy || reading || !account?.active}
                onClick={execute}
              >
                {reading
                  ? "Consultando…"
                  : spec.method === "GET"
                    ? "Consultar Zernio"
                    : "Revisar acción"}
              </button>
            </div>
            {result !== null && (
              <RawDetails value={result} title="Resultado de la consulta" />
            )}
          </>
        )}
      </div>
    </InboxDialog>
  );
}
