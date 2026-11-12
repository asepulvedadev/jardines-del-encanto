export type VoiceRecord = Record<string, unknown>;
export type VoiceSnapshot = {
  endpoint: string;
  provider_revision: number;
  created_at?: string;
  data: unknown;
};
export type VoiceSection = {
  key: string;
  label: string;
  list: string;
  get: string;
  id: string;
  name: string;
  create?: string;
  actions: [string, string][];
};
export const sections: VoiceSection[] = [
  {
    key: "agents",
    label: "Agentes",
    list: "listAgents",
    get: "getAgent",
    id: "agent_id",
    name: "agent_name",
    create: "createAgent",
    actions: [
      ["getAgent", "Consultar"],
      ["listAgentVersions", "Versiones"],
      ["publishAgentVersion", "Publicar"],
      ["createWebCall", "Probar en navegador"],
      ["deleteAgent", "Eliminar"],
    ],
  },
  {
    key: "voices",
    label: "Voces",
    list: "listVoices",
    get: "getVoice",
    id: "voice_id",
    name: "voice_name",
    create: "addCommunityVoice",
    actions: [["getVoice", "Consultar"]],
  },
  {
    key: "calls",
    label: "Llamadas",
    list: "listCalls",
    get: "getCall",
    id: "call_id",
    name: "call_status",
    create: "createPhoneCall",
    actions: [
      ["getCall", "Detalle y análisis"],
      ["updateCall", "Editar"],
      ["deleteCall", "Eliminar"],
    ],
  },
  {
    key: "numbers",
    label: "Números",
    list: "listPhoneNumbers",
    get: "getPhoneNumber",
    id: "phone_number",
    name: "nickname",
    create: "createPhoneNumber",
    actions: [
      ["getPhoneNumber", "Consultar"],
      ["updatePhoneNumber", "Editar"],
      ["deletePhoneNumber", "Eliminar"],
    ],
  },
  {
    key: "knowledge",
    label: "Conocimiento",
    list: "listKnowledgeBases",
    get: "getKnowledgeBase",
    id: "knowledge_base_id",
    name: "knowledge_base_name",
    create: "createKnowledgeBase",
    actions: [
      ["getKnowledgeBase", "Consultar"],
      ["deleteKnowledgeBase", "Eliminar"],
    ],
  },
  {
    key: "testing",
    label: "Pruebas",
    list: "listTestCaseDefinitions",
    get: "getTestCaseDefinition",
    id: "test_case_definition_id",
    name: "name",
    create: "createTestCaseDefinition",
    actions: [
      ["getTestCaseDefinition", "Consultar"],
      ["updateTestCaseDefinition", "Editar"],
      ["deleteTestCaseDefinition", "Eliminar"],
    ],
  },
  {
    key: "models",
    label: "Instrucciones y modelos",
    list: "listRetellLLM",
    get: "getRetellLLM",
    id: "llm_id",
    name: "model",
    create: "createRetellLLM",
    actions: [
      ["getRetellLLM", "Consultar"],
      ["deleteRetellLLM", "Eliminar"],
    ],
  },
  {
    key: "flows",
    label: "Flujos",
    list: "listConversationFlows",
    get: "getConversationFlow",
    id: "conversation_flow_id",
    name: "name",
    create: "createConversationFlow",
    actions: [
      ["getConversationFlow", "Consultar"],
      ["updateConversationFlow", "Editar"],
      ["deleteConversationFlow", "Eliminar"],
    ],
  },
  {
    key: "chat",
    label: "Chat y SMS",
    list: "listChats",
    get: "getChat",
    id: "chat_id",
    name: "chat_status",
    create: "createChatAgent",
    actions: [
      ["getChat", "Consultar"],
      ["createChatCompletion", "Enviar mensaje"],
      ["endChat", "Finalizar"],
    ],
  },
  {
    key: "contacts",
    label: "Contactos de Retell",
    list: "listContacts",
    get: "getContact",
    id: "contact_id",
    name: "first_name",
    create: "createContact",
    actions: [
      ["getContact", "Consultar"],
      ["updateContact", "Editar"],
      ["deleteContact", "Eliminar"],
    ],
  },
  {
    key: "apps",
    label: "Aplicaciones",
    list: "listApps",
    get: "getApp",
    id: "app_id",
    name: "name",
    create: "createApp",
    actions: [
      ["getApp", "Consultar"],
      ["updateApp", "Editar"],
      ["deleteApp", "Eliminar"],
    ],
  },
];
export function object(value: unknown): value is VoiceRecord {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
export function text(value: unknown): string {
  return typeof value === "string"
    ? value
    : typeof value === "number" && Number.isFinite(value)
      ? String(value)
      : "";
}
function records(value: unknown): VoiceRecord[] {
  if (Array.isArray(value)) return value.filter(object);
  if (!object(value)) return [];
  for (const key of [
    "agents",
    "voices",
    "calls",
    "phone_numbers",
    "knowledge_bases",
    "retell_llms",
    "conversation_flows",
    "chats",
    "contacts",
    "apps",
    "test_case_definitions",
    "items",
    "data",
  ]) {
    if (Array.isArray(value[key]))
      return (value[key] as unknown[]).filter(object);
  }
  return [value];
}
export function resourceRows(
  snapshots: VoiceSnapshot[],
  section: VoiceSection,
  revision: number,
): VoiceRecord[] {
  const rows = new Map<string, VoiceRecord>();
  const ordered = snapshots
    .filter(
      (s) =>
        s.provider_revision === revision &&
        [section.list, section.get].includes(s.endpoint),
    )
    .map((snapshot, index) => ({ snapshot, index }))
    .sort((a, b) => {
      const left = Date.parse(a.snapshot.created_at ?? ""),
        right = Date.parse(b.snapshot.created_at ?? "");
      return Number.isFinite(left) && Number.isFinite(right)
        ? left - right || a.index - b.index
        : a.index - b.index;
    });
  for (const { snapshot } of ordered) {
    if (snapshot.endpoint === section.list) rows.clear();
    for (const row of records(snapshot.data)) {
      const id = text(row[section.id]);
      if (id && id.length <= 256) rows.set(id, { ...rows.get(id), ...row });
    }
  }
  return [...rows.values()];
}
export function resourceSeed(
  endpoint: string,
  row: VoiceRecord,
  section: VoiceSection,
): VoiceRecord {
  if (endpoint === "createWebCall")
    return { requestBody: { agent_id: text(row.agent_id) } };
  const seed: VoiceRecord = { [section.id]: text(row[section.id]) };
  if (/^(update|publish|createChatCompletion)/.test(endpoint))
    seed.requestBody = {};
  return seed;
}
export function mergeConfirmed(
  snapshots: VoiceSnapshot[],
  result: VoiceRecord,
  revision: number,
): VoiceSnapshot[] {
  if (
    result.provider !== "retell" ||
    result.status !== "completed" ||
    typeof result.endpoint !== "string"
  )
    return snapshots;
  const section = sections.find(
    (s) =>
      s.create === result.endpoint ||
      s.get === result.endpoint ||
      s.list === result.endpoint ||
      `update${s.get.slice(3)}` === result.endpoint,
  );
  if (!section) return snapshots;
  const endpoint =
    section.list === result.endpoint ? section.list : section.get;
  // Keep multiple confirmed detail results by resource identity; no mutation is inferred from a proposal.
  return [
    ...snapshots,
    {
      endpoint,
      provider_revision: revision,
      created_at: new Date().toISOString(),
      data: result.data,
    },
  ].slice(-96);
}
