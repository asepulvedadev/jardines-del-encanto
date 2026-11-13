import type { RetellSchema } from "./retell-schema";
import {
  voiceSchemaPatch,
  voiceHydrateField,
  type VoiceSchemaDrafts,
} from "./voice-schema-model";

type ComposedSchema = RetellSchema & {
  allOf?: ComposedSchema[];
  oneOf?: ComposedSchema[];
  anyOf?: ComposedSchema[];
};
export type VoiceEditorKind = "agent" | "instructions";
export type VoiceReplacements = Partial<
  Record<"response_engine" | "general_prompt" | "begin_message", boolean>
>;
export type VoiceEditorField = {
  key: string;
  label: string;
  schema: RetellSchema;
  multiline?: boolean;
};
const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const primitive = (value: unknown) =>
  typeof value === "string" ||
  (typeof value === "number" && Number.isFinite(value))
    ? String(value)
    : "";
const groups = (schema: ComposedSchema) => [
  ...(schema.allOf ?? []),
  ...(schema.oneOf ?? []),
  ...(schema.anyOf ?? []),
];

// Properties may be declared in an allOf mixin rather than on requestBody.
function property(
  schema: ComposedSchema | undefined,
  name: string,
): ComposedSchema | undefined {
  if (!schema) return undefined;
  const direct = schema.properties?.[name];
  if (direct) return direct as ComposedSchema;
  for (const branch of groups(schema)) {
    const found = property(branch, name);
    if (found) return found;
  }
  return undefined;
}
function scalar(schema: ComposedSchema | undefined): RetellSchema | undefined {
  if (!schema) return undefined;
  const own = ["string", "integer", "number"].includes(String(schema.type));
  let result: RetellSchema | undefined = own ? { ...schema } : undefined;
  for (const branch of schema.allOf ?? []) {
    const child = scalar(branch);
    if (child)
      result = { ...child, ...result, enum: result?.enum ?? child.enum };
  }
  if (!result) {
    for (const branch of [...(schema.oneOf ?? []), ...(schema.anyOf ?? [])]) {
      const child = scalar(branch);
      if (child) return child;
    }
  }
  return result;
}
function modelBranch(
  schema: ComposedSchema | undefined,
  record?: Record<string, unknown>,
) {
  if (!schema) return undefined;
  const config = isRecord(record?.model_config)
    ? record.model_config
    : undefined;
  const type = config ? text(config.type) : "cascading";
  const candidates = groups(schema);
  return (
    candidates.find((candidate) =>
      scalar(property(candidate, "type"))?.enum?.includes(type),
    ) ??
    (scalar(property(schema, "type"))?.enum?.includes(type)
      ? schema
      : undefined)
  );
}

const agentLabels = [
  ["agent_name", "Nombre del agente"],
  ["voice_id", "Voz del agente"],
  ["language", "Idioma"],
  ["voice_speed", "Velocidad de voz"],
  ["responsiveness", "Capacidad de respuesta"],
  ["interruption_sensitivity", "Sensibilidad a interrupciones"],
  ["max_call_duration_ms", "Duración máxima de llamada (ms)"],
] as const;
export function voiceEditorFields(
  kind: VoiceEditorKind,
  schema: RetellSchema,
  record?: Record<string, unknown>,
): VoiceEditorField[] {
  const body = property(schema, "requestBody");
  if (kind === "agent")
    return agentLabels.flatMap(([key, label]) => {
      const fieldSchema = scalar(property(body, key));
      return fieldSchema ? [{ key, label, schema: fieldSchema }] : [];
    });
  const config =
    !record || record.model_config !== undefined
      ? property(body, "model_config")
      : undefined;
  const branch = modelBranch(config, record);
  const model = config
    ? scalar(property(property(branch, "primary"), "model"))
    : scalar(property(body, "model"));
  const temperature = config
    ? scalar(property(branch, "temperature"))
    : scalar(property(body, "model_temperature"));
  return [
    ...(model
      ? [{ key: "model", label: "Modelo de respuesta", schema: model }]
      : []),
    ...(
      [
        ["general_prompt", "Prompt del agente (completo)"],
        ["begin_message", "Saludo inicial (completo)"],
      ] as const
    ).flatMap(([key, label]) => {
      const fieldSchema = scalar(property(body, key));
      return fieldSchema
        ? [{ key, label, schema: fieldSchema, multiline: true }]
        : [];
    }),
    ...(temperature
      ? [{ key: "temperature", label: "Temperatura", schema: temperature }]
      : []),
  ];
}
export function voiceInitialValues(
  kind: VoiceEditorKind,
  record?: Record<string, unknown>,
): Record<string, string> {
  if (!record) return {};
  if (kind === "agent")
    return Object.fromEntries(
      agentLabels.map(([key]) => [key, primitive(record[key])]),
    );
  const config = isRecord(record.model_config)
    ? record.model_config
    : undefined;
  const primary = isRecord(config?.primary) ? config.primary : undefined;
  return {
    model: primitive(config ? primary?.model : record.model),
    temperature: primitive(
      config ? config.temperature : record.model_temperature,
    ),
    // Every snapshot is partial. Never treat cached text as a full editable draft.
    general_prompt: "",
    begin_message: "",
  };
}
export function voiceCatalogOptions(
  items: unknown,
  idKey: string,
  labelKey?: string,
): { value: string; label: string }[] {
  if (!Array.isArray(items)) return [];
  const seen = new Set<string>();
  return items.flatMap((item) => {
    if (!isRecord(item)) return [];
    const value = text(item[idKey]).trim();
    if (!value || seen.has(value)) return [];
    seen.add(value);
    return [{ value, label: (labelKey && text(item[labelKey])) || value }];
  });
}
function parseField(field: VoiceEditorField, raw: string): string | number {
  const { schema, label } = field;
  if (["number", "integer"].includes(String(schema.type))) {
    const value = Number(raw);
    if (
      !raw.trim() ||
      !Number.isFinite(value) ||
      (schema.type === "integer" && !Number.isInteger(value)) ||
      (schema.minimum !== undefined && value < schema.minimum) ||
      (schema.maximum !== undefined && value > schema.maximum)
    )
      throw new Error(`Revisa ${label.toLowerCase()}.`);
    return value;
  }
  if (
    (schema.enum && !schema.enum.includes(raw)) ||
    (schema.minLength !== undefined && raw.length < schema.minLength) ||
    (schema.maxLength !== undefined && raw.length > schema.maxLength)
  )
    throw new Error(`Revisa ${label.toLowerCase()}.`);
  return raw;
}
export type VoiceEditorSafety = {
  completeFields?: string[];
  blockedFields?: Record<string, string>;
};
export function voiceEditorArguments(
  kind: VoiceEditorKind,
  schema: RetellSchema,
  record: Record<string, unknown> | undefined,
  values: Record<string, string>,
  replacements: VoiceReplacements = {},
  advancedDrafts: VoiceSchemaDrafts = {},
  safety?: VoiceEditorSafety,
): { endpoint: string; arguments: Record<string, unknown> } {
  const fields = voiceEditorFields(kind, schema, record);
  const bodySchema = property(schema, "requestBody");
  if (!bodySchema || !fields.length)
    throw new Error(
      "El esquema aprobado no está disponible para este formulario.",
    );
  const body: Record<string, unknown> = voiceSchemaPatch(
    bodySchema,
    advancedDrafts,
    record,
    safety?.completeFields,
  );
  const fullModel = body.model_config !== undefined;
  const fullEngine = body.response_engine !== undefined;
  const legacyKeys = [
    "model",
    "backup_model",
    "model_high_priority",
    "model_temperature",
    "model_ultrafast",
    "s2s_model",
  ];
  if (
    (fullModel || record?.model_config) &&
    legacyKeys.some((key) => body[key] !== undefined)
  ) {
    throw new Error(
      "Retell omite los ajustes heredados cuando existe una configuración completa del modelo. Usa la configuración vigente.",
    );
  }
  const args: Record<string, unknown> = { requestBody: body };
  const initial = voiceInitialValues(kind, record);
  if (record) {
    const key = kind === "agent" ? "agent_id" : "llm_id";
    if (!text(record[key]).trim() || !property(schema, key))
      throw new Error(
        "Falta el identificador del recurso. Actualiza la lectura aprobada.",
      );
    args[key] = record[key];
    if (record.version !== undefined && record.version !== null) {
      if (!Number.isInteger(record.version) || Number(record.version) < 0)
        throw new Error("La versión del recurso no es válida.");
      if (property(schema, "version")) args.version = record.version;
    }
  }
  for (const field of fields) {
    if (record && safety && !Object.hasOwn(values, field.key)) continue;
    if (
      body[field.key] !== undefined ||
      (fullModel && ["model", "temperature"].includes(field.key))
    )
      continue;
    const raw = values[field.key] ?? "";
    const isFullText =
      field.key === "general_prompt" || field.key === "begin_message";
    if (
      record &&
      isFullText &&
      !replacements[field.key as keyof VoiceReplacements]
    )
      continue;
    if (
      record &&
      isFullText &&
      safety?.completeFields?.includes(field.key) &&
      raw === record[field.key]
    )
      continue;
    if (record && !isFullText && raw === (initial[field.key] ?? "")) continue;
    if (
      !raw.trim() &&
      !(
        record &&
        field.key === "begin_message" &&
        replacements.begin_message
      ) &&
      !(
        record &&
        isFullText &&
        safety?.completeFields?.includes(field.key) &&
        replacements[field.key as keyof VoiceReplacements]
      )
    ) {
      if (
        (!record &&
          ["agent_name", "voice_id", "model", "general_prompt"].includes(
            field.key,
          )) ||
        (record &&
          field.key === "general_prompt" &&
          replacements.general_prompt) ||
        (record &&
          ["agent_name", "voice_id"].includes(field.key) &&
          raw !== initial[field.key])
      )
        throw new Error(`Completa ${field.label.toLowerCase()}.`);
      continue;
    }
    const value = parseField(field, raw);
    if (
      record &&
      !isFullText &&
      (value === record[field.key] ||
        (typeof value === "number" &&
          initial[field.key] !== "" &&
          value === Number(initial[field.key])))
    )
      continue;
    if (
      kind === "instructions" &&
      ["model", "temperature"].includes(field.key)
    ) {
      if (
        (!record || record.model_config !== undefined) &&
        property(bodySchema, "model_config")
      ) {
        const config = (body.model_config ??= {}) as Record<string, unknown>;
        if (!record) config.type = "cascading";
        if (field.key === "model") {
          const previous =
            isRecord(record?.model_config) &&
            isRecord(record.model_config.primary)
              ? record.model_config.primary
              : undefined;
          const primary: Record<string, unknown> = { model: value };
          // primary is a replacement object; retain its known, schema-supported tier.
          const tierSchema = scalar(
            property(
              property(
                modelBranch(property(bodySchema, "model_config"), record),
                "primary",
              ),
              "tier",
            ),
          );
          if (
            typeof previous?.tier === "string" &&
            tierSchema?.enum?.includes(previous.tier)
          )
            primary.tier = previous.tier;
          config.primary = primary;
        } else config.temperature = value;
      } else
        body[field.key === "model" ? "model" : "model_temperature"] = value;
    } else body[field.key] = value;
  }
  if (kind === "agent") {
    if (
      (!record && !fields.some((field) => field.key === "agent_name")) ||
      !fields.some((field) => field.key === "voice_id")
    )
      throw new Error("El esquema no permite configurar el agente.");
    if (!fullEngine && (!record || replacements.response_engine)) {
      const engine = property(bodySchema, "response_engine");
      const variant =
        engine &&
        groups(engine).find((entry) =>
          scalar(property(entry, "type"))?.enum?.includes("retell-llm"),
        );
      if (!variant || !property(variant, "llm_id"))
        throw new Error(
          "El esquema no permite vincular instrucciones Retell LLM.",
        );
      const llmId = text(values.llm_id).trim();
      if (!llmId)
        throw new Error("Completa el ID de las instrucciones Retell LLM.");
      const old = isRecord(record?.response_engine)
        ? record.response_engine
        : undefined;
      if (!record || old?.type !== "retell-llm" || old.llm_id !== llmId)
        body.response_engine = { type: "retell-llm", llm_id: llmId };
    }
  }
  if (
    !record &&
    kind === "agent" &&
    (typeof body.agent_name !== "string" ||
      !body.agent_name.trim() ||
      typeof body.voice_id !== "string" ||
      !body.voice_id.trim())
  )
    throw new Error(
      "Completa el nombre del agente y selecciona una voz válida.",
    );
  if (record && safety) {
    for (const key of Object.keys(body)) {
      if (
        !voiceHydrateField(
          bodySchema,
          key,
          record,
          safety.completeFields,
          safety.blockedFields,
        ).editable
      ) {
        throw new Error(
          "Este ajuste no tiene una lectura completa y segura. Actualiza la configuración antes de editarlo.",
        );
      }
    }
  }
  if (!Object.keys(body).length)
    throw new Error("No hay cambios para revisar.");
  return {
    endpoint: `${record ? "update" : "create"}${kind === "agent" ? "Agent" : "RetellLLM"}`,
    arguments: args,
  };
}
