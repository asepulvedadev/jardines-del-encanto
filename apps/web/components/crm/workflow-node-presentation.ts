import type { WorkflowNode } from "./workflow-types";

export const kindIcons = {
  whatsapp_template: "message",
  social_message: "send",
  retell_call: "phone",
  wait: "history",
  condition: "connections",
  crm_note: "edit",
  crm_task: "task",
  end: "check",
} as const;

export const nodeSummary = (node: WorkflowNode) => {
  const s = node.settings;
  switch (node.kind) {
    case "wait":
      return `${s.hours} horas de espera`;
    case "condition":
      return `${s.field === "stage" ? "Etapa" : "Medio"} = ${s.value}`;
    case "crm_note":
      return String(s.body || "Escribe la nota para el CRM");
    case "crm_task":
      return String(s.title || "Define el próximo seguimiento");
    case "social_message":
      return String(s.text || "Selecciona cuenta y mensaje");
    case "whatsapp_template":
      return String(s.template_name || "Selecciona una plantilla aprobada");
    case "retell_call":
      return s.agent_id
        ? `Agente ${s.agent_id}`
        : "Selecciona agente y número de salida";
    default:
      return "Sin más acciones para este cliente";
  }
};
