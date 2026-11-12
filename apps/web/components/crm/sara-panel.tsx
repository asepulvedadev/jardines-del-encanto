"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "./icon";
import { ActionProposals, ActionResultDetails } from "./hermes-panel";
import type { SettingsRequest } from "./settings-types";
import { SaraRecorder, saraRecorderMime } from "./sara-audio";
import { SaraVoiceOutput } from "./sara-voice-output";
import {
  EMPTY_SARA_DRAFT,
  SARA_FILE_LIMIT,
  mergeSaraMessages,
  mergeSaraConversations,
  saraFileBase64,
  saraProposalAvailable,
  saraUploadMime,
  saraSkillQuery,
  saraInsertSkill,
  type SaraSkillQuery,
  type SaraAttachment,
  type SaraConversation,
  type SaraDraft,
  type SaraMessage,
  type SaraSkill,
  type SaraStatus,
  type SaraTurn,
  type SaraTurnInput,
} from "./sara-types";
import "./sara.css";
const errors: Record<string, string> = {
  authentication_required: "Tu sesión finalizó. Vuelve a ingresar.",
  invalid_csrf: "Tu sesión cambió. Recarga la página.",
  invalid_input: "Revisa el mensaje y los archivos.",
  hermes_unavailable: "Sara IA no está disponible. Tu borrador se conserva.",
  hermes_disabled: "Sara IA está desactivada.",
  connection_disabled: "Sara IA está pausada. Tu nota se conserva localmente.",
  voice_unavailable:
    "La transcripción no está disponible. Conservamos tu nota local para que puedas intentar después.",
  sara_voice_unavailable:
    "La transcripción no está disponible. Conservamos tu nota local para que puedas intentar después.",
  sara_transcription_failed:
    "No pudimos obtener una transcripción válida. Conservamos tu nota local; puedes revisarla y volver a intentar explícitamente.",
  attachment_quota_exceeded:
    "Alcanzaste el límite de archivos de tu cuenta (100 archivos o 25 MiB).",
  attachment_invalid_filename:
    "Usa un nombre de archivo de hasta 120 caracteres, sin rutas ni caracteres de control.",
  attachment_invalid_type:
    "La extensión y el tipo del archivo no son compatibles.",
  attachment_invalid_encoding: "No pudimos leer el contenido del archivo.",
  attachment_invalid_content:
    "El archivo no tiene un contenido válido para su formato.",
  attachment_pdf_no_text:
    "El PDF no contiene texto extraíble. Usa un PDF de texto, TXT o MD.",
  attachment_invalid_pdf:
    "No pudimos leer el PDF. Revisa que no esté cifrado o dañado.",
  attachment_parser_busy:
    "Estamos procesando otros documentos. Conserva el archivo e intenta después.",
  sara_conversation_busy:
    "Esta conversación tiene un envío pendiente. Actualiza su estado antes de enviar otro.",
  sara_request_id_reused:
    "El identificador de envío ya está asociado a otro contenido. Actualiza el historial; no se inició otra ejecución.",
  transcription_unavailable:
    "La transcripción no está disponible. Conservamos tu nota local.",
  attachment_too_large: "El archivo supera 512 KiB.",
  attachment_text_too_large:
    "El documento contiene demasiado texto. Usa un archivo más corto.",
  attachment_limit: "Alcanzaste el límite de archivos de tu cuenta.",
  unsupported_attachment: "El formato del archivo no es compatible.",
  invalid_attachment: "No pudimos leer este archivo. Revisa su formato.",
  conversation_busy:
    "Esta conversación tiene un envío pendiente. Actualiza su estado antes de enviar otro.",
  proposal_expired: "La propuesta venció. Solicita una nueva.",
  record_changed:
    "El registro cambió. Actualiza la conversación antes de continuar.",
};
class SaraRequestError extends Error {
  constructor(
    message: string,
    readonly uncertain: boolean,
    readonly status?: number,
  ) {
    super(message);
  }
}
type TurnState = {
  payload: SaraTurnInput;
  phase: "sending" | "uncertain" | "pending" | "failed";
};
const feedback = (cause: unknown) =>
  cause instanceof Error
    ? cause.message
    : "No pudimos completar la solicitud. Conservamos tu borrador.";
const dateLabel = (value: string) =>
  new Date(value).toLocaleString("es-CO", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Bogota",
  });
function SaraFile({
  attachment,
  csrf,
}: {
  attachment: SaraAttachment;
  csrf: string;
}) {
  const [url, setUrl] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const localUrl = useRef("");
  const abort = useRef<AbortController | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      abort.current?.abort();
      if (localUrl.current) URL.revokeObjectURL(localUrl.current);
    };
  }, []);
  async function content(play: boolean) {
    if (pending) return;
    setPending(true);
    setError("");
    const controller = new AbortController();
    abort.current = controller;
    try {
      const response = await fetch(
        `/api/crm/sara/attachments/${encodeURIComponent(attachment.id)}/content`,
        {
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          headers: { "X-CSRF-Token": csrf },
          signal: controller.signal,
        },
      );
      if (!response.ok)
        throw new Error("No pudimos recuperar el archivo privado.");
      const mime = response.headers.get("content-type")?.split(";")[0];
      if (
        !mime ||
        (mime !== attachment.mime_type.split(";")[0] &&
          mime !== "application/octet-stream")
      )
        throw new Error("El archivo no tiene un formato seguro.");
      const reader = response.body?.getReader();
      const parts: Uint8Array[] = [];
      let size = 0;
      if (!reader) throw new Error("El archivo no tiene contenido.");
      while (true) {
        const value = await reader.read();
        if (value.done) break;
        size += value.value.byteLength;
        if (size > SARA_FILE_LIMIT) {
          await reader.cancel();
          throw new Error("El archivo supera el tamaño permitido.");
        }
        parts.push(value.value);
      }
      const blob = new Blob(parts as BlobPart[]);
      if (!alive.current) return;
      if (localUrl.current) URL.revokeObjectURL(localUrl.current);
      const value = URL.createObjectURL(
        new Blob([blob], { type: attachment.mime_type }),
      );
      localUrl.current = value;
      if (play) setUrl(value);
      else {
        const link = document.createElement("a");
        link.href = value;
        link.download = attachment.filename;
        link.click();
      }
    } catch (cause) {
      if (alive.current && !controller.signal.aborted)
        setError(feedback(cause));
    } finally {
      if (alive.current) setPending(false);
    }
  }
  return (
    <div className="sara-file">
      <span>
        <Icon name={attachment.kind === "audio" ? "microphone" : "paperclip"} />
        {attachment.filename}
      </span>
      <div>
        {attachment.kind === "audio" && !url && (
          <button
            type="button"
            disabled={pending}
            onClick={() => void content(true)}
          >
            Escuchar nota
          </button>
        )}
        <button
          type="button"
          disabled={pending}
          onClick={() => void content(false)}
          aria-label={`Descargar ${attachment.filename}`}
        >
          <Icon name="download" />
          Descargar
        </button>
      </div>
      {url && (
        <audio
          controls
          src={url}
          aria-label={`Nota de voz: ${attachment.filename}`}
        />
      )}
      <details>
        <summary>
          {attachment.kind === "audio"
            ? "Ver extracto de transcripción"
            : "Ver extracto"}
        </summary>
        <p>{attachment.text || "No hay texto extraído disponible."}</p>
      </details>
      {error && (
        <p className="sara-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
export function SaraMessageView({
  message,
  csrf,
  request,
  onChanged,
}: {
  message: SaraMessage;
  csrf: string;
  request: SettingsRequest;
  onChanged: () => Promise<void>;
}) {
  const available = message.proposals.filter(saraProposalAvailable);
  const unavailable = message.proposals.filter(
    (proposal) => proposal.resolvable === false,
  );
  return (
    <article
      className={`sara-message sara-message-${message.role}`}
      aria-label={`${message.role === "assistant" ? "Sara IA" : "Tú"}, ${dateLabel(message.created_at)}`}
    >
      <div className="sara-message-meta">
        <strong>{message.role === "assistant" ? "Sara IA" : "Tú"}</strong>
        <time dateTime={message.created_at}>
          {dateLabel(message.created_at)}
        </time>
        {message.state !== "completed" && (
          <span>
            {message.state === "pending" ? "Pendiente" : "Envío fallido"}
          </span>
        )}
      </div>
      {message.content && (
        <p className="sara-message-text">{message.content}</p>
      )}
      {message.role === "assistant" && message.state === "completed" && (
        <SaraVoiceOutput
          key={message.id}
          text={message.content}
          request={request}
          onChanged={onChanged}
        />
      )}
      {message.attachments.map((attachment) => (
        <SaraFile key={attachment.id} attachment={attachment} csrf={csrf} />
      ))}
      {message.results.length > 0 && (
        <details className="sara-activity">
          <summary>
            Actividad de Sara <span>{message.results.length}</span>
          </summary>
          <div>
            {message.results.map((result, index) => (
              <ActionResultDetails
                key={index}
                result={result}
                request={request}
              />
            ))}
          </div>
        </details>
      )}
      {available.length > 0 && (
        <ActionProposals
          proposals={available.filter(
            (proposal) => proposal.resolvable !== false,
          )}
          request={request}
          onChanged={onChanged}
        />
      )}{" "}
      {unavailable.map((proposal) => (
        <div className="sara-unavailable-proposal" key={proposal.id}>
          <strong>{proposal.action}</strong>
          <p>
            {proposal.status === "pending"
              ? "Propuesta no disponible en esta sesión. Solicita una nueva; no se volverá a ejecutar desde el historial."
              : proposal.status === "expired"
                ? "Propuesta vencida."
                : proposal.status === "approved"
                  ? "Propuesta aprobada anteriormente."
                  : "Propuesta rechazada."}
          </p>
          <details>
            <summary>Ver argumentos originales</summary>
            <pre>{JSON.stringify(proposal.arguments, null, 2)}</pre>
          </details>
        </div>
      ))}
    </article>
  );
}
export function SaraPanel({
  csrf,
  onChanged,
}: {
  csrf: string;
  onChanged: () => Promise<void>;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<SaraStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [conversations, setConversations] = useState<SaraConversation[]>([]);
  const [listCursor, setListCursor] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedId;
  const [search, setSearch] = useState("");
  const historyDialog = useRef<HTMLDialogElement>(null);
  const deleted = useRef(new Set<string>());
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<SaraConversation | null>(
    null,
  );
  const [deletePending, setDeletePending] = useState(false);
  const deleteLock = useRef(false);
  const [deleteError, setDeleteError] = useState("");
  const [createPending, setCreatePending] = useState(false);
  const createLock = useRef(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  const [messages, setMessages] = useState<Record<string, SaraMessage[]>>({});
  const [messageCursors, setMessageCursors] = useState<
    Record<string, string | null>
  >({});
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const historyGeneration = useRef(0);
  const historyAbort = useRef<AbortController | null>(null);
  const listLock = useRef(false);
  const [drafts, setDrafts] = useState<Record<string, SaraDraft>>({});
  const [turns, setTurns] = useState<Record<string, TurnState>>({});
  const turnLocks = useRef(new Set<string>());
  const [conversationErrors, setConversationErrors] = useState<
    Record<string, string>
  >({});
  const [uploads, setUploads] = useState<Record<string, boolean>>({});
  const uploadLocks = useRef(new Set<string>());
  const composer = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const docInput = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const scrollOlder = useRef(false);
  const [skills, setSkills] = useState<SaraSkill[]>([]);
  const [skillToken, setSkillToken] = useState<SaraSkillQuery | null>(null);
  const [activeSkill, setActiveSkill] = useState(0);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState("");

  const [recording, setRecording] = useState(false);
  const [recordStarting, setRecordStarting] = useState(false);
  const recorder = useRef<SaraRecorder | null>(null);
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(
    null,
  );
  const previewRef = useRef<{ file: File; url: string } | null>(null);
  const [recordSupported, setRecordSupported] = useState(false);
  const selected = conversations.find((value) => value.id === selectedId);
  const draft = selectedId
    ? (drafts[selectedId] ?? EMPTY_SARA_DRAFT)
    : EMPTY_SARA_DRAFT;
  const currentMessages = selectedId ? (messages[selectedId] ?? []) : [];
  const turn = selectedId ? turns[selectedId] : undefined;
  const busy = !!(
    turn && ["sending", "uncertain", "pending"].includes(turn.phase)
  );
  const historicalPending = currentMessages.some(
    (value) => value.role === "user" && value.state === "pending",
  );
  const isUploading = !!(selectedId && uploads[selectedId]);
  const error = selectedId ? (conversationErrors[selectedId] ?? "") : "";
  const request: SettingsRequest = useCallback(
    async <T,>(path: string, method = "GET", payload?: unknown): Promise<T> => {
      const body = method === "GET" ? undefined : JSON.stringify(payload ?? {});
      if (
        body &&
        new TextEncoder().encode(body).byteLength >
          (path === "sara/attachments" ? 768 * 1024 : 16384)
      )
        throw new SaraRequestError(
          "La solicitud supera el tamaño permitido.",
          false,
        );
      let response: Response;
      try {
        response = await fetch(`/api/crm/${path}`, {
          method,
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body,
          signal: AbortSignal.timeout(
            path.includes("/messages") ||
              path === "sara/attachments" ||
              /^hermes\/proposals\/[0-9a-f-]+\/approve$/.test(path)
              ? 95000
              : 25000,
          ),
        });
      } catch {
        throw new SaraRequestError(
          "No pudimos confirmar la respuesta del servidor. Conservamos tu borrador; comprueba el mismo envío antes de intentar otro.",
          true,
        );
      }
      if (response.status === 401) {
        router.replace("/login");
        throw new SaraRequestError(errors.authentication_required, false);
      }
      const value = await response.json().catch(() => null);
      if (!response.ok || !value)
        throw new SaraRequestError(
          errors[typeof value?.detail === "string" ? value.detail : ""] ??
            "No pudimos completar la solicitud. Conservamos tu borrador.",
          response.status >= 500 || response.status === 408 || !value,
          response.status,
        );
      return value as T;
    },
    [csrf, router],
  );
  const getPage = useCallback(
    async <T,>(path: string, signal?: AbortSignal): Promise<T> => {
      const response = await fetch(`/api/crm/sara/${path}`, {
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        headers: { "X-CSRF-Token": csrf },
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(25000)])
          : AbortSignal.timeout(25000),
      });
      if (response.status === 401) router.replace("/login");
      const value = await response.json().catch(() => null);
      if (!response.ok || !value)
        throw new Error(
          "No pudimos consultar el historial. Intenta actualizar.",
        );
      return value as T;
    },
    [csrf, router],
  );
  const updateDraft = useCallback(
    (id: string, change: (value: SaraDraft) => SaraDraft) =>
      setDrafts((old) => ({
        ...old,
        [id]: change(old[id] ?? EMPTY_SARA_DRAFT),
      })),
    [],
  );
  const setError = useCallback(
    (id: string, value: string) =>
      setConversationErrors((old) => ({ ...old, [id]: value })),
    [],
  );
  const discardPreview = useCallback(() => {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current.url);
    previewRef.current = null;
    setPreview(null);
  }, []);
  const stopCapture = useCallback(() => {
    recorder.current?.dispose();
    recorder.current = null;
    setRecording(false);
    setRecordStarting(false);
    discardPreview();
  }, [discardPreview]);
  useEffect(() => {
    alive.current = true;
    setRecordSupported(
      globalThis.isSecureContext &&
        typeof MediaRecorder !== "undefined" &&
        !!navigator.mediaDevices?.getUserMedia &&
        !!saraRecorderMime(
          (value) =>
            typeof MediaRecorder.isTypeSupported === "function" &&
            MediaRecorder.isTypeSupported(value),
        ),
    );
    return () => {
      alive.current = false;
      recorder.current?.dispose();
      if (previewRef.current) URL.revokeObjectURL(previewRef.current.url);
      historyAbort.current?.abort();
    };
  }, []);
  useEffect(() => {
    let active = true;
    request<SaraStatus>("sara/status")
      .then((value) => {
        if (active) {
          setStatus(value);
          setStatusError("");
        }
      })
      .catch((cause) => {
        if (active) setStatusError(feedback(cause));
      });
    return () => {
      active = false;
    };
  }, [request]);
  const createConversation = useCallback(async () => {
    if (createLock.current || !alive.current) return;
    createLock.current = true;
    setCreatePending(true);
    setListError("");
    try {
      const value = await request<SaraConversation>(
        "sara/conversations",
        "POST",
        {},
      );
      if (!alive.current) return;
      setConversations((old) => [
        value,
        ...old.filter((item) => item.id !== value.id),
      ]);
      setSelectedId(value.id);
      historyDialog.current?.close();
      requestAnimationFrame(() => composer.current?.focus());
      return value;
    } catch (cause) {
      if (alive.current) setListError(feedback(cause));
    } finally {
      createLock.current = false;
      if (alive.current) setCreatePending(false);
    }
  }, [request]);
  const loadConversations = useCallback(
    async (before?: string) => {
      if (listLock.current) return;
      listLock.current = true;
      setListLoading(true);
      setListError("");
      try {
        const value = await getPage<{
          conversations: SaraConversation[];
          next_cursor: string | null;
        }>(
          `conversations${before ? `?before=${encodeURIComponent(before)}` : ""}`,
        );
        if (!alive.current) return;
        const available = value.conversations.filter(
          (item) => !deleted.current.has(item.id),
        );
        setConversations((old) =>
          mergeSaraConversations(old, available).filter(
            (item) => !deleted.current.has(item.id),
          ),
        );
        setListCursor(
          deleted.current.has(value.next_cursor ?? "")
            ? null
            : value.next_cursor,
        );
        if (!before)
          setSelectedId((old) =>
            old && !deleted.current.has(old) ? old : (available[0]?.id ?? null),
          );
        if (!before && !available.length && !selectedRef.current)
          await createConversation();
      } catch (cause) {
        if (alive.current) setListError(feedback(cause));
      } finally {
        listLock.current = false;
        if (alive.current) setListLoading(false);
      }
    },
    [getPage, createConversation],
  );
  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);
  const loadMessages = useCallback(
    async (id: string, before?: string) => {
      const generation = ++historyGeneration.current;
      historyAbort.current?.abort();
      const controller = new AbortController();
      historyAbort.current = controller;
      setHistoryLoading(true);
      setHistoryError("");
      const previousHeight = log.current?.scrollHeight ?? 0;
      try {
        const value = await getPage<{
          messages: SaraMessage[];
          next_cursor: string | null;
        }>(
          `conversations/${encodeURIComponent(id)}/messages${before ? `?before=${encodeURIComponent(before)}` : ""}`,
          controller.signal,
        );
        if (
          controller.signal.aborted ||
          generation !== historyGeneration.current ||
          selectedRef.current !== id
        )
          return;
        scrollOlder.current = !!before;
        setMessages((old) => ({
          ...old,
          [id]: mergeSaraMessages(old[id] ?? [], value.messages),
        }));
        setMessageCursors((old) => ({ ...old, [id]: value.next_cursor }));
        if (before)
          requestAnimationFrame(() => {
            if (selectedRef.current === id && log.current)
              log.current.scrollTop +=
                log.current.scrollHeight - previousHeight;
          });
      } catch (cause) {
        if (
          !controller.signal.aborted &&
          generation === historyGeneration.current
        )
          setHistoryError(feedback(cause));
      } finally {
        if (
          !controller.signal.aborted &&
          generation === historyGeneration.current
        )
          setHistoryLoading(false);
      }
    },
    [getPage],
  );
  useEffect(() => {
    stopCapture();
    setRenaming(false);
    setSkillToken(null);
    setHistoryError("");
    if (selectedId) void loadMessages(selectedId);
    else setHistoryLoading(false);
    return () => {
      historyAbort.current?.abort();
    };
  }, [selectedId, loadMessages, stopCapture]);
  useEffect(() => {
    if (scrollOlder.current) {
      scrollOlder.current = false;
      return;
    }
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [selectedId, currentMessages.length]);
  useEffect(() => {
    const field = composer.current;
    if (field) {
      field.style.height = "auto";
      field.style.height = `${Math.min(field.scrollHeight, 180)}px`;
    }
  }, [draft.text, selectedId]);
  async function rename(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId || createLock.current) return;
    const id = selectedId;
    if (!title.trim()) {
      setError(id, "Escribe un título para la conversación.");
      return;
    }
    createLock.current = true;
    setCreatePending(true);
    setError(id, "");
    try {
      const value = await request<SaraConversation>(
        `sara/conversations/${encodeURIComponent(id)}`,
        "PATCH",
        { title: title.trim() },
      );
      setConversations((old) =>
        old.map((item) => (item.id === id ? value : item)),
      );
      if (selectedRef.current === id) setRenaming(false);
    } catch (cause) {
      setError(id, feedback(cause));
    } finally {
      createLock.current = false;
      setCreatePending(false);
    }
  }
  async function afterAction(id: string) {
    try {
      await onChanged();
      if (selectedRef.current === id) await loadMessages(id);
    } catch {
      setError(
        id,
        "La acción ya respondió, pero no pudimos actualizar la vista. No repitas el cambio; actualiza el historial.",
      );
    }
  }
  async function sendTurn(id: string, payload: SaraTurnInput) {
    if (turnLocks.current.has(id)) return;
    turnLocks.current.add(id);
    setError(id, "");
    setTurns((old) => ({ ...old, [id]: { payload, phase: "sending" } }));
    try {
      const value = await request<SaraTurn>(
        `sara/conversations/${encodeURIComponent(id)}/messages`,
        "POST",
        payload,
      );
      if (!alive.current) return;
      if (selectedRef.current === id) {
        historyAbort.current?.abort();
        ++historyGeneration.current;
        setHistoryLoading(false);
      }
      setMessages((old) => ({
        ...old,
        [id]: mergeSaraMessages(old[id] ?? [], [
          value.user_message,
          ...(value.assistant_message ? [value.assistant_message] : []),
        ]),
      }));
      setTurns((old) => {
        const copy = { ...old };
        if (value.state === "completed") delete copy[id];
        else copy[id] = { payload, phase: value.state };
        return copy;
      });
      updateDraft(id, (current) =>
        (current.text.trim() === payload.message ||
          (!current.text.trim() &&
            payload.message === "Revisa los archivos adjuntos.")) &&
        current.attachments.map((file) => file.id).join(",") ===
          payload.attachment_ids.join(",")
          ? EMPTY_SARA_DRAFT
          : current,
      );
      if (value.state === "failed")
        setError(
          id,
          "El envío falló. No se inició ningún reintento automático.",
        );
      try {
        await onChanged();
      } catch {
        setError(
          id,
          "La respuesta se guardó, pero no pudimos actualizar el CRM. No repitas el envío.",
        );
      }
    } catch (cause) {
      if (alive.current) {
        setTurns((old) => ({
          ...old,
          [id]: {
            payload,
            phase:
              cause instanceof SaraRequestError && !cause.uncertain
                ? "failed"
                : "uncertain",
          },
        }));
        setError(id, feedback(cause));
      }
    } finally {
      turnLocks.current.delete(id);
    }
  }
  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !selectedId ||
      !ready ||
      historyLoading ||
      busy ||
      historicalPending ||
      isUploading ||
      recording ||
      recordStarting ||
      (!draft.text.trim() && !draft.attachments.length)
    )
      return;
    void sendTurn(selectedId, {
      request_id: crypto.randomUUID(),
      message: draft.text.trim() || "Revisa los archivos adjuntos.",
      attachment_ids: draft.attachments.map((file) => file.id),
    });
  }
  async function uploadFiles(files: File[], voice = false) {
    const id = selectedRef.current;
    if (!id || uploadLocks.current.has(id)) return;
    if (files.length + (drafts[id]?.attachments.length ?? 0) > 4) {
      setError(id, "Puedes adjuntar hasta 4 archivos por mensaje.");
      return;
    }
    uploadLocks.current.add(id);
    setUploads((old) => ({ ...old, [id]: true }));
    setError(id, "");
    try {
      for (const file of files) {
        const mime_type = saraUploadMime(file.name, file.type);
        if (mime_type.startsWith("audio/") && !status?.voice_available)
          throw new Error(
            "Las notas de voz no están disponibles. Puedes continuar por texto.",
          );
        const data_base64 = await saraFileBase64(file);
        const value = await request<SaraAttachment>(
          "sara/attachments",
          "POST",
          { filename: file.name, mime_type, data_base64 },
        );
        if (!alive.current) return;
        updateDraft(id, (current) => ({
          ...current,
          attachments: [...current.attachments, value],
        }));
      }
      if (voice && selectedRef.current === id) discardPreview();
    } catch (cause) {
      if (alive.current) setError(id, feedback(cause));
    } finally {
      uploadLocks.current.delete(id);
      if (alive.current) setUploads((old) => ({ ...old, [id]: false }));
    }
  }
  function localPreview(file: File) {
    const id = selectedRef.current;
    if (!id) return;
    try {
      const mime = saraUploadMime(file.name, file.type);
      if (!mime.startsWith("audio/"))
        throw new Error("Selecciona un archivo de audio compatible.");
      if (!file.size || file.size > SARA_FILE_LIMIT)
        throw new Error("La nota debe pesar entre 1 byte y 512 KiB.");
      discardPreview();
      const value = { file, url: URL.createObjectURL(file) };
      previewRef.current = value;
      setPreview(value);
    } catch (cause) {
      setError(id, feedback(cause));
    }
  }
  async function startRecording() {
    if (
      !selectedId ||
      recordStarting ||
      recording ||
      busy ||
      isUploading ||
      !status?.voice_available
    )
      return;
    const id = selectedId;
    setError(id, "");
    discardPreview();
    setRecordStarting(true);
    const capture = new SaraRecorder(
      (file) => {
        if (alive.current && selectedRef.current === id) localPreview(file);
      },
      (message) => {
        if (alive.current) setError(id, message);
      },
      () => {
        if (alive.current) {
          setRecording(false);
          setRecordStarting(false);
        }
      },
    );
    recorder.current = capture;
    try {
      await capture.start();
      if (
        alive.current &&
        selectedRef.current === id &&
        recorder.current === capture
      )
        setRecording(true);
    } catch (cause) {
      if (alive.current) setError(id, feedback(cause));
    } finally {
      if (alive.current) setRecordStarting(false);
    }
  }
  const skillMenuOpen =
    !!skillToken && !!selectedId && !busy && !historicalPending;
  useEffect(() => {
    if (!skillMenuOpen) return;
    let active = true;
    setSkills([]);
    setSkillsLoading(true);
    setSkillsError("");
    request<{ skills: SaraSkill[] }>("sara/skills")
      .then((value) => {
        if (active) setSkills(value.skills);
      })
      .catch((cause) => {
        if (active) setSkillsError(feedback(cause));
      })
      .finally(() => {
        if (active) setSkillsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [skillMenuOpen, selectedId, request]);
  const matchingSkills = skills.filter((skill) =>
    `${skill.name} ${skill.description}`
      .toLocaleLowerCase("es")
      .includes((skillToken?.query ?? "").toLocaleLowerCase("es")),
  );
  const usableSkills = matchingSkills.filter((skill) => skill.effective);
  const highlightedSkill =
    usableSkills[Math.min(activeSkill, Math.max(0, usableSkills.length - 1))];
  useEffect(() => {
    if (skillMenuOpen && highlightedSkill)
      document
        .getElementById(`sara-skill-${highlightedSkill.id}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [skillMenuOpen, highlightedSkill]);
  function selectSkill(skill: SaraSkill) {
    if (
      !selectedId ||
      !skillToken ||
      !skill.effective ||
      skillsLoading ||
      skillsError
    )
      return;
    const value = saraInsertSkill(draft.text, skillToken, skill.name);
    if (value.text.length > 4000) {
      setError(selectedId, "El mensaje no puede superar 4000 caracteres.");
      return;
    }
    updateDraft(selectedId, (current) => ({ ...current, text: value.text }));
    setSkillToken(null);
    requestAnimationFrame(() => {
      composer.current?.focus();
      composer.current?.setSelectionRange(value.caret, value.caret);
    });
  }
  function trackSkillToken(field: HTMLTextAreaElement) {
    setSkillToken(
      field.selectionStart === field.selectionEnd
        ? saraSkillQuery(field.value, field.selectionStart)
        : null,
    );
    setActiveSkill(0);
  }
  function closeDelete() {
    if (deleteLock.current) return;
    deleteDialog.current?.close();
    setDeleteTarget(null);
    setDeleteError("");
  }
  async function removeConversation() {
    if (!deleteTarget || deleteLock.current) return;
    const id = deleteTarget.id;
    if (
      turnLocks.current.has(id) ||
      uploadLocks.current.has(id) ||
      createLock.current ||
      listLock.current
    ) {
      setDeleteError(
        "Espera a que termine la operación en curso antes de borrar.",
      );
      return;
    }
    deleteLock.current = true;
    setDeletePending(true);
    setDeleteError("");
    try {
      try {
        await request(
          `sara/conversations/${encodeURIComponent(id)}`,
          "DELETE",
          {},
        );
      } catch (cause) {
        // A lost delete acknowledgement may be retried: an owned loaded row that
        // is already absent is safe to remove locally, never re-created or replayed.
        if (!(cause instanceof SaraRequestError && cause.status === 404))
          throw cause;
      }
      if (!alive.current) return;
      deleted.current.add(id);
      const remaining = conversations.filter((item) => item.id !== id);
      setConversations((old) => old.filter((item) => item.id !== id));
      if (selectedRef.current === id) {
        stopCapture();
        historyAbort.current?.abort();
        ++historyGeneration.current;
        selectedRef.current = remaining[0]?.id ?? null;
        setSelectedId(selectedRef.current);
      }
      const omit = <T,>(old: Record<string, T>) => {
        const next = { ...old };
        delete next[id];
        return next;
      };
      setMessages(omit);
      setDrafts(omit);
      setTurns(omit);
      setMessageCursors(omit);
      setConversationErrors(omit);
      setUploads(omit);
      setListCursor(null);
      deleteDialog.current?.close();
      setDeleteTarget(null);
      await loadConversations();
      requestAnimationFrame(() => {
        if (historyDialog.current?.open)
          historyDialog.current
            .querySelector<HTMLButtonElement>("button")
            ?.focus();
      });
    } catch (cause) {
      if (alive.current) setDeleteError(feedback(cause));
    } finally {
      deleteLock.current = false;
      if (alive.current) setDeletePending(false);
    }
  }
  const ready = !!(status?.available && status.enabled);
  const filtered = conversations.filter((item) =>
    item.title.toLocaleLowerCase("es").includes(search.toLocaleLowerCase("es")),
  );
  return (
    <section className="sara-workspace" aria-label="Sara IA">
      <dialog
        ref={historyDialog}
        className="sara-history-dialog"
        aria-labelledby="sara-history-title"
      >
        <header className="sara-history-heading">
          <h2 id="sara-history-title">Conversaciones</h2>
          <button
            className="sara-icon-button"
            aria-label="Cerrar historial"
            onClick={() => historyDialog.current?.close()}
          >
            <Icon name="close" />
          </button>
        </header>
        <label className="sara-search">
          <Icon name="search" />
          <span className="crm-sr-only">Buscar conversaciones cargadas</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar conversaciones"
          />
        </label>
        {listError && (
          <p className="sara-error" role="alert">
            {listError}
          </p>
        )}
        {listLoading && <p role="status">Consultando conversaciones…</p>}
        {!listLoading && !conversations.length && !listError && (
          <p className="sara-muted">
            Aún no tienes conversaciones. Crea una para comenzar.
          </p>
        )}
        <nav aria-label="Historial de conversaciones">
          {filtered.map((item) => (
            <div className="sara-history-row" key={item.id}>
              <button
                aria-current={selectedId === item.id ? "page" : undefined}
                title={item.title}
                onClick={() => {
                  setSelectedId(item.id);
                  historyDialog.current?.close();
                }}
              >
                <span>{item.title}</span>
                <time dateTime={item.updated_at}>
                  {new Date(item.updated_at).toLocaleDateString("es-CO", {
                    day: "numeric",
                    month: "short",
                  })}
                </time>
              </button>
              <button
                className="sara-icon-button sara-delete-button"
                aria-label={`Borrar conversación: ${item.title}`}
                title="Borrar conversación"
                disabled={
                  deletePending ||
                  listLoading ||
                  createPending ||
                  !!uploads[item.id] ||
                  ["sending", "uncertain", "pending"].includes(
                    turns[item.id]?.phase ?? "",
                  ) ||
                  (messages[item.id] ?? []).some(
                    (message) => message.state === "pending",
                  )
                }
                onClick={() => {
                  setDeleteTarget(item);
                  setDeleteError("");
                  deleteDialog.current?.showModal();
                }}
              >
                <Icon name="trash" />
              </button>
            </div>
          ))}
        </nav>
        {!filtered.length && search && (
          <p className="sara-muted">
            Sin coincidencias en las conversaciones cargadas.
          </p>
        )}
        {listCursor && (
          <button
            className="sara-history-more"
            disabled={listLoading}
            onClick={() => void loadConversations(listCursor)}
          >
            Cargar más conversaciones
          </button>
        )}
        {listError && (
          <button
            disabled={listLoading}
            onClick={() => void loadConversations()}
          >
            Actualizar historial
          </button>
        )}
      </dialog>
      <div className="sara-chat">
        <header className="sara-header">
          <div className="sara-heading">
            <span
              className="sara-presence"
              data-ready={ready}
              role="status"
              aria-label={
                statusError
                  ? "Sara no disponible"
                  : !status
                    ? "Consultando estado de Sara"
                    : ready
                      ? "Sara disponible"
                      : "Sara no disponible"
              }
            />
            <h2 title={selected?.title}>
              {selected?.title ?? "Nueva conversación"}
            </h2>
          </div>
          <nav className="sara-toolbar" aria-label="Herramientas de Sara">
            {selected && (
              <button
                className="sara-icon-button"
                aria-label="Actualizar conversación"
                title="Actualizar conversación"
                disabled={historyLoading}
                onClick={() => void loadMessages(selected.id)}
              >
                <Icon name="refresh" />
              </button>
            )}
            {selected && (
              <button
                className="sara-icon-button"
                aria-label="Cambiar título de conversación"
                title="Cambiar título"
                onClick={() => {
                  setTitle(selected.title);
                  setRenaming((value) => !value);
                }}
              >
                <Icon name="edit" />
              </button>
            )}
            <button
              className="sara-icon-button"
              aria-label="Historial de conversaciones"
              title="Historial de conversaciones"
              aria-haspopup="dialog"
              onClick={() => historyDialog.current?.showModal()}
            >
              <Icon name="history" />
            </button>
            <button
              className="sara-icon-button"
              aria-label="Nueva conversación"
              title="Nueva conversación"
              disabled={createPending || listLoading}
              onClick={() => void createConversation()}
            >
              <Icon name="plus" />
            </button>
          </nav>
        </header>
        {renaming && selected && (
          <form className="sara-rename" onSubmit={rename}>
            <label>
              Título de conversación
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required
                maxLength={120}
                disabled={createPending}
              />
            </label>
            <button disabled={createPending}>Guardar título</button>
            <button type="button" onClick={() => setRenaming(false)}>
              Cancelar
            </button>
          </form>
        )}
        <div
          className="sara-log"
          ref={log}
          role="log"
          aria-label={
            selected
              ? `Conversación: ${selected.title}`
              : "Conversación con Sara IA"
          }
          aria-live="polite"
          aria-relevant="additions"
          aria-busy={historyLoading}
        >
          {selectedId && messageCursors[selectedId] && (
            <button
              className="sara-older"
              disabled={historyLoading}
              onClick={() =>
                void loadMessages(
                  selectedId,
                  messageCursors[selectedId] ?? undefined,
                )
              }
            >
              Cargar mensajes anteriores
            </button>
          )}
          {historyLoading && <p role="status">Consultando mensajes…</p>}
          {historyError && (
            <p className="sara-error" role="alert">
              {historyError}
            </p>
          )}
          {statusError && (
            <p className="sara-error" role="alert">
              {statusError}
            </p>
          )}
          {!listLoading &&
            !historyLoading &&
            !currentMessages.length &&
            !historyError &&
            turn?.phase !== "sending" && (
              <div className="sara-welcome">
                <p className="sara-welcome-eyebrow">
                  SARA IA · JARDINES DEL ENCANTO
                </p>
                <h3>
                  ¿Qué vamos a<br />
                  hacer hoy?
                </h3>
                <p>
                  Organiza tus clientes, revisa documentos y prepara tu próximo
                  paso.
                </p>
                {!selectedId && (
                  <button
                    disabled={createPending}
                    onClick={() => void createConversation()}
                  >
                    Iniciar conversación
                  </button>
                )}
              </div>
            )}
          {listError && (
            <p className="sara-error" role="alert">
              {listError}
            </p>
          )}
          {currentMessages.map((message) => (
            <SaraMessageView
              key={`${selectedId}-${message.id}`}
              message={message}
              csrf={csrf}
              request={request}
              onChanged={() => afterAction(selectedId!)}
            />
          ))}
          {turn?.phase === "sending" && (
            <p className="sara-turn-state sara-working" role="status">
              <span className="sara-working-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              Sara está trabajando…
            </p>
          )}
          {(turn?.phase === "uncertain" || turn?.phase === "pending") && (
            <div className="sara-turn-state" role="status">
              <p>
                {turn.phase === "uncertain"
                  ? "No se confirmó la respuesta. Comprueba este mismo envío; no enviaremos una copia nueva."
                  : "El envío sigue pendiente. Puedes consultar su estado sin iniciar otra ejecución."}
              </p>
              <button
                onClick={() =>
                  selectedId && void sendTurn(selectedId, turn.payload)
                }
              >
                Comprobar envío
              </button>
            </div>
          )}
          {historicalPending && !turn && (
            <p className="sara-turn-state" role="status">
              Hay un envío pendiente en el historial. Actualiza la conversación
              para comprobarlo.
            </p>
          )}
        </div>
        {skillMenuOpen && (
          <div className="sara-skill-picker">
            <div className="sara-skill-picker-heading">
              <strong>Skills</strong>
              <span>Esc para cerrar</span>
            </div>
            {skillsLoading && <p role="status">Consultando skills…</p>}
            {skillsError && (
              <p className="sara-error" role="alert">
                {skillsError}
              </p>
            )}
            <div
              id="sara-skill-options"
              role="listbox"
              aria-label="Skills del proyecto"
            >
              {!skillsLoading &&
                !skillsError &&
                matchingSkills.map((skill) => (
                  <button
                    type="button"
                    role="option"
                    id={`sara-skill-${skill.id}`}
                    key={skill.id}
                    tabIndex={-1}
                    aria-selected={highlightedSkill?.id === skill.id}
                    aria-disabled={!skill.effective}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectSkill(skill)}
                  >
                    <span>
                      <strong>{skill.name}</strong>
                      {skill.description && <small>{skill.description}</small>}
                    </span>
                    <small>
                      {skill.effective
                        ? "Disponible"
                        : skill.enabled
                          ? "No disponible"
                          : "Desactivada"}
                    </small>
                  </button>
                ))}
            </div>
            {!skillsLoading && !skillsError && !matchingSkills.length && (
              <p role="status">
                {skills.length
                  ? "No hay coincidencias."
                  : "No hay skills en el registro del proyecto."}
              </p>
            )}
          </div>
        )}
        <div className="sara-composer-area">
          {error && (
            <p className="sara-error" role="alert">
              {error}
            </p>
          )}
          {!ready && status && !statusError && (
            <p className="sara-muted">
              Sara no está disponible. Puedes revisar el historial; tu borrador
              se conserva.
              <button
                onClick={() => {
                  void request<SaraStatus>("sara/status")
                    .then((value) => {
                      setStatus(value);
                      setStatusError("");
                    })
                    .catch((cause) => setStatusError(feedback(cause)));
                }}
              >
                Actualizar estado
              </button>
            </p>
          )}
          {preview && (
            <div className="sara-audio-preview">
              <strong>Revisa tu nota antes de usarla</strong>
              <audio
                controls
                src={preview.url}
                aria-label="Vista previa de nota de voz"
              />
              <span>
                {preview.file.name} · {Math.ceil(preview.file.size / 1024)} KiB
              </span>
              <div>
                <button
                  disabled={busy || isUploading || !status?.voice_available}
                  onClick={() => void uploadFiles([preview.file], true)}
                >
                  Usar nota
                </button>
                <button disabled={isUploading} onClick={discardPreview}>
                  Descartar nota
                </button>
              </div>
              <p className="sara-muted">
                Usar nota solicita la transcripción. Revisa el texto antes de
                enviar a Sara.
              </p>
            </div>
          )}
          <form className="sara-composer" onSubmit={submit}>
            <label className="crm-sr-only" htmlFor="sara-message">
              Mensaje para Sara IA
            </label>
            <textarea
              id="sara-message"
              ref={composer}
              value={draft.text}
              onChange={(event) => {
                if (selectedId)
                  updateDraft(selectedId, (current) => ({
                    ...current,
                    text: event.target.value,
                  }));
                trackSkillToken(event.currentTarget);
              }}
              onSelect={(event) => trackSkillToken(event.currentTarget)}
              onBlur={(event) => {
                if (!event.relatedTarget?.closest(".sara-skill-picker"))
                  setSkillToken(null);
              }}
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={skillMenuOpen}
              aria-controls={skillMenuOpen ? "sara-skill-options" : undefined}
              aria-activedescendant={
                skillMenuOpen && highlightedSkill
                  ? `sara-skill-${highlightedSkill.id}`
                  : undefined
              }
              maxLength={4000}
              aria-describedby="sara-composer-hint"
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (skillMenuOpen) {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    setSkillToken(null);
                    return;
                  }
                  if (
                    ["ArrowDown", "ArrowUp"].includes(event.key) &&
                    usableSkills.length
                  ) {
                    event.preventDefault();
                    setActiveSkill(
                      (value) =>
                        (value +
                          (event.key === "ArrowDown" ? 1 : -1) +
                          usableSkills.length) %
                        usableSkills.length,
                    );
                    return;
                  }
                  if (
                    (event.key === "Enter" && !event.shiftKey) ||
                    (event.key === "Tab" && !event.shiftKey && highlightedSkill)
                  ) {
                    event.preventDefault();
                    if (!event.repeat && highlightedSkill)
                      selectSkill(highlightedSkill);
                    return;
                  }
                }
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing &&
                  !event.repeat
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              disabled={!selectedId || busy || historicalPending}
              placeholder={
                selectedId
                  ? "Escribe a Sara IA…"
                  : createPending
                    ? "Preparando tu conversación…"
                    : "Inicia una conversación para escribir"
              }
              rows={2}
            />
            {draft.attachments.length > 0 && (
              <div className="sara-draft-files">
                {draft.attachments.map((file) => (
                  <div key={file.id}>
                    <strong>{file.filename}</strong>
                    <button
                      type="button"
                      className="sara-icon-button"
                      aria-label={`Quitar ${file.filename}`}
                      disabled={busy || isUploading}
                      onClick={() =>
                        selectedId &&
                        updateDraft(selectedId, (current) => ({
                          ...current,
                          attachments: current.attachments.filter(
                            (item) => item.id !== file.id,
                          ),
                        }))
                      }
                    >
                      <Icon name="close" />
                    </button>
                    <details open={file.kind === "audio"}>
                      <summary>
                        {file.kind === "audio"
                          ? "Revisar transcripción"
                          : "Revisar extracto"}
                      </summary>
                      <p>{file.text}</p>
                    </details>
                  </div>
                ))}
              </div>
            )}
            <div className="sara-composer-toolbar">
              <div className="sara-model">
                <Icon name="leaf" size={16} />
                <span title={status?.model ?? "Hermes"}>
                  {status?.model ?? "Sara IA"}
                </span>
              </div>
              <div className="sara-composer-actions">
                <button
                  className="sara-icon-button"
                  type="button"
                  title="Adjuntar documentos o audio (máximo 512 KiB)"
                  aria-label="Adjuntar documentos o audio"
                  disabled={
                    !selectedId ||
                    busy ||
                    historicalPending ||
                    isUploading ||
                    draft.attachments.length >= 4 ||
                    recording ||
                    recordStarting
                  }
                  onClick={() => docInput.current?.click()}
                >
                  <Icon name="paperclip" />
                </button>
                {recording || recordStarting ? (
                  <>
                    <button
                      className="sara-icon-button sara-recording"
                      type="button"
                      title="Detener grabación"
                      aria-label="Detener grabación"
                      disabled={recordStarting}
                      onClick={() => recorder.current?.stop()}
                    >
                      <Icon name="stop" />
                    </button>
                    <button
                      className="sara-icon-button"
                      type="button"
                      aria-label="Cancelar grabación"
                      title="Cancelar grabación"
                      onClick={stopCapture}
                    >
                      <Icon name="close" />
                    </button>
                  </>
                ) : (
                  <button
                    className="sara-icon-button"
                    type="button"
                    aria-label="Grabar nota de voz"
                    title={
                      !status?.voice_available
                        ? "Transcripción no disponible"
                        : !recordSupported
                          ? "Este navegador no permite grabar; adjunta un audio"
                          : "Grabar nota de voz"
                    }
                    disabled={
                      !selectedId ||
                      busy ||
                      historicalPending ||
                      isUploading ||
                      !status?.voice_available ||
                      !recordSupported ||
                      draft.attachments.length >= 4
                    }
                    onClick={() => void startRecording()}
                  >
                    <Icon name="microphone" />
                  </button>
                )}
                <button
                  className="sara-send sara-icon-button"
                  type="submit"
                  title="Enviar mensaje"
                  aria-label="Enviar mensaje"
                  disabled={
                    !selectedId ||
                    !ready ||
                    historyLoading ||
                    busy ||
                    historicalPending ||
                    isUploading ||
                    recording ||
                    recordStarting ||
                    (!draft.text.trim() && !draft.attachments.length)
                  }
                >
                  <Icon name="arrowUp" />
                </button>
              </div>
            </div>
            <span className="crm-sr-only" id="sara-composer-hint">
              Escribe $ para ver skills. Enter para enviar. Shift y Enter para
              una nueva línea.
            </span>
          </form>
          {isUploading && (
            <p className="sara-muted" role="status">
              Procesando archivo y texto…
            </p>
          )}
          {recording && (
            <p className="sara-record-state" role="status">
              Grabando nota · máximo 60 segundos y 512 KiB. Nada se envía hasta
              que pulses Usar nota.
            </p>
          )}
          {status && !status.voice_available && (
            <p className="sara-muted">
              Notas de voz no disponibles en este servidor. Puedes continuar por
              texto o adjuntar documentos.
            </p>
          )}
          {status?.voice_available && !recordSupported && (
            <p className="sara-muted">
              Este navegador no permite grabar. Puedes adjuntar un audio
              compatible.
            </p>
          )}
          <input
            ref={docInput}
            type="file"
            accept=".txt,.md,.csv,.pdf,.webm,.ogg,.mp3,.wav,.mp4,.m4a,text/plain,text/markdown,text/csv,application/pdf,audio/webm,audio/ogg,audio/mpeg,audio/wav,audio/mp4"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (!files.length || !selectedId) return;
              try {
                const audios = files.filter((file) =>
                  saraUploadMime(file.name, file.type).startsWith("audio/"),
                );
                if (audios.length > 1)
                  throw new Error(
                    "Selecciona una sola nota de voz para revisarla antes de usarla.",
                  );
                if (audios.length && !status?.voice_available)
                  throw new Error(
                    "Las notas de voz no están disponibles en este servidor.",
                  );
                if (files.length + draft.attachments.length > 4)
                  throw new Error(
                    "Puedes adjuntar hasta 4 archivos por mensaje.",
                  );
                const documents = files.filter(
                  (file) => !audios.includes(file),
                );
                if (documents.length) void uploadFiles(documents);
                if (audios[0]) localPreview(audios[0]);
              } catch (cause) {
                setError(selectedId, feedback(cause));
              }
            }}
          />
        </div>
      </div>
      <dialog
        ref={deleteDialog}
        className="sara-history-dialog sara-delete-dialog"
        aria-labelledby="sara-delete-title"
        aria-describedby="sara-delete-description"
        onCancel={(event) => {
          if (deleteLock.current) event.preventDefault();
          else closeDelete();
        }}
      >
        <h2 id="sara-delete-title">Borrar conversación</h2>
        <p className="sara-delete-name">{deleteTarget?.title}</p>
        <p id="sara-delete-description">
          Se borrarán sus mensajes y los archivos que no estén en otras
          conversaciones. No se puede deshacer. Los cambios ya realizados y su
          registro de auditoría se conservan.
        </p>
        {deleteError && (
          <p className="sara-error" role="alert">
            {deleteError}
          </p>
        )}
        <div className="sara-delete-actions">
          <button autoFocus disabled={deletePending} onClick={closeDelete}>
            Cancelar borrado
          </button>
          <button
            className="sara-delete-confirm"
            disabled={deletePending}
            onClick={() => void removeConversation()}
          >
            {deletePending ? "Borrando…" : "Borrar conversación"}
          </button>
        </div>
      </dialog>
    </section>
  );
}
