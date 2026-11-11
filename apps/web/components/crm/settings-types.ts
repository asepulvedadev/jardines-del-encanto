export type SettingsRequest = <T>(
  path: string,
  method?: string,
  payload?: unknown,
) => Promise<T>;
export type ItemKind = "skill" | "tool" | "plugin" | "script" | "connection";
export type ControlItem = {
  id: string;
  kind: ItemKind;
  name: string;
  description: string;
  definition: Record<string, unknown>;
  enabled: boolean;
  effective: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};
export type Capability = {
  key: string;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  mutating: boolean;
  enabled: boolean;
};
export type Connection = {
  key: string;
  name: string;
  enabled: boolean;
  available: boolean;
  effective: boolean;
  version: number;
  status: string;
};
export type Catalog = {
  items: ControlItem[];
  capabilities: Capability[];
  connections: Connection[];
};
export type Proposal = {
  id: string;
  action: string;
  arguments: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired";
  version: number;
};
export type ActionResult = {
  result?: Record<string, unknown>;
  proposals?: Proposal[];
};
export const settingsError = (cause: unknown) =>
  cause instanceof Error
    ? cause.message
    : "No se confirmó el cambio. Intenta de nuevo.";
export const itemLabels: Record<ItemKind, string> = {
  skill: "Skill",
  tool: "Tool",
  plugin: "Plugin",
  script: "Script",
  connection: "Conexión",
};
