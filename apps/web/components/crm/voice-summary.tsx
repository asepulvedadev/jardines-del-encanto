import type { Proposal } from "./settings-types";

const labels: Record<string, string> = {
  endpoint: "Operación",
  arguments: "Datos de la operación",
  requestBody: "Configuración",
  agent_id: "ID del agente",
  agent_name: "Nombre del agente",
  voice_id: "ID de la voz",
  voice_name: "Nombre de la voz",
  llm_id: "ID de las instrucciones",
  response_engine: "Motor de respuesta",
  general_prompt: "Instrucciones completas",
  begin_message: "Mensaje inicial",
  model: "Modelo",
  model_config: "Configuración del modelo",
  model_temperature: "Temperatura",
  temperature: "Temperatura",
  primary: "Modelo principal",
  backup: "Modelo de respaldo",
  type: "Tipo",
  language: "Idioma",
  voice_speed: "Velocidad de voz",
  voice_temperature: "Variación de voz",
  volume: "Volumen",
  responsiveness: "Capacidad de respuesta",
  interruption_sensitivity: "Sensibilidad a interrupciones",
  max_call_duration_ms: "Duración máxima de llamada (ms)",
  version: "Versión",
  enabled: "Activado",
  active: "Activo",
  from_number: "Número de origen",
  to_number: "Número de destino",
  contact_id: "ID del cliente",
  expected_phone: "Celular verificado",
  contacts: "Destinatarios del CRM",
  call_id: "ID de la llamada",
  call_status: "Estado de la llamada",
  phone_number: "Número de teléfono",
  provider: "Proveedor",
  status: "Estado",
  data: "Datos recibidos",
  retryable: "Permite repetir",
  session_id: "ID de la sesión",
  chat_id: "ID del chat",
  message: "Mensaje",
  content: "Contenido",
  limit: "Límite",
  pagination_key: "Cursor de paginación",
  sort_order: "Orden",
  recording_url: "Dirección de la grabación",
  transcript: "Transcripción",
  metadata: "Datos adicionales",
  knowledge_base_id: "ID de la base de conocimiento",
  knowledge_base_ids: "Bases de conocimiento",
  webhook_url: "Dirección del webhook",
  tools: "Herramientas",
  dynamic_variables: "Variables dinámicas",
  retell_llm_dynamic_variables: "Variables de las instrucciones",
  analysis: "Análisis",
};
const titles: Record<string, string> = {
  listAgents: "Consultar agentes",
  getAgent: "Consultar agente",
  createAgent: "Crear agente",
  updateAgent: "Editar agente",
  deleteAgent: "Eliminar agente",
  listVoices: "Consultar voces",
  getVoice: "Consultar voz",
  addCommunityVoice: "Agregar voz de la comunidad",
  cloneVoice: "Clonar voz",
  createWebCall: "Preparar prueba de voz en el navegador",
  createPhoneCall: "Crear llamada telefónica",
  createBatchCall: "Crear llamadas masivas",
  listCalls: "Consultar llamadas",
  getCall: "Consultar llamada",
  updateCall: "Editar llamada",
  deleteCall: "Eliminar llamada",
  createRetellLLM: "Crear instrucciones",
  updateRetellLLM: "Editar instrucciones",
  getRetellLLM: "Consultar instrucciones",
  listRetellLLMs: "Consultar instrucciones",
  deleteRetellLLM: "Eliminar instrucciones",
  listPhoneNumbers: "Consultar números",
  getPhoneNumber: "Consultar número",
  createPhoneNumber: "Crear número",
  updatePhoneNumber: "Editar número",
  deletePhoneNumber: "Eliminar número",
  createChat: "Crear conversación",
  createSmsChat: "Crear conversación por SMS",
  createChatCompletion: "Enviar mensaje",
  endChat: "Finalizar conversación",
};
const verbs: [string, string][] = [
  ["create", "Crear"],
  ["update", "Editar"],
  ["delete", "Eliminar"],
  ["list", "Consultar"],
  ["get", "Consultar"],
  ["publish", "Publicar"],
  ["add", "Agregar"],
  ["remove", "Quitar"],
  ["import", "Importar"],
  ["export", "Exportar"],
  ["start", "Iniciar"],
  ["stop", "Detener"],
];
function words(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
}
export function voiceFieldLabel(key: string): string {
  const fallback = words(key);
  return (
    labels[key] ??
    (fallback
      ? fallback[0].toLocaleUpperCase("es") + fallback.slice(1)
      : "Campo sin nombre")
  );
}
export function voiceOperationTitle(endpoint: unknown): string {
  if (typeof endpoint !== "string" || !endpoint) return "Operación de Retell";
  if (titles[endpoint]) return titles[endpoint];
  for (const [prefix, verb] of verbs)
    if (endpoint.startsWith(prefix) && endpoint.length > prefix.length)
      return `${verb} ${words(endpoint.slice(prefix.length))}`;
  return voiceFieldLabel(endpoint);
}

/** Render every supplied value; provider text is plain React text, never HTML. */
export function VoiceFields({ value }: { value: unknown }) {
  if (Array.isArray(value))
    return value.length ? (
      <ol className="voice-summary-list">
        {value.map((item, index) => (
          <li key={index}>
            <VoiceFields value={item} />
          </li>
        ))}
      </ol>
    ) : (
      <span className="voice-summary-empty">Lista vacía</span>
    );
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? (
      <dl className="voice-summary-fields">
        {entries.map(([key, child]) => (
          <div className="voice-summary-field" key={key}>
            <dt title={key}>{voiceFieldLabel(key)}</dt>
            <dd>
              <VoiceFields value={child} />
            </dd>
          </div>
        ))}
      </dl>
    ) : (
      <span className="voice-summary-empty">Objeto vacío</span>
    );
  }
  const text =
    value === null
      ? "Sin valor (null)"
      : value === undefined
        ? "Sin dato (undefined)"
        : value === true
          ? "Sí"
          : value === false
            ? "No"
            : value === ""
              ? "Texto vacío"
              : String(value);
  return <span className="voice-summary-value">{text}</span>;
}
export function VoiceTechnicalDetails({ value }: { value: unknown }) {
  return (
    <details className="voice-technical">
      <summary>Detalles técnicos</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function VoiceProposalSummary({ proposal }: { proposal: Proposal }) {
  return (
    <div className="voice-summary" aria-label="Cambios exactos propuestos">
      <p className="voice-summary-notice">
        {proposal.status === "pending"
          ? "Revisa todos los datos antes de aprobar. Esta propuesta todavía no se ha aplicado."
          : proposal.status === "approved"
            ? "La aprobación ya fue procesada. Revisa el resultado para confirmar el estado de la operación."
            : proposal.status === "rejected"
              ? "Propuesta rechazada. No se ejecutará desde esta revisión."
              : "La propuesta venció. Ya no puede aprobarse desde esta revisión."}
      </p>
      <VoiceFields value={proposal.arguments} />
      <VoiceTechnicalDetails value={proposal.arguments} />
    </div>
  );
}
const statuses: Record<string, string> = {
  completed: "Operación completada",
  ready: "Sesión preparada · pendiente de inicio",
  external_outcome_unconfirmed: "Resultado externo sin confirmar",
  dispatch_reserved: "Envío reservado · resultado sin confirmar",
  failed: "La operación no se completó",
  error: "Error de la operación",
};
export function VoiceResultSummary({
  result,
}: {
  result: Record<string, unknown>;
}) {
  const readable = {
    ...result,
    ...(typeof result.status === "string" && statuses[result.status]
      ? { status: statuses[result.status] }
      : {}),
    ...(typeof result.endpoint === "string"
      ? { endpoint: voiceOperationTitle(result.endpoint) }
      : {}),
    ...(result.provider === "retell" ? { provider: "Retell AI" } : {}),
  };
  return (
    <div className="voice-summary" aria-label="Datos del resultado">
      <strong>{statuses[String(result.status)] ?? "Resultado recibido"}</strong>
      {typeof result.endpoint === "string" ? (
        <p>{voiceOperationTitle(result.endpoint)}</p>
      ) : null}
      <VoiceFields value={readable} />
      <VoiceTechnicalDetails value={result} />
    </div>
  );
}
