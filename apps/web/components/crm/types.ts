export const sources = [
  ["in_person", "Presencial"],
  ["social_campaign", "Campaña de redes"],
  ["web", "Página web"],
  ["referral", "Referido"],
  ["whatsapp", "WhatsApp"],
  ["other", "Otro"],
] as const;
export const stages = [
  ["new", "Nuevo"],
  ["contacted", "Contactado"],
  ["won", "Ganado"],
] as const;
export type Stage = (typeof stages)[number][0];
export type Source = (typeof sources)[number][0];
export type Contact = {
  id: string;
  name: string;
  phone: string;
  source: Source;
  version: number;
  created_at: string;
  registration_code?: string | null;
};
export type Deal = {
  id: string;
  contact_id: string;
  stage: Stage;
  version: number;
  created_at: string;
  updated_at: string;
};
export type Task = {
  id: string;
  contact_id: string;
  title: string;
  due_date: string;
  completed: boolean;
  version: number;
};
export type Activity = {
  id: string;
  deal_id: string;
  kind: string;
  body: string;
  created_at: string;
};
export type WorkspaceData = {
  contacts: Contact[];
  deals: Deal[];
  tasks: Task[];
  activities: Activity[];
  counts: {
    contacts: number;
    active: number;
    won: number;
    pending: number;
    overdue: number;
  };
  limited: boolean;
};
export type View = "overview" | "pipeline" | "contacts" | "tasks";
export const labels: Record<View, string> = {
  overview: "Inicio",
  pipeline: "Pipeline",
  contacts: "Clientes",
  tasks: "Seguimientos",
};
export const sourceLabel = (source: Source) =>
  sources.find(([key]) => key === source)?.[1] ?? source;
export const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Bogota",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const shortDate = (date: string) =>
  new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short" }).format(
    new Date(`${date}T12:00:00-05:00`),
  );
export const phoneLabel = (phone: string) =>
  phone.startsWith("+57") && phone.length === 13
    ? `+57 ${phone.slice(3, 6)} ${phone.slice(6, 9)} ${phone.slice(9)}`
    : phone;
export const initials = (name: string) =>
  name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
export const errorMessage = (code: string) =>
  ({
    invalid_credentials: "El usuario o la contraseña no son correctos.",
    login_throttled:
      "Demasiados intentos. Espera 15 minutos antes de volver a intentar.",
    login_busy:
      "Estamos procesando otros accesos. Intenta de nuevo en unos segundos.",
    phone_already_exists: "Ya existe un cliente con este celular.",
    record_changed:
      "Este registro cambió en otra sesión. Copia tus cambios y recarga la página antes de volver a guardar.",
    invalid_input:
      "Revisa los datos. El nombre, celular y medio deben ser válidos.",
    invalid_csrf:
      "Tu sesión cambió. Recarga la página antes de volver a guardar.",
    invalid_origin: "No se pudo validar el origen de la solicitud.",
    authentication_required: "Tu sesión finalizó. Vuelve a ingresar.",
  })[code] ??
  "No pudimos completar la solicitud. Intenta de nuevo; tus cambios no se han confirmado.";
