export type CampaignVariable = {
  key: string;
  kind: "text" | "link";
  example: string;
};
export type CampaignButton = {
  kind: "reply" | "url";
  label: string;
  value: string;
};
export type CampaignDocument = {
  name: string;
  audience: "invitation" | "information" | "registered";
  suggested_date: string | null;
  image_id: string | null;
  body: string;
  variables: CampaignVariable[];
  buttons: CampaignButton[];
};
export type CampaignRecord = {
  id: string;
  version: number;
  status: "local_draft";
  document: CampaignDocument;
  updated_at: string | null;
  review?: { id: string; version: number; status: string } | null;
};
export const campaignAudiences = {
  invitation: "Invitación",
  information: "Información",
  registered: "Registrados",
} as const;
export const campaignToken = /\{\{([a-z][a-z0-9_]{0,39})\}\}/g;
export const campaignMedia = (id: string) =>
  `/api/crm/campaigns/media/${encodeURIComponent(id)}`;
export function renderCampaignText(
  text: string,
  variables: Pick<CampaignVariable, "key" | "example">[],
) {
  const values = new Map(
    variables.map((variable) => [variable.key, variable.example]),
  );
  return text.replace(
    campaignToken,
    (token, key: string) => values.get(key) ?? token,
  );
}
export function safeCampaignLink(value: string) {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.port &&
      url.hostname.includes(".") &&
      !/^[\d.]+$/.test(url.hostname) &&
      !url.hostname.startsWith("[") &&
      !/\.(local|localhost|internal)$/.test(url.hostname) &&
      !/[\s{}\\\x00-\x1f]/.test(value)
    );
  } catch {
    return false;
  }
}
export function campaignIssues(doc: CampaignDocument): string[] {
  const issues: string[] = [];
  if (
    new TextEncoder().encode(
      JSON.stringify({ version: 2147483646, document: doc }),
    ).byteLength > 16384
  )
    issues.push(
      "El borrador es demasiado grande. Acorta el mensaje o los ejemplos de variables.",
    );
  const keys = new Set(doc.variables.map((variable) => variable.key));
  if (!doc.name.trim() || doc.name.length > 100)
    issues.push("Escribe un nombre de hasta 100 caracteres.");
  if (!doc.body.trim() || doc.body.length > 1024)
    issues.push("El mensaje debe tener entre 1 y 1.024 caracteres.");
  if (doc.variables.length > 12 || keys.size !== doc.variables.length)
    issues.push("Usa hasta 12 variables, sin nombres repetidos.");
  for (const variable of doc.variables) {
    if (
      !/^[a-z][a-z0-9_]{0,39}$/.test(variable.key) ||
      !variable.example.trim() ||
      variable.example.length > 1000 ||
      /[{}]/.test(variable.example)
    )
      issues.push(
        "Cada variable necesita un nombre válido y un ejemplo sin otras variables.",
      );
    if (variable.kind === "link" && !safeCampaignLink(variable.example))
      issues.push(
        "Los enlaces deben ser HTTPS públicos, sin usuario ni contraseña.",
      );
  }
  for (const text of [doc.body, ...doc.buttons.map((button) => button.value)]) {
    const unknown = [...text.matchAll(campaignToken)].some(
      (match) => !keys.has(match[1]),
    );
    if (unknown || /[{}]/.test(text.replace(campaignToken, "")))
      issues.push(
        "Hay variables sin definir o llaves incompletas en el mensaje o los botones.",
      );
  }
  if (
    doc.buttons.length > 3 ||
    new Set(doc.buttons.map((b) => b.label.trim().toLowerCase())).size !==
      doc.buttons.length
  )
    issues.push("Usa hasta tres botones con nombres diferentes.");
  for (const button of doc.buttons) {
    if (
      !button.label.trim() ||
      button.label.length > 25 ||
      !button.value.trim() ||
      button.value.length > 1000
    )
      issues.push(
        "Cada botón necesita un texto de hasta 25 caracteres y un valor.",
      );
    if (button.kind === "url") {
      const match = /^\{\{([a-z][a-z0-9_]{0,39})\}\}$/.exec(button.value);
      if (
        match
          ? !doc.variables.some((v) => v.key === match[1] && v.kind === "link")
          : !safeCampaignLink(button.value)
      )
        issues.push(
          "El botón de enlace necesita una URL HTTPS o una variable de tipo enlace completa.",
        );
    } else if (button.value.length > 80 || /[{}]/.test(button.value))
      issues.push(
        "La respuesta del botón debe ser una clave de hasta 80 caracteres, sin variables.",
      );
  }
  return [...new Set(issues)];
}
export function emptyCampaign(): CampaignDocument {
  return {
    name: "Nueva plantilla",
    audience: "invitation",
    suggested_date: null,
    image_id: "campaign-01",
    body: "Hola {{nombre}}, conoce Jardines del Encanto en {{enlace_proyecto}}.\n\nSi prefieres no recibir información, responde SALIR.",
    variables: [
      { key: "nombre", kind: "text", example: "María" },
      {
        key: "enlace_proyecto",
        kind: "link",
        example: "https://jardinesdelencanto.site/",
      },
    ],
    buttons: [
      { kind: "url", label: "Ver proyecto", value: "{{enlace_proyecto}}" },
      { kind: "reply", label: "Quiero información", value: "informacion" },
    ],
  };
}

export type CampaignReview = {
  id: string;
  slug: string;
  version: number;
  account_id: string;
  account_label: string;
  name: string;
  snapshot: CampaignDocument;
  status: string;
  provider_id: string | null;
  category: string | null;
  created_at: string;
  checked_at: string | null;
};
export const campaignReviewLabels: Record<string, string> = {
  SUBMITTING: "Solicitud registrada",
  UNKNOWN: "Resultado por confirmar",
  PENDING: "En revisión",
  APPROVED: "Aprobada",
  REJECTED: "Rechazada",
  IN_APPEAL: "En apelación",
  PAUSED: "Pausada",
  DISABLED: "Deshabilitada",
  PENDING_DELETION: "Pendiente de eliminación",
};
export const campaignReviewErrors: Record<string, string> = {
  zernio_not_configured:
    "Conecta Zernio y tu cuenta de WhatsApp desde Configuración antes de enviar a revisión.",
  zernio_configuration_unavailable:
    "La conexión de Zernio no está disponible. Revisa Configuración.",
  zernio_workflow_unavailable:
    "No pudimos consultar las cuentas de Zernio. Intenta actualizar la conexión.",
  review_account_unavailable:
    "La cuenta no está activa o no pertenece a la conexión actual. Vuelve a seleccionarla.",
  review_public_media_origin_required:
    "Para revisar imágenes, configura CAMPAIGN_MEDIA_ORIGIN con el origen HTTPS público del CRM. La URL local no es accesible para Zernio.",
  review_button_groups_required:
    "Meta admite hasta dos botones de enlace. Agrupa los botones del mismo tipo juntos antes de guardar.",
  review_save_current_version:
    "Guarda la versión actual antes de enviarla a revisión.",
  review_already_requested:
    "Esta versión ya tiene una solicitud para esa cuenta. Consulta su estado; no se volvió a enviar.",
  review_provider_unavailable:
    "No pudimos verificar la respuesta de Zernio. Consulta el historial y actualiza el estado antes de continuar.",
  review_profile_changed:
    "Esta solicitud pertenece a otra conexión de Zernio. Restablece esa conexión para consultar su estado.",
  review_not_found_at_provider:
    "Zernio aún no devuelve esta plantilla de forma inequívoca. El estado anterior se conserva. No la reenvíes; consulta nuevamente más tarde.",
};
