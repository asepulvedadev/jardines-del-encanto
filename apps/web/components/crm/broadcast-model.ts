export type BroadcastTemplate = {
  name: string;
  language: string;
  category: string;
  body: string;
  fields: { key: string; label: string; kind: string }[];
  issue: string | null;
};
export type BroadcastRecord = {
  id: string;
  name: string;
  account_id: string;
  template_name: string;
  template_language: string;
  preview: string;
  state: string;
  provider_id: string | null;
  provider_status: string | null;
  last_error: string | null;
  stats: Record<string, number>;
  version: number;
  recipient_count: number;
  recipients?: {
    contact_id: string;
    name: string;
    phone: string;
    status: string;
    cold: boolean;
  }[];
};
export const broadcastStates: Record<string, string> = {
  draft: "Borrador",
  preparing: "Preparando en Zernio",
  sending: "Enviando",
  submitted: "En proceso",
  completed: "Finalizada",
  failed: "Fallida",
  cancelled: "Cancelada",
  unknown: "Requiere revisión",
};
export function csvHeaders(text: string): string[] {
  const first = text.replace(/^\uFEFF/, "").split(/\r?\n/, 1)[0];
  const counts: Record<string, number> = { ",": 0, ";": 0, "\t": 0 };
  let quote = false;
  for (let i = 0; i < first.length; i++) {
    if (first[i] === '"') {
      if (quote && first[i + 1] === '"') i++;
      else quote = !quote;
    } else if (!quote && first[i] in counts) counts[first[i]]++;
  }
  const delimiter = Object.keys(counts).sort(
    (a, b) => counts[b] - counts[a],
  )[0];
  const fields: string[] = [];
  let field = "";
  quote = false;
  for (let i = 0; i < first.length; i++) {
    const c = first[i];
    if (c === '"') {
      if (quote && first[i + 1] === '"') {
        field += '"';
        i++;
      } else quote = !quote;
    } else if (c === delimiter && !quote) {
      fields.push(field);
      field = "";
    } else field += c;
  }
  fields.push(field);
  return fields;
}
export const broadcastErrors: Record<string, string> = {
  broadcast_columns_invalid:
    "Selecciona columnas distintas para nombre y celular. No repitas encabezados.",
  broadcast_csv_limit: "Divide el archivo en campañas de hasta 500 filas.",
  broadcast_csv_empty: "No encontramos contactos válidos en el CSV.",
  broadcast_csv_invalid: "El CSV no tiene un formato válido.",
  broadcast_csv_too_large: "El CSV debe pesar menos de 500 KB.",
  broadcast_fix_invalid_rows: "Corrige las filas marcadas antes de importar.",
  broadcast_variables_invalid:
    "Completa todos los valores de la plantilla. Los archivos requieren una URL HTTPS pública.",
  broadcast_template_unavailable:
    "La plantilla ya no está aprobada. Vuelve a cargarla.",
  broadcast_template_unsupported:
    "Esta plantilla requiere un formato no compatible con envíos masivos en este editor.",
  broadcast_changed:
    "La cuenta, plantilla o confirmación cambió. Revisa la campaña antes de enviar.",
  broadcast_already_attempted:
    "Esta campaña ya tiene un intento. Consulta su estado; no se repetirá el envío.",
  broadcast_busy:
    "La campaña se está procesando. Consulta su estado en unos segundos.",
  broadcast_templates_incomplete:
    "Zernio devolvió una lista incompleta de plantillas. No se puede asegurar su estado.",
  zernio_not_configured: "Conecta Zernio en Configuraciones → Conexiones.",
  connection_disabled: "Activa Zernio y WhatsApp en Configuraciones.",
};

/** Reserved cohort selectors stay separate from persisted broadcast UUIDs. */
export function leadCohortFilter(value: string) {
  if (value === "template" || value === "campaign") return { cohort: value };
  if (value === "cold") return { cold_only: true };
  return { campaign_id: value };
}
