export type InboxSchema = {
  type?: string | string[];
  properties?: Record<string, InboxSchema>;
  required?: string[];
  enum?: unknown[];
  default?: unknown;
  anyOf?: InboxSchema[];
  oneOf?: InboxSchema[];
  items?: InboxSchema;
  const?: unknown;
};
export type InboxOperation = {
  method: string;
  path: string;
  summary: string;
  description: string;
  input: Record<"path" | "query" | "body", InboxSchema>;
};
export type InboxAccount = {
  id: string;
  platform: string;
  name: string;
  active: boolean;
};
export type InboxCommand = {
  operation: string;
  account_id: string;
  path?: Record<string, unknown>;
  query?: Record<string, unknown>;
  body?: Record<string, unknown>;
};
export type InboxRow = Record<string, unknown>;
export type InboxResult = Record<string, unknown>;
export type InboxPlan = {
  id: string;
  operation: string;
  account_label: string;
  account_id: string;
  state: string;
  context?: Record<string, unknown>;
  expires_at: string;
  arguments: {
    path: Record<string, unknown>;
    query: Record<string, unknown>;
    body: Record<string, unknown>;
  };
  error?: string;
  created_at?: string;
};
export const inboxSections = {
  messages: "Mensajes",
  comments: "Comentarios",
  mentions: "Menciones",
  reviews: "Reseñas",
} as const;
export type InboxSection = keyof typeof inboxSections;
export const inboxPlatforms: Record<string, string> = {
  whatsapp: "WhatsApp",
  facebook: "Facebook",
  instagram: "Instagram",
  twitter: "X",
  telegram: "Telegram",
  tiktok: "TikTok",
  youtube: "YouTube",
  linkedin: "LinkedIn",
  bluesky: "Bluesky",
  reddit: "Reddit",
  threads: "Threads",
  googlebusiness: "Google Business",
  sms: "SMS",
  imessage: "iMessage",
  slack: "Slack",
  line: "LINE",
  wechat: "WeChat",
  google: "Google",
  microsoft: "Microsoft",
};
export const inboxOperationLabels: Record<string, string> = {
  listInboxConversations: "Listar conversaciones",
  createInboxConversation: "Nueva conversación",
  searchInboxConversations: "Buscar en mensajes",
  getInboxConversation: "Ver conversación",
  updateInboxConversation: "Archivar / reabrir",
  deleteInboxConversation: "Eliminar conversación",
  getInboxConversationMessages: "Leer mensajes",
  sendInboxMessage: "Responder mensaje",
  editInboxMessage: "Editar mensaje",
  deleteInboxMessage: "Eliminar mensaje",
  sendTypingIndicator: "Indicador de escritura",
  setConversationThreadControl: "Control de conversación",
  acceptConversationRequest: "Aceptar solicitud y responder",
  listInboxLabels: "Ver etiquetas",
  createInboxLabel: "Crear etiqueta",
  deleteInboxLabel: "Eliminar etiqueta",
  listConversationLabels: "Etiquetas de conversación",
  addConversationLabel: "Asignar etiqueta",
  removeConversationLabel: "Quitar etiqueta",
  markConversationRead: "Marcar como leído",
  addMessageReaction: "Añadir reacción",
  removeMessageReaction: "Quitar reacción",
  getMessageAttachment: "Abrir adjunto",
  listInboxComments: "Publicaciones con comentarios",
  getInboxPostComments: "Leer comentarios y respuestas",
  replyToInboxPost: "Responder comentario",
  deleteInboxComment: "Eliminar comentario",
  editInboxComment: "Editar comentario",
  setCommentModeration: "Moderar comentario",
  hideInboxComment: "Ocultar comentario",
  unhideInboxComment: "Mostrar comentario",
  pinInboxComment: "Fijar comentario",
  unpinInboxComment: "Desfijar comentario",
  likeInboxComment: "Me gusta en comentario",
  unlikeInboxComment: "Quitar me gusta del comentario",
  likePost: "Me gusta en publicación",
  unlikePost: "Quitar me gusta de publicación",
  sendPrivateReplyToComment: "Respuesta privada a comentario",
  listInboxMentions: "Leer menciones",
  replyToMention: "Responder mención",
  listInboxReviews: "Leer reseñas",
  replyToInboxReview: "Responder reseña",
  deleteInboxReviewReply: "Eliminar respuesta de reseña",
};
export const inboxStates: Record<string, string> = {
  prepared: "Pendiente de confirmación",
  sending: "En proceso · No repetir",
  sent: "Confirmada por Zernio",
  rejected: "Rechazada por Zernio",
  unknown: "Resultado desconocido · Revisar el canal",
};
export const inboxErrors: Record<string, string> = {
  zernio_not_configured:
    "Configura la API de Zernio en Conexiones para consultar el inbox.",
  connection_disabled: "Activa Zernio y el canal en Configuraciones.",
  inbox_account_unavailable:
    "La cuenta ya no está disponible o necesita reconexión.",
  inbox_accounts_incomplete:
    "La lista de cuentas está incompleta. No se ha enviado nada.",
  inbox_input_invalid:
    "Revisa los campos de la operación. Deben coincidir con el contrato de Zernio.",
  inbox_scope_mismatch: "La respuesta no corresponde a la cuenta seleccionada.",
  inbox_provider_permission:
    "Zernio requiere permisos, elegibilidad o un plan compatible para esta función.",
  inbox_provider_rejected:
    "La plataforma rechazó la operación. Revisa permisos, ventana de respuesta y campos en Zernio.",
  inbox_rate_limited:
    "Se alcanzó el límite de solicitudes. Espera antes de volver a consultar.",
  inbox_provider_unavailable:
    "No pudimos consultar Zernio. Actualiza para intentar de nuevo.",
  inbox_delivery_unknown:
    "No pudimos confirmar el resultado. Comprueba el canal y el historial antes de preparar otro envío.",
  inbox_action_stale:
    "Esta acción expiró, ya se ejecutó o la conexión cambió. Revisa el historial.",
  inbox_unsafe_url: "Usa una URL HTTPS pública para el adjunto.",
  invalid_csrf: "La sesión cambió. Recarga el CRM.",
  inbox_operation_invalid: "La operación no está disponible.",
  database_unavailable:
    "La base de datos no está disponible. No repitas un envío sin revisar el historial.",
};
export function inboxText(value: unknown): string {
  return typeof value === "string"
    ? value
    : typeof value === "number"
      ? String(value)
      : "";
}
export function inboxRows(result: InboxResult, key?: string): InboxRow[] {
  const found = key
    ? result[key]
    : (result.data ??
      result.posts ??
      result.reviews ??
      result.mentions ??
      result.conversations);
  return Array.isArray(found)
    ? found.filter(
        (v): v is InboxRow => !!v && typeof v === "object" && !Array.isArray(v),
      )
    : [];
}
export function inboxCursor(result: InboxResult): string | null {
  const page = result.pagination as InboxRow | undefined;
  if (!page?.hasMore) return null;
  return inboxText(page.nextCursor ?? page.cursor) || null;
}
export function inboxPartial(result: InboxResult): boolean {
  const meta = result.meta as InboxRow | undefined;
  return (
    !!meta &&
    (!!meta.accountsFailed ||
      (Array.isArray(meta.accountsSkipped) && meta.accountsSkipped.length > 0))
  );
}
export function inboxSafeLink(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
export function inboxRowId(row: InboxRow): string {
  return inboxText(row.id ?? row.postId ?? row.reviewId);
}
export function inboxTitle(row: InboxRow): string {
  const author = (row.from ?? row.reviewer ?? row.author) as
    | InboxRow
    | undefined;
  return (
    inboxText(
      row.participantName ??
        row.authorName ??
        row.authorUsername ??
        author?.name ??
        author?.displayName ??
        row.title ??
        row.accountUsername ??
        row.participantId,
    ) || "Sin nombre"
  );
}
export function inboxBody(row: InboxRow): string {
  return inboxText(
    row.message ?? row.content ?? row.text ?? row.comment ?? row.lastMessage,
  );
}
export function inboxTime(value: unknown): string {
  const text = inboxText(value);
  if (!text) return "";
  const date = new Date(text);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat("es-CO", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "America/Bogota",
      }).format(date);
}
