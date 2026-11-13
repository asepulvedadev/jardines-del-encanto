import type { RetellSchema } from "./retell-schema";
import { voiceEditorArguments } from "./voice-agent-model";
import {
  voiceSchemaPatch,
  voiceSchemaProperties,
  type VoiceSchemaDrafts,
} from "./voice-schema-model";

export type StudioSnapshot = {
  data: Record<string, unknown>;
  completeFields: string[];
  blockedFields: Record<string, string>;
};
export type StudioChange = {
  endpoint: string;
  arguments: Record<string, unknown>;
};
export const studioGroups: {
  key: string;
  label: string;
  icon:
    | "settings"
    | "connections"
    | "task"
    | "microphone"
    | "phone"
    | "history"
    | "list"
    | "people";
  agent: string[];
  instructions: string[];
}[] = [
  {
    key: "primary",
    label: "Modelo y configuración avanzada",
    icon: "settings",
    agent: [
      "agent_name",
      "response_engine",
      "version_description",
      "version_title",
      "voice_id",
      "language",
    ],
    instructions: [
      "general_prompt",
      "voice_prompt",
      "model",
      "model_config",
      "backup_model",
      "model_high_priority",
      "model_temperature",
      "model_ultrafast",
      "s2s_model",
      "begin_message",
      "start_speaker",
      "begin_after_user_silence_ms",
    ],
  },
  {
    key: "functions",
    label: "Funciones",
    icon: "connections",
    agent: ["pre_session_tools", "post_session_tools"],
    instructions: [
      "general_tools",
      "starting_state",
      "states",
      "is_transfer_llm",
    ],
  },
  {
    key: "knowledge",
    label: "Conocimiento y memoria",
    icon: "task",
    agent: ["handbook_config"],
    instructions: ["kb_config", "knowledge_base_ids"],
  },
  {
    key: "speech",
    label: "Ajustes de voz",
    icon: "microphone",
    agent: [
      "ambient_sound",
      "ambient_sound_volume",
      "backchannel_frequency",
      "backchannel_words",
      "enable_backchannel",
      "enable_dynamic_responsiveness",
      "enable_dynamic_voice_speed",
      "enable_expressive_mode",
      "expressive_emotion_tags",
      "expressive_mode_prompt",
      "interruption_sensitivity",
      "pronunciation_dictionary",
      "responsiveness",
      "voice_model",
      "voice_speed",
      "voice_temperature",
      "volume",
    ],
    instructions: [],
  },
  {
    key: "transcription",
    label: "Transcripción en tiempo real",
    icon: "list",
    agent: [
      "boosted_keywords",
      "custom_stt_config",
      "denoising_enhancement_level",
      "denoising_mode",
      "stt_mode",
      "vocab_specialization",
    ],
    instructions: [],
  },
  {
    key: "call",
    label: "Ajustes de llamada",
    icon: "phone",
    agent: [
      "allow_dtmf_interruption",
      "allow_user_dtmf",
      "begin_message_delay_ms",
      "call_screening_option",
      "end_call_after_silence_ms",
      "ivr_option",
      "max_call_duration_ms",
      "reminder_max_count",
      "reminder_trigger_ms",
      "ring_duration_ms",
      "timezone",
      "user_dtmf_options",
      "voicemail_option",
    ],
    instructions: [],
  },
  {
    key: "security",
    label: "Seguridad y respaldo",
    icon: "settings",
    agent: [
      "data_storage_retention_days",
      "data_storage_setting",
      "enable_dnc_detection",
      "fallback_voice_ids",
      "guardrail_config",
      "opt_in_signed_url",
      "pii_config",
      "signed_url_expiration_ms",
    ],
    instructions: ["default_dynamic_variables"],
  },
  {
    key: "extraction",
    label: "Extracción posterior a la llamada",
    icon: "task",
    agent: ["post_call_analysis_data", "post_call_analysis_model"],
    instructions: [],
  },
  {
    key: "memory",
    label: "Memoria posterior a la llamada",
    icon: "history",
    agent: ["contact_memory_config"],
    instructions: [],
  },
  {
    key: "webhooks",
    label: "Webhooks",
    icon: "connections",
    agent: ["webhook_events", "webhook_timeout_ms", "webhook_url"],
    instructions: [],
  },
  {
    key: "mcps",
    label: "Servidores MCP",
    icon: "connections",
    agent: [],
    instructions: ["mcps"],
  },
];

export function studioChanges(
  schemas: Record<string, RetellSchema>,
  agent: StudioSnapshot,
  instructions: StudioSnapshot | undefined,
  agentDrafts: VoiceSchemaDrafts,
  instructionDrafts: VoiceSchemaDrafts,
): StudioChange[] {
  const changes: StudioChange[] = [];
  for (const [kind, snapshot, drafts] of [
    ["agent", agent, agentDrafts],
    ["instructions", instructions, instructionDrafts],
  ] as const) {
    if (!snapshot) {
      if (Object.values(drafts).some((d) => d.enabled))
        throw new Error("Las instrucciones completas no están disponibles.");
      continue;
    }
    const schema =
      schemas[kind === "agent" ? "updateAgent" : "updateRetellLLM"];
    if (!schema) throw new Error("El esquema aprobado no está disponible.");
    const body = voiceSchemaProperties(schema).requestBody;
    const patch = voiceSchemaPatch(
      body,
      drafts,
      snapshot.data,
      snapshot.completeFields,
    );
    if (!Object.keys(patch).length) continue;
    changes.push(
      voiceEditorArguments(kind, schema, snapshot.data, {}, {}, drafts, {
        completeFields: snapshot.completeFields,
        blockedFields: snapshot.blockedFields,
      }),
    );
  }
  if (
    changes.some(
      (change) =>
        change.endpoint === "updateAgent" &&
        Object.hasOwn(
          change.arguments.requestBody as object,
          "response_engine",
        ),
    ) &&
    changes.some((change) => change.endpoint === "updateRetellLLM")
  )
    throw new Error(
      "Revisa primero el cambio de motor y vuelve a cargar el agente antes de editar sus instrucciones vinculadas.",
    );
  return changes;
}
export function studioTestArguments(
  mode: "audio" | "llm",
  agent: Record<string, unknown>,
  message = "",
): Record<string, unknown> {
  if (typeof agent.agent_id !== "string" || !agent.agent_id)
    throw new Error("No hay un agente guardado para probar.");
  const version = agent.version;
  if (
    version != null &&
    (!Number.isSafeInteger(version) || Number(version) < 0)
  )
    throw new Error("La versión del agente no es válida.");
  if (mode === "audio")
    return {
      requestBody: {
        agent_id: agent.agent_id,
        ...(version != null ? { agent_version: version } : {}),
      },
    };
  if (!message.trim())
    throw new Error("Escribe un mensaje para probar el modelo.");
  return {
    agent_id: agent.agent_id,
    ...(version != null ? { version } : {}),
    requestBody: { messages: [{ role: "user", content: message }] },
  };
}
