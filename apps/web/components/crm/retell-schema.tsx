export type RetellSchema = {
  type?: string | string[];
  title?: string;
  properties?: Record<string, RetellSchema>;
  required?: string[];
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  default?: unknown;
};
export type RetellField = {
  path: string;
  name: string;
  required: boolean;
  type: string;
  schema: RetellSchema;
};
export const retellOutbound = (endpoint: string) =>
  ["createPhoneCall", "createSmsChat", "createBatchCall"].includes(endpoint);
export function retellFields(schema: RetellSchema): RetellField[] {
  const fields: RetellField[] = [];
  function add(parent: RetellSchema, prefix = "") {
    for (const [name, value] of Object.entries(parent.properties ?? {})) {
      if (name === "requestBody" && value.type === "object") {
        add(value, "requestBody.");
      } else if (
        ["string", "integer", "number", "boolean"].includes(String(value.type))
      ) {
        fields.push({
          path: prefix + name,
          name,
          required: !!parent.required?.includes(name),
          type: String(value.type),
          schema: value,
        });
      }
    }
  }
  add(schema);
  return fields;
}
export function retellInitialArguments(
  schema: RetellSchema,
  defaults: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    retellFields(schema).flatMap((field) => {
      const name = field.name === "override_agent_id" ? "agent_id" : field.name;
      const value = defaults[name] ?? field.schema.default;
      return value !== undefined && value !== ""
        ? [[field.path, String(value)]]
        : [];
    }),
  );
}
function plain(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function safe(value: unknown, depth = 0): void {
  if (depth > 30) throw new Error("El JSON excede la profundidad permitida.");
  if (Array.isArray(value)) for (const entry of value) safe(entry, depth + 1);
  else if (plain(value))
    for (const [key, entry] of Object.entries(value)) {
      if (["__proto__", "constructor", "prototype"].includes(key))
        throw new Error("El JSON contiene una propiedad no permitida.");
      safe(entry, depth + 1);
    }
}
export function retellArguments(
  schema: RetellSchema,
  values: Record<string, string>,
  advanced?: string,
): Record<string, unknown> {
  if (advanced !== undefined) {
    if (advanced.length > 32768) throw new Error("El JSON supera 32 KiB.");
    let parsed: unknown;
    try {
      parsed = JSON.parse(advanced);
    } catch {
      throw new Error("Revisa el formato JSON.");
    }
    if (!plain(parsed))
      throw new Error("Los argumentos deben ser un objeto JSON.");
    safe(parsed);
    return parsed;
  }
  const result: Record<string, unknown> = {};
  for (const field of retellFields(schema)) {
    const raw = values[field.path] ?? "";
    if (raw === "") {
      if (field.required) throw new Error(`Completa ${field.name}.`);
      continue;
    }
    let value: unknown = raw;
    if (field.type === "boolean") {
      if (!["true", "false"].includes(raw))
        throw new Error(`Revisa ${field.name}.`);
      value = raw === "true";
    } else if (["number", "integer"].includes(field.type)) {
      value = Number(raw);
      if (
        !Number.isFinite(value) ||
        (field.type === "integer" && !Number.isInteger(value)) ||
        (field.schema.minimum !== undefined &&
          Number(value) < field.schema.minimum) ||
        (field.schema.maximum !== undefined &&
          Number(value) > field.schema.maximum)
      )
        throw new Error(`Revisa ${field.name}.`);
    } else if (
      (field.schema.minLength !== undefined &&
        raw.length < field.schema.minLength) ||
      (field.schema.maxLength !== undefined &&
        raw.length > field.schema.maxLength)
    )
      throw new Error(`Revisa ${field.name}.`);
    if (field.schema.enum && !field.schema.enum.includes(value))
      throw new Error(`Selecciona un valor válido para ${field.name}.`);
    if (field.path.startsWith("requestBody.")) {
      const body = (result.requestBody ??= {}) as Record<string, unknown>;
      body[field.name] = value;
    } else result[field.name] = value;
  }
  if (schema.required?.includes("requestBody") && !result.requestBody)
    result.requestBody = {};
  safe(result);
  return result;
}
