export type NodeKind =
  | "whatsapp_template"
  | "social_message"
  | "retell_call"
  | "wait"
  | "condition"
  | "crm_note"
  | "crm_task"
  | "end";
export type WorkflowNode = {
  id: string;
  kind: NodeKind;
  label: string;
  position: { x: number; y: number };
  next_id?: string | null;
  on_true?: string | null;
  on_false?: string | null;
  settings: Record<string, string | number | boolean | string[]>;
};
export type WorkflowDocument = {
  entry_id: string;
  nodes: WorkflowNode[];
  schedule: {
    timezone: "America/Bogota";
    days: number[];
    start_time: string;
    end_time: string;
    daily_limit: number;
  };
  stop_on_reply: boolean;
};
export type Workflow = {
  id: string;
  name: string;
  description: string;
  document: WorkflowDocument;
  version: number;
  created_at: string;
  updated_at: string;
};
export type RunStatus =
  | "prepared"
  | "active"
  | "paused"
  | "completed"
  | "stopped"
  | "blocked"
  | "unknown";
export type WorkflowRun = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  workflow_version: number;
  status: RunStatus;
  version: number;
  created_at: string;
  started_at?: string;
  expires_at?: string;
  counts: {
    total: number;
    completed: number;
    active: number;
    blocked: number;
    unknown: number;
    stopped: number;
  };
};
export type RunReview = {
  run: WorkflowRun;
  fingerprint: string;
  expires_at: string;
  recipients: {
    contact_id: string;
    name: string;
    phone: string;
    source: string;
    channel_recipient?: string | Record<string, unknown>;
  }[];
  steps: {
    node_id: string;
    label: string;
    kind: NodeKind;
    description: string;
  }[];
  warnings: string[];
};
export type RunDetail = {
  run: WorkflowRun;
  recipients: {
    contact_id: string;
    name: string;
    phone: string;
    status: string;
    current_node_id?: string;
    current_node_label?: string;
    due_at?: string;
    error?: string;
  }[];
  events: {
    id: string;
    contact_id?: string;
    node_id?: string;
    kind: string;
    message: string;
    created_at: string;
  }[];
};
export type WorkflowCatalog = {
  worker: { enabled: boolean; available: boolean };
  nodes: {
    kind: NodeKind;
    label: string;
    available: boolean;
    reason?: string;
  }[];
  connections: {
    key: string;
    name: string;
    available: boolean;
    reason?: string;
  }[];
};
export type ConversationOption = {
  id: string;
  account_id: string;
  platform: string;
  participant_id: string;
  participant_name?: string;
  label: string;
  phone?: string;
  can_reply: boolean;
  reason?: string;
};
export type ZernioOptions = {
  available: boolean;
  reason?: string;
  accounts: {
    id: string;
    name: string;
    platform: string;
    available: boolean;
    reason?: string;
  }[];
  templates: {
    name: string;
    language: string;
    status: string;
    parameter_count?: number;
    body?: string;
  }[];
  conversations: ConversationOption[];
};
export type RetellOptions = {
  available: boolean;
  reason?: string;
  agents: { id: string; name: string }[];
  numbers: { number: string; label: string }[];
  destination_policy?: { colombia_available: boolean; reason: string };
};
export type ConversationBinding = {
  account_id: string;
  conversation_id: string;
};
export const nodeLabels: Record<NodeKind, string> = {
  whatsapp_template: "Plantilla de WhatsApp",
  social_message: "Mensaje social",
  retell_call: "Llamada de Retell",
  wait: "Esperar",
  condition: "Condición del CRM",
  crm_note: "Registrar nota",
  crm_task: "Crear seguimiento",
  end: "Fin de la secuencia",
};
export const runLabels: Record<RunStatus, string> = {
  prepared: "Pendiente de aprobación",
  active: "En curso",
  paused: "En pausa",
  completed: "Finalizada",
  stopped: "Detenida",
  blocked: "Requiere atención",
  unknown: "Resultado incierto",
};
export const dayLabels = [
  "Lunes",
  "Martes",
  "Miércoles",
  "Jueves",
  "Viernes",
  "Sábado",
  "Domingo",
];
export function initialDocument(): WorkflowDocument {
  return {
    entry_id: "end",
    nodes: [
      {
        id: "end",
        kind: "end",
        label: nodeLabels.end,
        position: { x: 330, y: 150 },
        settings: {},
      },
    ],
    schedule: {
      timezone: "America/Bogota",
      days: [1, 2, 3, 4, 5],
      start_time: "09:00",
      end_time: "18:00",
      daily_limit: 20,
    },
    stop_on_reply: true,
  };
}
function defaults(kind: NodeKind): WorkflowNode["settings"] {
  switch (kind) {
    case "wait":
      return { hours: 24 };
    case "condition":
      return { field: "stage", operator: "equals", value: "contacted" };
    case "crm_note":
      return { body: "" };
    case "crm_task":
      return { title: "", due_days: 1 };
    case "retell_call":
      return { agent_id: "", from_number: "" };
    case "social_message":
      return { account_id: "", platform: "", text: "" };
    case "whatsapp_template":
      return {
        account_id: "",
        template_name: "",
        language: "",
        parameters: [],
      };
    default:
      return {};
  }
}
export function insertNode(
  document: WorkflowDocument,
  kind: NodeKind,
  id: string,
): WorkflowDocument {
  if (document.nodes.length >= 20)
    throw new Error("La secuencia admite hasta 20 pasos.");
  const copy = structuredClone(document);
  const end = copy.nodes.find((n) => n.kind === "end");
  if (!end) throw new Error("Agrega un final antes de conectar nuevos pasos.");
  const node: WorkflowNode = {
    id,
    kind,
    label: nodeLabels[kind],
    position: { x: 330, y: 150 },
    settings: defaults(kind),
    ...(kind === "condition"
      ? { on_true: end.id, on_false: end.id }
      : kind === "end"
        ? {}
        : { next_id: end.id }),
  };
  for (const old of copy.nodes)
    for (const key of ["next_id", "on_true", "on_false"] as const)
      if (old[key] === end.id) old[key] = id;
  if (copy.entry_id === end.id) copy.entry_id = id;
  copy.nodes.splice(copy.nodes.indexOf(end), 0, node);
  return layoutDocument(copy);
}
export function layoutDocument(document: WorkflowDocument): WorkflowDocument {
  return {
    ...document,
    nodes: document.nodes.map((node, index) => ({
      ...node,
      position: { x: 330, y: 90 + index * 150 },
    })),
  };
}
export function removeNode(
  document: WorkflowDocument,
  id: string,
): WorkflowDocument {
  const node = document.nodes.find((n) => n.id === id);
  if (!node || node.kind === "end") return document;
  const replacement = node.next_id ?? node.on_true ?? null;
  const nodes = document.nodes
    .filter((n) => n.id !== id)
    .map((n) => {
      const next = { ...n };
      for (const key of ["next_id", "on_true", "on_false"] as const)
        if (next[key] === id) next[key] = replacement;
      return next;
    });
  return layoutDocument({
    ...document,
    entry_id:
      document.entry_id === id ? (replacement ?? "") : document.entry_id,
    nodes,
  });
}
export function outgoing(node: WorkflowNode): string[] {
  return (
    node.kind === "condition" ? [node.on_true, node.on_false] : [node.next_id]
  ).filter((id): id is string => Boolean(id));
}
export function connectionOptions(
  document: WorkflowDocument,
  from: string,
): WorkflowNode[] {
  const reaches = (id: string, seen = new Set<string>()): boolean => {
    if (id === from) return true;
    if (seen.has(id)) return false;
    seen.add(id);
    return outgoing(
      document.nodes.find((n) => n.id === id) ??
        ({ kind: "end" } as WorkflowNode),
    ).some((next) => reaches(next, seen));
  };
  return document.nodes.filter((n) => !reaches(n.id));
}
export function graphIssues(document: WorkflowDocument): string[] {
  const errors: string[] = [];
  const nodes = new Map(document.nodes.map((n) => [n.id, n]));
  if (!nodes.has(document.entry_id))
    errors.push("Selecciona un paso de inicio válido.");
  if (document.nodes.length > 20 || !document.nodes.length)
    errors.push("Usa entre 1 y 20 pasos.");
  const visited = new Set<string>(),
    stack = new Set<string>();
  const visit = (id: string) => {
    if (stack.has(id)) {
      if (!errors.some((e) => e.includes("ciclo")))
        errors.push("Las conexiones forman un ciclo.");
      return;
    }
    if (visited.has(id)) return;
    const node = nodes.get(id);
    if (!node) {
      errors.push("Hay una conexión sin destino.");
      return;
    }
    visited.add(id);
    stack.add(id);
    if (node.kind === "condition" && (!node.on_true || !node.on_false))
      errors.push(`Conecta ambas salidas de «${node.label}».`);
    if (node.kind !== "end" && node.kind !== "condition" && !node.next_id)
      errors.push(`Conecta el siguiente paso de «${node.label}».`);
    outgoing(node).forEach(visit);
    stack.delete(id);
  };
  if (nodes.has(document.entry_id)) visit(document.entry_id);
  if (visited.size !== nodes.size)
    errors.push("Todos los pasos deben estar conectados al inicio.");
  if (!document.schedule.days.length)
    errors.push("Selecciona al menos un día de ejecución.");
  if (document.schedule.start_time >= document.schedule.end_time)
    errors.push("La hora final debe ser posterior al inicio.");
  if (
    !Number.isInteger(document.schedule.daily_limit) ||
    document.schedule.daily_limit < 1 ||
    document.schedule.daily_limit > 100
  )
    errors.push("El límite diario debe ser un entero entre 1 y 100.");
  return errors;
}
export function prepareArguments(
  version: number,
  ids: string[],
  bindings: Record<string, ConversationBinding>,
  consent: boolean,
) {
  if (
    !consent ||
    ids.length < 1 ||
    ids.length > 50 ||
    new Set(ids).size !== ids.length
  )
    throw new Error(
      "Confirma el consentimiento y selecciona entre 1 y 50 clientes.",
    );
  return {
    version,
    contact_ids: ids,
    bindings: ids
      .filter((id) => bindings[id]?.account_id && bindings[id]?.conversation_id)
      .map((contact_id) => ({ contact_id, ...bindings[contact_id] })),
    consent_confirmed: true,
  };
}
export function channelBindingKey(contactId: string, accountId: string) {
  return JSON.stringify([contactId, accountId]);
}
export function multichannelPrepareArguments(
  version: number,
  ids: string[],
  bindings: Record<string, ConversationBinding>,
  consent: boolean,
  accountIds: string[],
) {
  const base = prepareArguments(version, ids, {}, consent);
  const accounts = [...new Set(accountIds)];
  const channel_bindings = ids.flatMap((contact_id) =>
    accounts.map((account_id) => {
      const binding = bindings[channelBindingKey(contact_id, account_id)];
      if (!binding?.conversation_id || binding.account_id !== account_id)
        throw new Error("Vincula una conversación real por cliente y cuenta.");
      return {
        contact_id,
        account_id,
        conversation_id: binding.conversation_id,
      };
    }),
  );
  return channel_bindings.length ? { ...base, channel_bindings } : base;
}
export function canActivate(
  review: RunReview | null,
  worker: WorkflowCatalog["worker"] | undefined,
  dirty: boolean,
  consent: boolean,
  now = Date.now(),
): boolean {
  return Boolean(
    review &&
    review.run.status === "prepared" &&
    worker?.enabled &&
    worker.available &&
    !dirty &&
    consent &&
    Date.parse(review.expires_at) > now,
  );
}
export function workflowError(code: unknown): string {
  const key = typeof code === "string" ? code : "";
  const errors: Record<string, string> = {
    zernio_provider_takeover_consent_required:
      "Facebook e Instagram requieren autorizar explícitamente el control de la conversación en el paso. No se ha enviado nada.",
    zernio_window_unconfirmed:
      "No se pudo verificar un mensaje entrante del destinatario en las últimas 24 horas. No se envió el mensaje; en WhatsApp puedes usar una plantilla aprobada.",
    zernio_thread_control_unconfirmed:
      "La conversación pertenece a otra aplicación o está en espera. Revisa el control en Inbox antes de preparar la secuencia.",
    retell_route_confirmation_required:
      "Las llamadas a Colombia (+57) requieren una ruta telefónica verificada. La secuencia no hará esa llamada hasta configurarla.",
    record_changed:
      "La versión cambió en otra sesión. Tu borrador se conserva; recarga la versión guardada antes de volver a editar.",
    workflow_version_conflict:
      "La versión cambió en otra sesión. Tu borrador se conserva; recarga la versión guardada antes de volver a editar.",
    worker_unavailable:
      "El ejecutor automático no está disponible. Puedes guardar borradores, pero no activar envíos.",
    workflow_worker_unavailable:
      "El ejecutor automático no está disponible. Puedes guardar borradores, pero no activar envíos.",
    workflow_provider_review_limit:
      "La revisión admite hasta 10 acciones externas (clientes por pasos de mensaje o llamada). Reduce la audiencia o el recorrido.",
    workflow_review_budget_exceeded:
      "La validación de proveedor superó 60 segundos. No se envió ninguna acción. Puedes preparar una nueva revisión.",
    workflow_review_expired:
      "La revisión venció. Prepara una nueva antes de activar.",
    invalid_csrf:
      "Tu sesión cambió. Recarga la página; no se confirmó la operación.",
    authentication_required: "Tu sesión finalizó. Vuelve a ingresar.",
    administrator_required:
      "Solo un administrador puede modificar o activar secuencias.",
    workflow_provider_unavailable:
      "La conexión no permite esta acción. Revisa las conexiones y prepara una nueva revisión.",
  };
  return (
    errors[key] ??
    "No pudimos confirmar la operación. El borrador se conserva. Actualiza el historial antes de repetir una activación."
  );
}
