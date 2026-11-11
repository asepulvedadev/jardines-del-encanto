"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "./icon";
import { ActionProposals, ActionResultDetails } from "./hermes-panel";
import type { SettingsRequest } from "./settings-types";
import { SaraRecorder, saraRecorderMime } from "./sara-audio";
import {
  EMPTY_SARA_DRAFT,
  SARA_FILE_LIMIT,
  mergeSaraMessages,
  mergeSaraConversations,
  saraFileBase64,
  saraProposalAvailable,
  saraUploadMime,
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
      {message.attachments.map((attachment) => (
        <SaraFile key={attachment.id} attachment={attachment} csrf={csrf} />
      ))}
      {message.results.map((result, index) => (
        <ActionResultDetails key={index} result={result} />
      ))}
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
  onManageSkills,
}: {
  csrf: string;
  onChanged: () => Promise<void>;
  onManageSkills?: () => void;
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
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
  const audioInput = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const scrollOlder = useRef(false);
  const [skills, setSkills] = useState<SaraSkill[]>([]);
  const [skillSearch, setSkillSearch] = useState("");
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState("");
  const skillsDialog = useRef<HTMLDialogElement>(null);
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
            path.includes("/messages") || path === "sara/attachments"
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
        setConversations((old) =>
          mergeSaraConversations(old, value.conversations),
        );
        setListCursor(value.next_cursor);
        if (!before)
          setSelectedId((old) => old ?? value.conversations[0]?.id ?? null);
      } catch (cause) {
        if (alive.current) setListError(feedback(cause));
      } finally {
        listLock.current = false;
        if (alive.current) setListLoading(false);
      }
    },
    [getPage],
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
  async function createConversation(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createLock.current) return;
    createLock.current = true;
    setCreatePending(true);
    setListError("");
    try {
      const value = await request<SaraConversation>(
        "sara/conversations",
        "POST",
        newTitle.trim() ? { title: newTitle.trim() } : {},
      );
      if (!alive.current) return;
      setConversations((old) => [
        value,
        ...old.filter((item) => item.id !== value.id),
      ]);
      setSelectedId(value.id);
      setNewTitle("");
      setCreating(false);
      setHistoryOpen(false);
      requestAnimationFrame(() => composer.current?.focus());
    } catch (cause) {
      setListError(feedback(cause));
    } finally {
      createLock.current = false;
      if (alive.current) setCreatePending(false);
    }
  }
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
  async function showSkills() {
    skillsDialog.current?.showModal();
    setSkillsLoading(true);
    setSkillsError("");
    try {
      const value = await request<{ skills: SaraSkill[] }>("sara/skills");
      setSkills(value.skills);
    } catch (cause) {
      setSkillsError(feedback(cause));
    } finally {
      setSkillsLoading(false);
    }
  }
  const ready = !!(status?.available && status.enabled);
  const filtered = conversations.filter((item) =>
    item.title.toLocaleLowerCase("es").includes(search.toLocaleLowerCase("es")),
  );
  return (
    <section
      className={`sara-workspace ${historyOpen ? "sara-history-open" : ""}`}
      aria-label="Sara IA"
    >
      <aside className="sara-history" aria-label="Conversaciones de Sara">
        <div className="sara-history-heading">
          <strong>Conversaciones</strong>
          <button
            className="sara-icon-button"
            aria-label="Nueva conversación"
            onClick={() => {
              setCreating(true);
              setHistoryOpen(true);
            }}
          >
            <Icon name="plus" />
          </button>
        </div>
        <label className="sara-search">
          <Icon name="search" />
          <span className="crm-sr-only">Buscar conversaciones cargadas</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar conversaciones"
          />
        </label>
        {creating && (
          <form className="sara-title-form" onSubmit={createConversation}>
            <label>
              Título (opcional)
              <input
                autoFocus
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                maxLength={120}
                disabled={createPending}
              />
            </label>
            <div>
              <button disabled={createPending}>Crear conversación</button>
              <button
                type="button"
                disabled={createPending}
                onClick={() => setCreating(false)}
              >
                Cancelar
              </button>
            </div>
          </form>
        )}
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
            <button
              key={item.id}
              aria-current={selectedId === item.id ? "page" : undefined}
              title={item.title}
              onClick={() => {
                setSelectedId(item.id);
                setHistoryOpen(false);
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
      </aside>
      <div className="sara-chat">
        <header className="sara-header">
          <button
            className="sara-history-toggle sara-icon-button"
            aria-label={
              historyOpen ? "Ocultar conversaciones" : "Ver conversaciones"
            }
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((value) => !value)}
          >
            <Icon name="list" />
          </button>
          <div className="sara-heading">
            <h2>Sara IA</h2>
            <span>
              {statusError
                ? "No disponible"
                : !status
                  ? "Consultando estado…"
                  : ready
                    ? "Disponible"
                    : "No disponible"}
            </span>
          </div>
          <button
            className="sara-skills-button"
            onClick={() => void showSkills()}
          >
            <Icon name="task" />
            Skills
          </button>
          {selected && (
            <button
              className="sara-icon-button"
              aria-label="Cambiar título de conversación"
              onClick={() => {
                setTitle(selected.title);
                setRenaming((value) => !value);
              }}
            >
              <Icon name="settings" />
            </button>
          )}
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
          {selected && (
            <div className="sara-conversation-label">
              <h3>{selected.title}</h3>
              <button
                disabled={historyLoading}
                onClick={() => void loadMessages(selected.id)}
              >
                Actualizar conversación
              </button>
            </div>
          )}
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
          {!selectedId && !listLoading && (
            <div className="sara-welcome">
              <span className="sara-avatar">
                <Icon name="message" size={28} />
              </span>
              <h3>Un espacio para avanzar.</h3>
              <p>
                Consulta el CRM, revisa documentos o prepara tu siguiente acción
                con Sara IA.
              </p>
              <button
                onClick={() => {
                  setCreating(true);
                  setHistoryOpen(true);
                }}
              >
                Nueva conversación
              </button>
            </div>
          )}
          {selectedId &&
            !historyLoading &&
            !currentMessages.length &&
            !historyError && (
              <div className="sara-welcome">
                <span className="sara-avatar">
                  <Icon name="message" size={28} />
                </span>
                <h3>¿En qué trabajamos hoy?</h3>
                <p>
                  Escribe una consulta o adjunta un documento. Los cambios en el
                  CRM requieren tu aprobación.
                </p>
              </div>
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
            <p className="sara-turn-state" role="status">
              Sara está procesando el envío…
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
          <form className="sara-composer" onSubmit={submit}>
            <label className="crm-sr-only" htmlFor="sara-message">
              Mensaje para Sara IA
            </label>
            <textarea
              id="sara-message"
              ref={composer}
              value={draft.text}
              onChange={(event) =>
                selectedId &&
                updateDraft(selectedId, (current) => ({
                  ...current,
                  text: event.target.value,
                }))
              }
              maxLength={4000}
              disabled={!selectedId || busy || historicalPending}
              placeholder={
                selectedId
                  ? "Escribe a Sara IA…"
                  : "Crea o selecciona una conversación"
              }
              rows={2}
            />
            <div className="sara-composer-toolbar">
              <div>
                <button
                  className="sara-icon-button"
                  type="button"
                  title="Adjuntar documento (máximo 512 KiB)"
                  aria-label="Adjuntar documento"
                  disabled={
                    !selectedId ||
                    busy ||
                    historicalPending ||
                    isUploading ||
                    draft.attachments.length >= 4
                  }
                  onClick={() => docInput.current?.click()}
                >
                  <Icon name="paperclip" />
                </button>
                <button
                  className="sara-icon-button"
                  type="button"
                  title={
                    !status?.voice_available
                      ? "Transcripción no disponible"
                      : "Adjuntar nota de voz"
                  }
                  aria-label="Adjuntar nota de voz"
                  disabled={
                    !selectedId ||
                    busy ||
                    historicalPending ||
                    isUploading ||
                    !status?.voice_available ||
                    draft.attachments.length >= 4
                  }
                  onClick={() => audioInput.current?.click()}
                >
                  <Icon name="microphone" />
                </button>
                {recording || recordStarting ? (
                  <>
                    <button
                      className="sara-icon-button sara-recording"
                      type="button"
                      aria-label="Detener grabación"
                      disabled={recordStarting}
                      onClick={() => recorder.current?.stop()}
                    >
                      <Icon name="stop" />
                    </button>
                    <button type="button" onClick={stopCapture}>
                      Cancelar grabación
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="sara-record-button"
                    disabled={
                      !selectedId ||
                      busy ||
                      historicalPending ||
                      isUploading ||
                      recordStarting ||
                      !status?.voice_available ||
                      !recordSupported ||
                      draft.attachments.length >= 4
                    }
                    onClick={() => void startRecording()}
                  >
                    <span aria-hidden="true">●</span>
                    {recordStarting ? "Abriendo micrófono…" : "Grabar nota"}
                  </button>
                )}
              </div>
              <button
                className="sara-send"
                type="submit"
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
                <Icon name="send" />
                Enviar
              </button>
            </div>
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
            accept=".txt,.md,.csv,.pdf,text/plain,text/markdown,text/csv,application/pdf"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length) void uploadFiles(files);
            }}
          />
          <input
            ref={audioInput}
            type="file"
            accept=".webm,.ogg,.mp3,.wav,.mp4,.m4a,audio/webm,audio/ogg,audio/mpeg,audio/wav,audio/mp4"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) localPreview(file);
            }}
          />
        </div>
      </div>
      <dialog
        ref={skillsDialog}
        className="sara-skills-dialog"
        aria-labelledby="sara-skills-title"
      >
        <header>
          <h2 id="sara-skills-title">Skills del proyecto</h2>
          <button
            className="sara-icon-button"
            aria-label="Cerrar skills"
            onClick={() => skillsDialog.current?.close()}
          >
            <Icon name="close" />
          </button>
        </header>
        <label>
          Buscar skills
          <input
            value={skillSearch}
            onChange={(event) => setSkillSearch(event.target.value)}
            placeholder="Nombre o descripción"
          />
        </label>
        {skillsLoading && <p role="status">Consultando skills…</p>}
        {skillsError && (
          <p className="sara-error" role="alert">
            {skillsError}
          </p>
        )}
        {!skillsLoading && !skills.length && !skillsError && (
          <p className="sara-muted">
            Aún no hay skills en el registro del proyecto.
          </p>
        )}
        {skills
          .filter((skill) =>
            `${skill.name} ${skill.description}`
              .toLocaleLowerCase("es")
              .includes(skillSearch.toLocaleLowerCase("es")),
          )
          .map((skill) => (
            <details key={skill.id}>
              <summary>
                {skill.name}
                <span>
                  {skill.effective
                    ? "Disponible"
                    : skill.enabled
                      ? "No disponible"
                      : "Desactivada"}
                </span>
              </summary>
              <p>{skill.description}</p>
              <pre>{skill.content}</pre>
            </details>
          ))}
        {!skillsLoading &&
          skills.length > 0 &&
          !skills.some((skill) =>
            `${skill.name} ${skill.description}`
              .toLocaleLowerCase("es")
              .includes(skillSearch.toLocaleLowerCase("es")),
          ) && <p className="sara-muted">No hay coincidencias.</p>}
        {onManageSkills && (
          <button
            className="sara-manage"
            onClick={() => {
              skillsDialog.current?.close();
              onManageSkills();
            }}
          >
            Gestionar skills
          </button>
        )}
      </dialog>
    </section>
  );
}
