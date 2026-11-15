"use client";
import { useId } from "react";
import type { InboxSchema } from "./inbox-types";
const labels: Record<string, string> = {
  category: "Categoría",
  effect: "Efecto de iMessage",
  contactCard: "Tarjeta del remitente",
  channel: "Canal de entrega",
  sharedMediaId: "Publicación propia de Instagram",
  sticker: "Sticker de Instagram",
  target: "Destino del control",
  parentCid: "CID del comentario padre",
  rootCid: "CID de la publicación raíz",
  rootUri: "URI de la publicación raíz",
  subreddit: "Comunidad de Reddit",
  mentionAuthor: "Mencionar al autor",
  skipDmCheck: "Omitir comprobación de mensajes de X",
  conversationId: "Conversación",
  messageId: "Mensaje",
  postId: "Publicación",
  commentId: "Comentario",
  reviewId: "Reseña",
  mediaId: "Publicación mencionada",
  index: "Posición del adjunto",
  message: "Mensaje",
  text: "Texto",
  participantId: "ID o teléfono del destinatario",
  participantUsername: "Usuario destinatario",
  attachmentUrl: "URL pública del adjunto",
  attachmentType: "Tipo de adjunto",
  attachmentName: "Nombre del archivo",
  templateName: "Nombre de plantilla aprobada",
  templateLanguage: "Idioma de la plantilla",
  templateParams: "Variables de la plantilla",
  status: "Estado",
  cursor: "Cursor de la página siguiente",
  limit: "Registros por página",
  sortOrder: "Orden",
  folder: "Carpeta",
  query: "Buscar texto",
  name: "Nombre",
  color: "Color",
  labelId: "ID de etiqueta",
  action: "Acción",
  targetAppId: "Aplicación destinataria",
  metadata: "Nota de transferencia",
  emoji: "Emoji",
  reaction: "Reacción",
  platform: "Plataforma",
  moderationStatus: "Moderación",
  banAuthor: "Bloquear autor",
  replyTo: "Responder al mensaje",
  messageTag: "Etiqueta de mensaje",
  messagingType: "Tipo de envío",
  quickReplies: "Respuestas rápidas",
  buttons: "Botones de elección",
  template: "Plantilla / carrusel",
  interactive: "Interactivo de WhatsApp",
  replyMarkup: "Teclado de Telegram",
  location: "Ubicación",
  contacts: "Tarjetas de contacto",
  linkPreview: "Vista previa de enlaces",
  voiceNote: "Nota de voz",
  headerMedia: "Imagen o archivo de cabecera",
  subject: "Asunto",
  cc: "Destinatarios en copia",
  since: "Desde (ISO 8601)",
  minRating: "Calificación mínima",
  maxRating: "Calificación máxima",
  hasReply: "Tiene respuesta",
  minComments: "Mínimo de comentarios",
};
export function InboxFields({
  schema,
  values,
  onChange,
  prefix,
  compact = false,
}: {
  schema: InboxSchema;
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  prefix: string;
  compact?: boolean;
}) {
  const id = useId();
  if (compact) {
    const primary = new Set([
      ...(schema.required ?? []),
      "message",
      "text",
      "attachmentUrl",
      "attachmentType",
      "templateName",
      "templateLanguage",
      "templateParams",
    ]);
    const properties = Object.entries(schema.properties ?? {}).filter(
      ([key]) => !["accountId", "profileId"].includes(key),
    );
    const core = Object.fromEntries(
      properties.filter(([key]) => primary.has(key)),
    );
    const extra = Object.fromEntries(
      properties.filter(([key]) => !primary.has(key)),
    );
    return (
      <>
        <InboxFields
          schema={{ ...schema, properties: core }}
          values={values}
          onChange={onChange}
          prefix={prefix}
        />
        {Object.keys(extra).length > 0 && (
          <details className="inbox-advanced-fields">
            <summary>
              Opciones avanzadas · {Object.keys(extra).length} campos
            </summary>
            <p>
              Botones, plantillas, ubicaciones y opciones específicas de cada
              canal. Usa únicamente las compatibles con la cuenta seleccionada.
            </p>
            <InboxFields
              schema={{ ...schema, properties: extra }}
              values={values}
              onChange={onChange}
              prefix={`${prefix}-advanced`}
            />
          </details>
        )}
      </>
    );
  }
  return (
    <div className="inbox-fields">
      {Object.entries(schema.properties ?? {})
        .filter(([key]) => !["accountId", "profileId"].includes(key))
        .map(([key, field]) => {
          const name = labels[key] ?? key;
          const required = schema.required?.includes(key);
          const value = values[key] ?? "";
          const inputId = `${id}-${prefix}-${key}`;
          const complex =
            ["object", "array"].includes(String(field.type)) ||
            field.anyOf ||
            field.oneOf;
          return (
            <label key={key} htmlFor={inputId}>
              <span>
                {name}
                {required ? " *" : ""}
              </span>
              {field.enum ? (
                <select
                  id={inputId}
                  value={value}
                  onChange={(e) => onChange(key, e.target.value)}
                >
                  <option value="">Sin especificar</option>
                  {field.enum.map((v) => (
                    <option key={String(v)} value={String(v)}>
                      {String(v)}
                    </option>
                  ))}
                </select>
              ) : field.type === "boolean" ? (
                <select
                  id={inputId}
                  value={value}
                  onChange={(e) => onChange(key, e.target.value)}
                >
                  <option value="">Predeterminado</option>
                  <option value="true">Sí</option>
                  <option value="false">No</option>
                </select>
              ) : complex ? (
                <>
                  <textarea
                    id={inputId}
                    value={value}
                    rows={4}
                    spellCheck={false}
                    placeholder={field.type === "array" ? "[]" : "{}"}
                    onChange={(e) => onChange(key, e.target.value)}
                  />
                  <small>
                    Estructura JSON del contrato de Zernio. Consulta los campos
                    en la referencia.
                  </small>
                  <details>
                    <summary>Ver estructura admitida</summary>
                    <pre>{JSON.stringify(field, null, 2)}</pre>
                  </details>
                </>
              ) : key === "message" || key === "text" ? (
                <textarea
                  id={inputId}
                  value={value}
                  rows={4}
                  maxLength={16000}
                  onChange={(e) => onChange(key, e.target.value)}
                />
              ) : (
                <input
                  id={inputId}
                  value={value}
                  type={
                    field.type === "integer" || field.type === "number"
                      ? "number"
                      : "text"
                  }
                  maxLength={16000}
                  onChange={(e) => onChange(key, e.target.value)}
                />
              )}
            </label>
          );
        })}
    </div>
  );
}
export function inboxFieldValues(
  schema: InboxSchema,
  values: Record<string, string>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    if (value === "") continue;
    const field = schema.properties?.[key];
    if (!field) continue;
    const type = field.type;
    result[key] =
      type === "integer" || type === "number"
        ? Number(value)
        : type === "boolean"
          ? value === "true"
          : type === "object" || type === "array" || field.anyOf || field.oneOf
            ? JSON.parse(value)
            : value;
  }
  return result;
}
