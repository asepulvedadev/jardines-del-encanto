import type { RetellSchema } from "./retell-schema";

export type VoiceSchema = Omit<RetellSchema, "properties"> & {
  properties?: Record<string, VoiceSchema>;
  allOf?: VoiceSchema[];
  oneOf?: VoiceSchema[];
  anyOf?: VoiceSchema[];
  items?: VoiceSchema;
  additionalProperties?: boolean | VoiceSchema;
  nullable?: boolean;
  description?: string;
  deprecated?: boolean;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
  pattern?: string;
  format?: string;
  readOnly?: boolean;
};
export type VoiceSchemaDraft = {
  enabled: boolean;
  blocked?: boolean;
  null?: boolean;
  branch?: number;
  raw?: string;
  children?: Record<string, VoiceSchemaDraft>;
  items?: VoiceSchemaDraft[];
  entries?: { key: string; draft: VoiceSchemaDraft }[];
};
export type VoiceSchemaDrafts = Record<string, VoiceSchemaDraft>;
export type VoiceSchemaInventoryEntry = {
  key: string;
  label: string;
  section: string;
  schema: VoiceSchema;
  support: "native" | "blocked";
  reason?: string;
};
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export function voiceSchemaResolve(input: VoiceSchema): VoiceSchema {
  let result: VoiceSchema = { ...input, allOf: undefined };
  for (const part of input.allOf ?? []) {
    const next = voiceSchemaResolve(part);
    result = {
      ...next,
      ...result,
      properties: { ...next.properties, ...result.properties },
      required: [
        ...new Set([...(next.required ?? []), ...(result.required ?? [])]),
      ],
      enum: result.enum ?? next.enum,
      oneOf: result.oneOf ?? next.oneOf,
      anyOf: result.anyOf ?? next.anyOf,
      type: result.type ?? next.type,
    };
  }
  return result;
}
export function voiceSchemaProperties(
  schema: VoiceSchema,
): Record<string, VoiceSchema> {
  return voiceSchemaResolve(schema).properties ?? {};
}
export function voiceSchemaVariants(input: VoiceSchema): VoiceSchema[] {
  const schema = voiceSchemaResolve(input);
  const variants = schema.oneOf ?? schema.anyOf;
  if (!variants) return [];
  const base = { ...schema, oneOf: undefined, anyOf: undefined };
  return variants
    .filter((item) => !(item.enum?.length === 1 && item.enum[0] === null))
    .map((item) => voiceSchemaResolve({ allOf: [base, item] }));
}
export function voiceSchemaNullable(input: VoiceSchema): boolean {
  const schema = voiceSchemaResolve(input);
  return (
    !!schema.nullable ||
    !!schema.enum?.includes(null) ||
    [...(schema.oneOf ?? []), ...(schema.anyOf ?? [])].some(voiceSchemaNullable)
  );
}
export function voiceSchemaType(input: VoiceSchema): string {
  const schema = voiceSchemaResolve(input);
  if (schema.enum?.length === 1 && schema.enum[0] === null) return "null";
  if (Array.isArray(schema.type))
    return schema.type.find((type) => type !== "null") ?? "null";
  return (
    schema.type ??
    (schema.properties || schema.additionalProperties !== undefined
      ? "object"
      : schema.items
        ? "array"
        : "any")
  );
}
export function voiceSchemaComplex(schema: VoiceSchema, key = ""): boolean {
  return (
    voiceSchemaVariants(schema).length > 0 ||
    ["object", "array", "any"].includes(voiceSchemaType(schema)) ||
    /prompt|message|description|content|^code$|(?:_url|url)$/.test(key)
  );
}
export function voiceSensitivePath(path: string): boolean {
  return path.split(/[.\[\]]/).some((part) => {
    const key = part.replace(/[^a-z0-9]/gi, "").toLowerCase();
    return (
      ["__proto__", "prototype", "constructor"].includes(part) ||
      /header|password|passwd|secret|credential|authorization|authentication|apikey|accesskey|token|privatekey|encryptionkey|signature|bearer|oauth/.test(
        key,
      ) ||
      ["token", "auth", "key", "sig", "sas"].includes(key)
    );
  });
}
const labels: Record<string, string> = {
  requestBody: "Configuración",
  input_topics: "Temas de entrada",
  output_topics: "Temas de salida",
  ai_disclosure: "Identificación como inteligencia artificial",
  conversational_personality: "Personalidad de conversación",
  default_personality: "Personalidad predeterminada",
  echo_verification: "Verificación de datos repetidos",
  high_empathy: "Empatía reforzada",
  nato_phonetic_alphabet: "Alfabeto fonético internacional",
  natural_filler_words: "Pausas y expresiones naturales",
  scope_boundaries: "Límites de la conversación",
  smart_matching: "Coincidencias inteligentes",
  speech_normalization: "Normalización del habla",
  action: "Acción",
  detection_prompt: "Instrucciones de detección",
  categories: "Categorías",
  mode: "Modo",
  conditional_prompt: "Instrucciones condicionales",
  app_id: "Aplicación",
  app_tool_template_name: "Plantilla de función",
  enable_typing_sound: "Sonido de escritura",
  execution_message_type: "Tipo de mensaje de ejecución",
  execution_status_variable: "Variable del estado de ejecución",
  output_selection: "Selección de resultados",
  fields: "Campos",
  additionalProperties: "Propiedades adicionales",
  args_at_root: "Argumentos en la raíz",
  max_retry: "Reintentos máximos",
  parameter_type: "Tipo de parámetro",
  code: "Código de la función",
  sms_content: "Contenido del mensaje SMS",
  text: "Texto",
  template: "Plantilla",
  sms_destination: "Destino del SMS",
  ignore_e164_validation: "Omitir validación telefónica E.164",
  phone_number: "Número de teléfono",
  sms_sender: "Remitente del SMS",
  condition: "Condición",
  equations: "Comparaciones",
  left: "Valor izquierdo",
  operator: "Operador",
  right: "Valor derecho",
  depends_on: "Dependencias",
  digit_limit: "Límite de dígitos",
  termination_key: "Tecla para finalizar",
  custom_sip_headers: "Encabezados SIP privados",
  extension: "Extensión",
  cold_transfer_mode: "Transferencia directa",
  custom_on_hold_music_asset_id: "Audio de espera personalizado",
  on_hold_music: "Música de espera",
  show_transferee_as_caller: "Mostrar el destinatario como origen",
  transfer_ring_duration_ms: "Timbrado de transferencia (ms)",
  agent_detection_timeout_ms: "Espera para detectar agente (ms)",
  enable_bridge_audio_cue: "Señal de audio al conectar",
  opt_out_human_detection: "Desactivar detección humana",
  private_handoff_option: "Entrega privada",
  message: "Mensaje",
  public_handoff_option: "Entrega pública",
  agentic_transfer_config: "Transferencia entre agentes",
  action_on_timeout: "Acción al agotar la espera",
  transfer_agent: "Agente de destino",
  agent_version: "Versión del agente",
  transfer_timeout_ms: "Espera de transferencia (ms)",
  keep_current_language: "Conservar idioma actual",
  keep_current_voice: "Conservar voz actual",
  post_call_analysis_setting: "Extracción de la transferencia",
  use_swap_agent_max_duration: "Usar duración máxima del agente de destino",
  webhook_setting: "Webhook de transferencia",
  delay_ms: "Pausa (ms)",
  variables: "Variables",
  edges: "Transiciones",
  destination_state_name: "Estado de destino",
  state_prompt: "Instrucciones del estado",
  tools: "Funciones",
  agent_name: "Nombre del agente",
  voice_id: "Voz del agente",
  language: "Idioma",
  response_engine: "Motor de respuesta completo",
  allow_dtmf_interruption: "Permitir interrupciones con el teclado",
  allow_user_dtmf: "Aceptar tonos del teclado",
  ambient_sound: "Sonido ambiente",
  ambient_sound_volume: "Volumen del ambiente",
  backchannel_frequency: "Frecuencia de interjecciones",
  backchannel_words: "Palabras de acompañamiento",
  begin_message_delay_ms: "Pausa antes de hablar (ms)",
  boosted_keywords: "Palabras destacadas para transcripción",
  call_screening_option: "Filtro de llamadas",
  contact_memory_config: "Memoria de contactos",
  custom_stt_config: "Transcripción personalizada",
  data_storage_retention_days: "Retención de datos (días)",
  data_storage_setting: "Datos almacenados",
  denoising_enhancement_level: "Intensidad de limpieza de audio",
  denoising_mode: "Reducción de ruido",
  enable_backchannel: "Activar interjecciones",
  enable_dnc_detection: "Detectar solicitudes de no contacto",
  enable_dynamic_responsiveness: "Respuesta dinámica",
  enable_dynamic_voice_speed: "Velocidad dinámica",
  enable_expressive_mode: "Voz expresiva",
  end_call_after_silence_ms: "Finalizar tras silencio (ms)",
  expressive_emotion_tags: "Emociones de la voz",
  expressive_mode_prompt: "Instrucciones de expresividad",
  fallback_voice_ids: "Voces de respaldo",
  guardrail_config: "Protección de conversación",
  handbook_config: "Manual del agente",
  interruption_sensitivity: "Sensibilidad a interrupciones",
  ivr_option: "Navegación IVR",
  max_call_duration_ms: "Duración máxima (ms)",
  opt_in_signed_url: "Usar enlaces firmados",
  pii_config: "Datos personales sensibles",
  post_call_analysis_data: "Campos de extracción posterior",
  post_call_analysis_model: "Modelo de extracción",
  post_session_tools: "Funciones posteriores a la sesión",
  pre_session_tools: "Funciones previas a la sesión",
  pronunciation_dictionary: "Diccionario de pronunciación",
  reminder_max_count: "Cantidad máxima de recordatorios",
  reminder_trigger_ms: "Espera para recordatorio (ms)",
  responsiveness: "Capacidad de respuesta",
  ring_duration_ms: "Tiempo de timbrado (ms)",
  signed_url_expiration_ms: "Vigencia del enlace firmado (ms)",
  stt_mode: "Modo de transcripción",
  timezone: "Zona horaria",
  user_dtmf_options: "Opciones del teclado",
  version_description: "Descripción de versión",
  version_title: "Título de versión",
  vocab_specialization: "Vocabulario especializado",
  voice_model: "Modelo de voz",
  voice_speed: "Velocidad de voz",
  voice_temperature: "Variación de la voz",
  voicemail_option: "Buzón de voz",
  volume: "Volumen",
  webhook_events: "Eventos del webhook",
  webhook_timeout_ms: "Espera del webhook (ms)",
  webhook_url: "Dirección del webhook",
  is_transfer_agent: "Agente para transferencias",
  backup_model: "Modelo de respaldo heredado",
  begin_after_user_silence_ms: "Comenzar tras silencio de la persona (ms)",
  begin_message: "Mensaje inicial completo",
  kb_config: "Recuperación de conocimiento",
  knowledge_base_ids: "Bases de conocimiento",
  model: "Modelo de respuesta",
  model_config: "Configuración completa del modelo",
  model_high_priority: "Prioridad alta heredada",
  model_temperature: "Temperatura heredada",
  model_ultrafast: "Modo ultrarrápido heredado",
  s2s_model: "Modelo de voz a voz heredado",
  start_speaker: "Quién habla primero",
  default_dynamic_variables: "Variables dinámicas predeterminadas",
  general_prompt: "Instrucciones completas",
  general_tools: "Funciones del agente",
  is_transfer_llm: "Instrucciones para transferencias",
  mcps: "Servidores MCP",
  starting_state: "Estado inicial",
  states: "Estados heredados",
  voice_prompt: "Instrucciones del modelo de voz",
  type: "Tipo",
  name: "Nombre",
  description: "Descripción",
  model_config_type: "Tipo de modelo",
  primary: "Modelo principal",
  backup: "Modelo de respaldo",
  backend: "Modelo de apoyo",
  temperature: "Temperatura",
  tier: "Nivel de capacidad",
  high_priority: "Prioridad alta",
  ultrafast: "Ultrarrápido",
  model_temperature_value: "Temperatura",
  llm_id: "Instrucciones Retell LLM",
  conversation_flow_id: "Flujo de conversación",
  llm_websocket_url: "Dirección del modelo personalizado",
  version: "Versión",
  provider: "Proveedor",
  endpointing_ms: "Detección de fin de turno (ms)",
  filter_score: "Puntaje mínimo de similitud",
  top_k: "Fragmentos recuperados",
  enable_read: "Leer memoria",
  enable_update: "Actualizar memoria",
  url: "Dirección",
  method: "Método",
  parameters: "Parámetros de entrada",
  properties: "Propiedades",
  required: "Campos obligatorios",
  items: "Elementos",
  enum: "Valores permitidos",
  headers: "Encabezados privados",
  query_params: "Parámetros de consulta",
  response_variables: "Variables de respuesta",
  timeout_ms: "Tiempo de espera (ms)",
  speak_during_execution: "Hablar durante la ejecución",
  speak_after_execution: "Hablar después de ejecutar",
  execution_message_description: "Mensaje durante la ejecución",
  response_message_description: "Mensaje posterior",
  tool_id: "Función",
  mcp_id: "Servidor MCP",
  agent_id: "Agente",
  word: "Palabra",
  alphabet: "Alfabeto fonético",
  phoneme: "Pronunciación",
  choices: "Opciones",
  examples: "Ejemplos",
  instruction: "Instrucción",
  prompt: "Instrucciones",
  destination: "Destino",
  number: "Número",
  transfer_destination: "Destino de transferencia",
  transfer_option: "Opciones de transferencia",
  agent_identity: "Identidad del agente",
  call_purpose: "Motivo de la llamada",
  kick_in_timeout_ms: "Espera para activar el respaldo (ms)",
  backup_kick_in_timeout: "Espera del respaldo (ms)",
  tool_call_id: "Identificador de función",
  static: "Valor fijo",
  dynamic: "Valor dinámico",
  value: "Valor",
  body: "Contenido",
  input_schema: "Esquema de entrada",
};
export function voiceSchemaLabel(key: string): string {
  return labels[key] ?? key.replace(/_/g, " ");
}
export function voiceSchemaOptionLabel(value: unknown): string {
  const options: Record<string, string> = {
    agent: "El agente",
    user: "La persona",
    cascading: "Texto con voz separada",
    s2s: "Voz a voz",
    duplex: "Voz dúplex",
    "retell-llm": "Instrucciones Retell LLM",
    "custom-llm": "Modelo personalizado",
    "conversation-flow": "Flujo de conversación",
    standard: "Estándar",
    fast: "Rápido",
    ultrafast: "Ultrarrápido",
    everything: "Todos los datos",
    everything_except_pii: "Todo excepto datos personales sensibles",
    basic_attributes_only: "Solo atributos básicos",
  };
  return typeof value === "boolean"
    ? value
      ? "Activo"
      : "Inactivo"
    : (options[String(value)] ?? String(value));
}
export function voiceSchemaSection(key: string): string {
  if (/webhook/.test(key)) return "Webhooks";
  if (/mcp/.test(key)) return "Servidores MCP";
  if (/post_call_analysis/.test(key))
    return "Extracción posterior a la llamada";
  if (/contact_memory/.test(key)) return "Memoria posterior a la llamada";
  if (/knowledge|^kb_|handbook|dynamic_variables/.test(key))
    return "Conocimiento y memoria";
  if (/tools|^states$|starting_state/.test(key)) return "Funciones";
  if (/stt|transcri|boosted|vocab/.test(key))
    return "Transcripción en tiempo real";
  if (/storage|pii|guardrail|fallback|signed|dnc/.test(key))
    return "Seguridad y respaldo";
  if (
    /voice|ambient|backchannel|expressive|volume|pronunciation|responsiveness|interruption/.test(
      key,
    )
  )
    return "Ajustes de voz";
  if (/call|ring|dtmf|reminder|silence|begin|speaker|ivr|timezone/.test(key))
    return "Ajustes de llamada";
  return "Agente, modelo e instrucciones";
}
export function voiceSchemaInventory(
  schema: VoiceSchema,
): VoiceSchemaInventoryEntry[] {
  const body = voiceSchemaProperties(schema).requestBody ?? schema;
  return Object.entries(voiceSchemaProperties(body)).map(([key, value]) => ({
    key,
    label: voiceSchemaLabel(key),
    section: voiceSchemaSection(key),
    schema: value,
    support: voiceSensitivePath(key) || value.readOnly ? "blocked" : "native",
    reason: voiceSensitivePath(key)
      ? "Las credenciales y los encabezados privados se administran directamente en Retell."
      : value.readOnly
        ? "El proveedor marca este campo como solo lectura."
        : undefined,
  }));
}
export function voiceEmptyDraft(input: VoiceSchema): VoiceSchemaDraft {
  const schema = voiceSchemaResolve(input);
  const type = voiceSchemaType(schema);
  if (voiceSchemaVariants(schema).length) return { enabled: true };
  if (type === "array") return { enabled: true, items: [] };
  if (type === "object") {
    const children: VoiceSchemaDrafts = {};
    for (const [key, value] of Object.entries(voiceSchemaProperties(schema))) {
      const resolved = voiceSchemaResolve(value);
      if (
        schema.required?.includes(key) &&
        resolved.enum?.length === 1 &&
        resolved.enum[0] !== null &&
        !voiceSensitivePath(key)
      )
        children[key] = { enabled: true, raw: String(resolved.enum[0]) };
    }
    return { enabled: true, children, entries: [] };
  }
  return {
    enabled: true,
    raw:
      schema.enum?.length === 1 && schema.enum[0] !== null
        ? String(schema.enum[0])
        : "",
  };
}
export const voiceAnySchemas: VoiceSchema[] = [
  { type: "string", title: "Texto" },
  { type: "number", title: "Número" },
  { type: "boolean", title: "Sí o no" },
  { type: "object", title: "Objeto", additionalProperties: true },
  { type: "array", title: "Lista", items: {} },
  { enum: [null], title: "Sin valor" },
];
export function voicePrivateUrl(value: string): boolean {
  // Match the URL parser's whitespace normalization before detecting its scheme.
  const normalized = value.trim().replace(/[\t\r\n]/g, "");
  const relative = /^[\\/]{2}/.test(normalized);
  if (!relative && !/^[a-z][a-z0-9+.-]*:/i.test(normalized)) return false;
  try {
    const url = new URL(relative ? `https:${normalized}` : normalized);
    return (
      !!url.username ||
      !!url.password ||
      [...url.searchParams.keys()].some(voiceSensitivePath)
    );
  } catch {
    return true;
  }
}
function safeText(value: string, path: string) {
  if (voicePrivateUrl(value))
    throw new Error(
      `Revisa ${voiceSchemaLabel(path.split(".").at(-1) ?? path)}. No se permiten direcciones con credenciales.`,
    );
}
function parseDraft(
  input: VoiceSchema,
  draft: VoiceSchemaDraft,
  path: string,
  depth = 0,
): unknown {
  const label = voiceSchemaLabel(path.split(".").at(-1) ?? path);
  const invalid = () =>
    new Error(
      `Revisa ${label}: completa los campos obligatorios y respeta los valores permitidos.`,
    );
  if (draft.blocked || depth > 24 || voiceSensitivePath(path))
    throw new Error(
      `No se permite editar ${label}. Adminístralo directamente en Retell.`,
    );
  const schema = voiceSchemaResolve(input);
  if (draft.null) {
    if (!voiceSchemaNullable(schema)) throw invalid();
    return null;
  }
  const type = voiceSchemaType(schema);
  const variants = voiceSchemaVariants(schema);
  if (variants.length || type === "any") {
    const choices = variants.length ? variants : voiceAnySchemas;
    if (draft.branch === undefined || !choices[draft.branch]) throw invalid();
    return parseDraft(
      choices[draft.branch],
      { ...draft, branch: undefined },
      path,
      depth + 1,
    );
  }
  if (type === "null") return null;
  if (type === "object") {
    const result: Record<string, unknown> = {};
    const properties = voiceSchemaProperties(schema);
    for (const [key, child] of Object.entries(draft.children ?? {})) {
      if (!child.enabled) continue;
      if (!Object.hasOwn(properties, key)) throw invalid();
      Object.defineProperty(result, key, {
        value: parseDraft(properties[key], child, `${path}.${key}`, depth + 1),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    for (const { key, draft: child } of draft.entries ?? []) {
      if (!child.enabled) continue;
      if (
        !key.trim() ||
        voiceSensitivePath(key) ||
        Object.hasOwn(result, key) ||
        Object.hasOwn(properties, key) ||
        schema.additionalProperties === false ||
        (schema.additionalProperties === undefined &&
          Object.keys(properties).length > 0)
      )
        throw invalid();
      const valueSchema = record(schema.additionalProperties)
        ? (schema.additionalProperties as VoiceSchema)
        : {};
      Object.defineProperty(result, key, {
        value: parseDraft(valueSchema, child, `${path}.${key}`, depth + 1),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    for (const key of schema.required ?? [])
      if (!Object.hasOwn(result, key)) throw invalid();
    return result;
  }
  if (type === "array") {
    const values = (draft.items ?? []).map((item, index) => {
      if (!item.enabled) throw invalid();
      return parseDraft(
        schema.items ?? {},
        item,
        `${path}.${index}`,
        depth + 1,
      );
    });
    if (
      (schema.minItems !== undefined && values.length < schema.minItems) ||
      (schema.maxItems !== undefined && values.length > schema.maxItems) ||
      (schema.uniqueItems &&
        new Set(values.map((value) => JSON.stringify(value))).size !==
          values.length)
    )
      throw invalid();
    return values;
  }
  const raw = draft.raw ?? "";
  let value: unknown = raw;
  if (type === "boolean") {
    if (!["true", "false"].includes(raw)) throw invalid();
    value = raw === "true";
  } else if (["number", "integer"].includes(type)) {
    value = Number(raw);
    if (
      !raw.trim() ||
      !Number.isFinite(value) ||
      (type === "integer" && !Number.isInteger(value)) ||
      (schema.minimum !== undefined && Number(value) < schema.minimum) ||
      (schema.maximum !== undefined && Number(value) > schema.maximum)
    )
      throw invalid();
  } else {
    if ((/(?:_id|_url)$/.test(path) || /_ids\.\d+$/.test(path)) && !raw.trim())
      throw invalid();
    if (
      (schema.minLength !== undefined && raw.length < schema.minLength) ||
      (schema.maxLength !== undefined && raw.length > schema.maxLength)
    )
      throw invalid();
    if (schema.pattern) {
      try {
        if (!new RegExp(schema.pattern).test(raw)) throw invalid();
      } catch {
        throw invalid();
      }
    }
    safeText(raw, path);
  }
  if (schema.enum && !schema.enum.includes(value)) throw invalid();
  return value;
}
export function voiceSchemaPatch(
  input: VoiceSchema,
  drafts: VoiceSchemaDrafts,
  current?: Record<string, unknown>,
): Record<string, unknown> {
  const schema = voiceSchemaResolve(input);
  const properties = voiceSchemaProperties(schema);
  const result: Record<string, unknown> = {};
  for (const [key, draft] of Object.entries(drafts)) {
    if (!draft.enabled) continue;
    if (
      !Object.hasOwn(properties, key) ||
      voiceSensitivePath(key) ||
      properties[key].readOnly
    )
      throw new Error(
        "El borrador contiene un campo no permitido. Administra los datos privados en Retell.",
      );
    const value = parseDraft(properties[key], draft, key);
    if (
      !voiceSchemaComplex(properties[key], key) &&
      current &&
      value === current[key]
    )
      continue;
    Object.defineProperty(result, key, {
      value,
      enumerable: true,
      writable: true,
      configurable: true,
    });
  }
  return result;
}
export function voiceSchemaHint(input: VoiceSchema): string {
  const schema = voiceSchemaResolve(input);
  const parts = [
    schema.minimum === undefined ? "" : `Mínimo: ${schema.minimum}.`,
    schema.maximum === undefined ? "" : `Máximo: ${schema.maximum}.`,
    schema.minLength === undefined
      ? ""
      : `Desde ${schema.minLength} caracteres.`,
    schema.maxLength === undefined
      ? ""
      : `Hasta ${schema.maxLength} caracteres.`,
    schema.minItems === undefined ? "" : `Desde ${schema.minItems} elementos.`,
    schema.maxItems === undefined ? "" : `Hasta ${schema.maxItems} elementos.`,
    schema.deprecated
      ? "Opción heredada del proveedor; se recomienda la configuración vigente."
      : "",
  ];
  return parts.filter(Boolean).join(" ");
}
