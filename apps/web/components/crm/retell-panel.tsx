"use client";
import { useEffect, useRef, useState } from "react";
import { ActionOutput } from "./hermes-panel";
import {
  settingsError,
  type ActionResult,
  type SettingsRequest,
} from "./settings-types";
import {
  retellArguments,
  retellFields,
  retellInitialArguments,
  retellGuidedArguments,
  retellOutbound,
  type RetellSchema,
} from "./retell-schema";
type Defaults = {
  agent_id: string;
  chat_agent_id: string;
  from_number: string;
};
type State = {
  available: boolean;
  configured: boolean;
  verified: boolean;
  enabled: boolean;
  revision: number;
  key_suffix?: string;
  defaults: Defaults;
};
type Operation = {
  endpoint: string;
  method: string;
  path: string;
  summary: string;
  group: string;
  risk: "read" | "write" | "paid" | "destructive" | "security";
  available: boolean;
  blocked_reason?: string;
};
type Catalog = {
  revision: number;
  registry_revision: string;
  operations: Operation[];
  new_operations: Operation[];
};
type Schema = {
  revision: number;
  endpoint: string;
  input_schema: RetellSchema;
  schema_hash: string;
  metadata: Operation;
};
type Contact = { id: string; name: string; phone: string };
const empty: Defaults = { agent_id: "", chat_agent_id: "", from_number: "" };
const defaultsLabels = {
  agent_id: "Agente de voz",
  chat_agent_id: "Agente de chat",
  from_number: "Número de origen",
};
const risks = {
  read: "Consulta",
  write: "Modifica datos",
  paid: "Consume créditos",
  destructive: "Elimina datos",
  security: "Acceso sensible",
};
const groupLabels: Record<string, string> = {
  account: "Cuenta",
  agents: "Agentes",
  apps: "Aplicaciones",
  assets: "Archivos",
  calls: "Llamadas",
  chat: "Chat y SMS",
  contacts: "Contactos",
  crm: "CRM",
  flows: "Flujos",
  knowledge: "Conocimiento",
  llm: "Modelos de lenguaje",
  telephony: "Telefonía",
  testing: "Pruebas",
  voices: "Voces",
};
const blockedLabels: Record<string, string> = {
  requires_file_adapter:
    "Requiere un adaptador de archivos. No disponible en esta versión.",
  unreviewed_operation: "Nueva operación pendiente de revisión.",
};
export function RetellPanel({
  request,
  onChanged,
  active,
  connectionEnabled,
  operationsOnly = false,
  initialOperation,
  onResult,
}: {
  request: SettingsRequest;
  onChanged: () => Promise<void>;
  active: boolean;
  connectionEnabled?: boolean;
  operationsOnly?: boolean;
  initialOperation?: { endpoint: string; arguments: Record<string, unknown> };
  onResult?: (result: Record<string, unknown>) => void | Promise<void>;
}) {
  const [state, setState] = useState<State | null>(null),
    [defaults, setDefaults] = useState<Defaults>(empty);
  const [key, setKey] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [disconnect, setDisconnect] = useState(false);
  const [replaceKey, setReplaceKey] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null),
    [search, setSearch] = useState(""),
    [group, setGroup] = useState("");
  const [endpoint, setEndpoint] = useState(""),
    [schema, setSchema] = useState<Schema | null>(null),
    [values, setValues] = useState<Record<string, string>>({});
  const [advanced, setAdvanced] = useState(false),
    [json, setJson] = useState("{}"),
    [contacts, setContacts] = useState<Contact[]>([]),
    [contactId, setContactId] = useState("");
  const [output, setOutput] = useState<ActionResult | null>(null),
    [outputKey, setOutputKey] = useState(0);
  const mounted = useRef(false),
    lock = useRef(false),
    generation = useRef(0),
    selection = useRef(0);
  const seeded = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const run = ++generation.current;
    setKey("");
    setReplaceKey(false);
    setOutput(null);
    setDisconnect(false);
    if (active) {
      setLoading(true);
      request<State>("retell/settings")
        .then((value) => {
          if (mounted.current && run === generation.current) {
            setState(value);
            setDefaults({ ...empty, ...value.defaults });
            if (operationsOnly && value.available && value.configured) {
              void request<Catalog>("retell/catalog", "POST", {
                revision: value.revision,
              })
                .then((catalog) => {
                  if (mounted.current && run === generation.current)
                    setCatalog(catalog);
                })
                .catch((cause) => {
                  if (mounted.current && run === generation.current)
                    setError(settingsError(cause));
                });
            }
          }
        })
        .catch((cause) => {
          if (mounted.current && run === generation.current)
            setError(settingsError(cause));
        })
        .finally(() => {
          if (mounted.current && run === generation.current) setLoading(false);
        });
    }
    return () => {
      mounted.current = false;
      generation.current++;
      selection.current++;
    };
  }, [request, active, operationsOnly]);
  useEffect(() => {
    if (
      !active ||
      !initialOperation ||
      !catalog ||
      !state ||
      busy ||
      seeded.current
    )
      return;
    seeded.current = true;
    void choose(initialOperation.endpoint, initialOperation.arguments);
  }, [active, initialOperation, catalog, state, busy]);
  async function act(task: (current: () => boolean) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const run = generation.current;
    const current = () => mounted.current && run === generation.current;
    try {
      await task(current);
    } catch (cause) {
      if (current()) setError(settingsError(cause));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function resetOperation() {
    selection.current++;
    setSchema(null);
    setEndpoint("");
    setValues({});
    setJson("{}");
    setOutput(null);
    setContactId("");
  }
  async function refresh() {
    if (!state) return;
    await act(async (current) => {
      const value = await request<Catalog>("retell/catalog", "POST", {
        revision: state.revision,
      });
      if (current()) {
        setCatalog(value);
        resetOperation();
      }
    });
  }
  async function save() {
    if (!state) return;
    const secret = key.trim();
    if (secret && state.configured && !replaceKey) {
      setError("Confirma que quieres reemplazar la clave guardada.");
      return;
    }
    setKey("");
    setReplaceKey(false);
    await act(async (current) => {
      await request("retell/settings", "POST", {
        revision: state.revision,
        ...(secret ? { api_key: secret } : {}),
        defaults,
      });
      const saved = await request<State>("retell/settings");
      if (current()) {
        setState(saved);
        setDefaults({ ...empty, ...saved.defaults });
        setCatalog(null);
        resetOperation();
      }
      await onChanged();
      try {
        const value = await request<Catalog>("retell/catalog", "POST", {
          revision: saved.revision,
        });
        if (current()) setCatalog(value);
      } catch {
        throw new Error(
          "Conexión guardada. Actualiza el catálogo antes de preparar una propuesta.",
        );
      }
    });
  }
  async function choose(value: string, seed?: Record<string, unknown>) {
    if (lock.current) return;
    const run = ++selection.current;
    setEndpoint(value);
    setSchema(null);
    setOutput(null);
    setValues({});
    setAdvanced(false);
    setJson("{}");
    setContactId("");
    const operation = catalog?.operations.find(
      (item) => item.endpoint === value,
    );
    if (!operation?.available || !state) return;
    await act(async (current) => {
      const [definition, workspace] = await Promise.all([
        request<Schema>("retell/schema", "POST", {
          revision: state.revision,
          endpoint: value,
        }),
        retellOutbound(value) && value !== "createBatchCall"
          ? request<{ contacts: Contact[] }>("workspace")
          : Promise.resolve({ contacts: [] }),
      ]);
      if (current() && run === selection.current) {
        setSchema(definition);
        setValues(
          retellInitialArguments(definition.input_schema, {
            ...defaults,
            ...(["createChat", "createSmsChat"].includes(value)
              ? { agent_id: defaults.chat_agent_id }
              : {}),
          }),
        );
        if (seed) {
          setAdvanced(true);
          setJson(JSON.stringify(seed, null, 2));
          try {
            setValues(
              retellGuidedArguments(
                definition.input_schema,
                JSON.stringify(seed),
              ),
            );
          } catch {
            setValues({});
          }
        }
        setContacts(workspace.contacts);
      }
    });
  }
  const operation = catalog?.operations.find(
    (item) => item.endpoint === endpoint,
  );
  const connectionIsEnabled = connectionEnabled ?? state?.enabled ?? false;
  const enabled = !!(
    state?.available &&
    state.configured &&
    state.verified &&
    connectionIsEnabled
  );
  const outbound = retellOutbound(endpoint),
    batch = endpoint === "createBatchCall";
  const fields = schema ? retellFields(schema.input_schema) : [];
  const groups = [
    ...new Set(catalog?.operations.map((item) => item.group) ?? []),
  ].sort();
  const visible =
    catalog?.operations.filter(
      (item) =>
        (!group || item.group === group) &&
        `${item.endpoint} ${item.summary}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) ?? [];
  async function prepare() {
    if (
      !state ||
      !schema ||
      !operation?.available ||
      !enabled ||
      batch ||
      catalog?.revision !== state.revision
    )
      return;
    await act(async (current) => {
      const contact = contacts.find((item) => item.id === contactId);
      if (outbound && !contact)
        throw new Error("Selecciona un cliente del CRM.");
      const targetPath =
        fields.find((field) => field.name === "to_number")?.path ??
        "requestBody.to_number";
      const args = retellArguments(
        schema.input_schema,
        { ...values, ...(contact ? { [targetPath]: contact.phone } : {}) },
        advanced ? json : undefined,
      );
      if (contact) {
        if (targetPath.startsWith("requestBody.")) {
          if (
            args.requestBody !== undefined &&
            (!args.requestBody ||
              typeof args.requestBody !== "object" ||
              Array.isArray(args.requestBody))
          )
            throw new Error("requestBody debe ser un objeto.");
          args.requestBody = {
            ...((args.requestBody as Record<string, unknown>) ?? {}),
            to_number: contact.phone,
          };
        } else args.to_number = contact.phone;
      }
      const value = await request<ActionResult>("hermes/actions", "POST", {
        action: "retell.execute",
        arguments: {
          endpoint,
          arguments: args,
          ...(contact
            ? {
                contacts: [
                  { contact_id: contact.id, expected_phone: contact.phone },
                ],
              }
            : {}),
        },
      });
      if (current()) {
        setOutput(value);
        setOutputKey((previous) => previous + 1);
      }
    });
  }
  const status = loading
    ? "Consultando…"
    : !state?.available
      ? "No disponible"
      : !state.configured
        ? "Sin conectar"
        : !state.verified
          ? "Requiere verificación"
          : !connectionIsEnabled
            ? "Pausado"
            : "Verificado";
  return (
    <section
      className="retell-panel"
      aria-labelledby="retell-title"
      aria-busy={busy || loading}
    >
      <div className="settings-section-heading">
        <h3 id="retell-title">Retell AI</h3>
        <span className="social-status">{status}</span>
      </div>
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      {!operationsOnly && (
        <div className="retell-form">
          <label htmlFor="retell-key">
            Clave de API
            <input
              id="retell-key"
              type="password"
              autoComplete="new-password"
              value={key}
              maxLength={512}
              onChange={(event) => {
                setKey(event.target.value);
                setReplaceKey(false);
              }}
              disabled={busy || loading || !state?.available}
              placeholder={
                state?.configured
                  ? "Guardada · escribe solo para reemplazar"
                  : "Nueva clave"
              }
            />
          </label>
          {key && state?.configured && (
            <label className="retell-replace" htmlFor="retell-replace">
              <input
                id="retell-replace"
                type="checkbox"
                checked={replaceKey}
                onChange={(event) => setReplaceKey(event.target.checked)}
                disabled={busy}
              />
              Reemplazar la clave guardada
            </label>
          )}
          <div className="retell-fields">
            {(Object.keys(defaultsLabels) as (keyof Defaults)[]).map(
              (field) => (
                <label key={field} htmlFor={`retell-${field}`}>
                  {defaultsLabels[field]}
                  <input
                    id={`retell-${field}`}
                    value={defaults[field]}
                    maxLength={128}
                    onChange={(event) =>
                      setDefaults((previous) => ({
                        ...previous,
                        [field]: event.target.value,
                      }))
                    }
                    disabled={busy || loading}
                  />
                </label>
              ),
            )}
          </div>
          <div className="social-actions">
            <button
              type="button"
              className="crm-button"
              disabled={busy || loading || !state?.available}
              onClick={() => void save()}
            >
              Guardar conexión
            </button>
            <button
              type="button"
              className="crm-button crm-secondary"
              disabled={busy || loading || !state?.configured}
              onClick={() => void refresh()}
            >
              Consultar catálogo
            </button>
            <button
              type="button"
              className="crm-button crm-secondary"
              disabled={busy || !state?.configured}
              onClick={() => setDisconnect(true)}
            >
              Desconectar
            </button>
          </div>
        </div>
      )}
      {operationsOnly && (
        <button
          type="button"
          className="crm-button crm-secondary"
          disabled={busy || loading || !state?.configured}
          onClick={() => void refresh()}
        >
          Actualizar catálogo
        </button>
      )}
      {disconnect && (
        <div
          className="retell-confirm"
          role="group"
          aria-label="Confirmar desconexión de Retell"
        >
          <p>
            Se eliminará la clave y se invalidarán las propuestas pendientes.
          </p>
          <div className="social-actions">
            <button
              type="button"
              className="crm-button crm-secondary"
              disabled={busy}
              onClick={() => setDisconnect(false)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="crm-button"
              disabled={busy}
              onClick={() =>
                void act(async (current) => {
                  await request("retell/disconnect", "POST", {
                    revision: state?.revision,
                  });
                  const saved = await request<State>("retell/settings");
                  if (current()) {
                    setState(saved);
                    setDefaults({ ...empty, ...saved.defaults });
                    setCatalog(null);
                    setKey("");
                    setDisconnect(false);
                    resetOperation();
                  }
                  await onChanged();
                })
              }
            >
              Confirmar desconexión
            </button>
          </div>
        </div>
      )}
      {catalog && (
        <div className="retell-workspace">
          <div className="settings-section-heading">
            <h4>Operaciones</h4>
            <span className="settings-meta" role="status">
              {catalog.operations.filter((item) => item.available).length}{" "}
              disponibles ·{" "}
              {catalog.operations.filter((item) => !item.available).length}{" "}
              pendientes
            </span>
          </div>
          <div className="retell-fields">
            <label htmlFor="retell-search">
              Buscar
              <input
                id="retell-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Agentes, llamadas, chat…"
              />
            </label>
            <label htmlFor="retell-group">
              Grupo
              <select
                id="retell-group"
                value={group}
                onChange={(event) => setGroup(event.target.value)}
              >
                <option value="">Todos</option>
                {groups.map((value) => (
                  <option key={value} value={value}>
                    {groupLabels[value] ?? value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label htmlFor="retell-operation">
            Operación
            <select
              id="retell-operation"
              value={endpoint}
              disabled={busy}
              onChange={(event) => void choose(event.target.value)}
            >
              <option value="">Selecciona una operación</option>
              {operation &&
                !visible.some((item) => item.endpoint === endpoint) && (
                  <option value={endpoint}>{endpoint}</option>
                )}
              {visible.map((item) => (
                <option key={item.endpoint} value={item.endpoint}>
                  {item.endpoint} · {risks[item.risk]}
                  {!item.available ? " · No disponible" : ""}
                </option>
              ))}
            </select>
          </label>
          {visible.length === 0 && (
            <p className="settings-meta">
              No hay operaciones para esta búsqueda.
            </p>
          )}
          {operation && (
            <>
              <div className="retell-operation-meta">
                <code>
                  {operation.method} {operation.path}
                </code>
                <span className="social-status">{risks[operation.risk]}</span>
              </div>
              {!operation.available && (
                <p role="status" className="settings-meta">
                  {blockedLabels[operation.blocked_reason ?? ""] ??
                    "Operación no disponible en esta versión."}{" "}
                  <a
                    href="https://dashboard.retellai.com"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Abrir Retell ↗
                  </a>
                </p>
              )}
              {batch && (
                <p className="settings-meta" role="status">
                  Este editor admite un destinatario. Prepara envíos masivos con
                  Sara, vinculando y verificando cada cliente del CRM.
                </p>
              )}
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void prepare();
                }}
                className="retell-operation-form"
              >
                {schema && (
                  <>
                    <div
                      className="retell-mode"
                      role="group"
                      aria-label="Editor de argumentos"
                    >
                      <button
                        type="button"
                        aria-pressed={!advanced}
                        disabled={busy}
                        onClick={() => {
                          if (!advanced) return;
                          try {
                            setValues(
                              retellGuidedArguments(schema.input_schema, json),
                            );
                            setAdvanced(false);
                            setError("");
                          } catch (cause) {
                            setError(settingsError(cause));
                          }
                        }}
                      >
                        Campos
                      </button>
                      <button
                        type="button"
                        aria-pressed={advanced}
                        disabled={busy}
                        onClick={() => {
                          if (!advanced) {
                            try {
                              setJson(
                                JSON.stringify(
                                  retellArguments(schema.input_schema, values),
                                  null,
                                  2,
                                ),
                              );
                            } catch {
                              setJson("{}");
                            }
                          }
                          setAdvanced(true);
                        }}
                      >
                        JSON avanzado
                      </button>
                    </div>
                    {outbound && !batch && (
                      <label htmlFor="retell-contact">
                        Cliente del CRM
                        <select
                          id="retell-contact"
                          value={contactId}
                          required
                          disabled={busy}
                          onChange={(event) => setContactId(event.target.value)}
                        >
                          <option value="">Selecciona un cliente</option>
                          {contacts.map((contact) => (
                            <option key={contact.id} value={contact.id}>
                              {contact.name} · {contact.phone}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {advanced ? (
                      <label htmlFor="retell-json">
                        Argumentos JSON
                        <textarea
                          id="retell-json"
                          value={json}
                          onChange={(event) => setJson(event.target.value)}
                          maxLength={32768}
                          spellCheck={false}
                          disabled={busy}
                          rows={10}
                        />
                      </label>
                    ) : (
                      <div className="retell-fields">
                        {fields
                          .filter(
                            (field) =>
                              !(outbound && field.name === "to_number"),
                          )
                          .map((field) => (
                            <label
                              key={field.path}
                              htmlFor={`retell-field-${field.path}`}
                            >
                              {field.name}
                              {field.required ? " *" : ""}
                              {field.type === "boolean" || field.schema.enum ? (
                                <select
                                  id={`retell-field-${field.path}`}
                                  value={values[field.path] ?? ""}
                                  onChange={(event) =>
                                    setValues((previous) => ({
                                      ...previous,
                                      [field.path]: event.target.value,
                                    }))
                                  }
                                  disabled={busy}
                                  required={field.required}
                                >
                                  <option value="">Sin definir</option>
                                  {(field.schema.enum ?? [true, false]).map(
                                    (value) => (
                                      <option
                                        key={String(value)}
                                        value={String(value)}
                                      >
                                        {String(value)}
                                      </option>
                                    ),
                                  )}
                                </select>
                              ) : (
                                <input
                                  id={`retell-field-${field.path}`}
                                  value={values[field.path] ?? ""}
                                  onChange={(event) =>
                                    setValues((previous) => ({
                                      ...previous,
                                      [field.path]: event.target.value,
                                    }))
                                  }
                                  type={
                                    ["integer", "number"].includes(field.type)
                                      ? "number"
                                      : "text"
                                  }
                                  step={field.type === "integer" ? 1 : "any"}
                                  min={field.schema.minimum}
                                  max={field.schema.maximum}
                                  minLength={field.schema.minLength}
                                  maxLength={Math.min(
                                    field.schema.maxLength ?? 8192,
                                    8192,
                                  )}
                                  required={field.required}
                                  disabled={busy}
                                />
                              )}
                            </label>
                          ))}
                      </div>
                    )}
                    <p className="settings-meta">
                      Estructuras y listas: JSON avanzado. El servidor valida
                      antes de proponer.
                    </p>
                  </>
                )}
                <button
                  className="crm-button"
                  disabled={
                    busy ||
                    loading ||
                    !enabled ||
                    !schema ||
                    !operation.available ||
                    batch ||
                    (outbound && !contactId) ||
                    catalog.revision !== state?.revision
                  }
                >
                  Preparar propuesta
                </button>
              </form>
            </>
          )}
          {catalog.new_operations?.length > 0 && (
            <details className="retell-discovery">
              <summary>
                {catalog.new_operations.length} nuevas operaciones · pendientes
                de revisión
              </summary>
              <ul>
                {catalog.new_operations.map((item) => (
                  <li key={item.endpoint}>
                    {item.endpoint}{" "}
                    <span className="settings-meta">No habilitada</span>
                  </li>
                ))}
              </ul>
              <a
                href="https://dashboard.retellai.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                Abrir Retell ↗
              </a>
            </details>
          )}
          {active && output && (
            <ActionOutput
              key={outputKey}
              value={output}
              request={request}
              onChanged={onChanged}
              onResult={onResult}
            />
          )}
        </div>
      )}
    </section>
  );
}
