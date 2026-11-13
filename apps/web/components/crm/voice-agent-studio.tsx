"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Icon } from "./icon";
import { VoiceSchemaEditor } from "./voice-schema-editor";
import {
  voiceHydrateField,
  voiceSchemaProperties,
  voiceSchemaNullable,
  voiceSchemaResolve,
  voiceSchemaVariants,
  type VoiceSchemaDrafts,
} from "./voice-schema-model";
import { voiceCatalogOptions } from "./voice-agent-model";
import {
  studioChanges,
  studioGroups,
  studioTestArguments,
  type StudioSnapshot,
} from "./voice-agent-studio-model";
import { ActionOutput } from "./hermes-panel";
import { RetellPanel } from "./retell-panel";
import type { RetellSchema } from "./retell-schema";
import type { ActionResult, SettingsRequest } from "./settings-types";

type Props = {
  agent: StudioSnapshot;
  instructions?: StudioSnapshot;
  warning?: string;
  schemas: Record<string, RetellSchema>;
  voices: Record<string, unknown>[];
  models: Record<string, unknown>[];
  revision: number;
  available: string[];
  request: SettingsRequest;
  busy: boolean;
  onPendingChange: (value: boolean, owner: symbol) => void;
  onClose: () => void;
  onReload: () => void;
  onChanged: () => Promise<void>;
  onResult: (result: Record<string, unknown>) => void | Promise<void>;
};
type Panel =
  | { kind: "review"; output: ActionResult; warning?: string }
  | { kind: "operation"; endpoint: string; arguments: Record<string, unknown> };
const languageLabels: Record<string, string> = {
  "es-419": "Español · Latinoamérica",
  "es-ES": "Español · España",
  "en-US": "Inglés · Estados Unidos",
  multi: "Multilingüe",
};
export function VoiceAgentStudio({
  agent,
  instructions,
  warning,
  schemas,
  voices,
  models,
  revision,
  available,
  request,
  busy,
  onPendingChange,
  onClose,
  onReload,
  onChanged,
  onResult,
}: Props) {
  const id = useId();
  const [tab, setTab] = useState("agent"),
    [testMode, setTestMode] = useState<"audio" | "llm">("audio"),
    [simulation, setSimulation] = useState("cases");
  const [agentDrafts, setAgentDrafts] = useState<VoiceSchemaDrafts>({}),
    [llmDrafts, setLlmDrafts] = useState<VoiceSchemaDrafts>({});
  const [panel, setPanel] = useState<Panel | null>(null),
    [error, setError] = useState(""),
    [pending, setPending] = useState(false),
    [stale, setStale] = useState(false),
    [message, setMessage] = useState("");
  const [cases, setCases] = useState<Record<string, unknown>[] | null>(null),
    [caseError, setCaseError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null),
    opener = useRef<HTMLElement | null>(null),
    lock = useRef(false),
    pendingOwner = useRef(Symbol("voice-studio-request")),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const disabled = busy || pending || stale;
  const guardedRequest: SettingsRequest = useCallback(
    async <T,>(
      path: string,
      method?: string,
      payload?: unknown,
    ): Promise<T> => {
      const action =
        path === "hermes/actions" ||
        /^hermes\/proposals\/.+\/(approve|reject)$/.test(path);
      if (action) {
        if (lock.current) throw new Error("Hay una solicitud en curso.");
        onPendingChange(true, pendingOwner.current);
        lock.current = true;
        setPending(true);
      }
      try {
        return await request<T>(path, method, payload);
      } finally {
        if (action) {
          lock.current = false;
          onPendingChange(false, pendingOwner.current);
          if (alive.current) setPending(false);
        }
      }
    },
    [request, onPendingChange],
  );
  useEffect(() => {
    if (!panel || !dialog.current) return;
    opener.current = document.activeElement as HTMLElement;
    if (!dialog.current.open) dialog.current.showModal();
    return () => {
      if (dialog.current?.open) dialog.current.close();
      if (opener.current?.isConnected) opener.current.focus();
    };
  }, [panel?.kind, panel?.kind === "operation" ? panel.endpoint : "review"]);
  useEffect(() => {
    if (tab !== "simulation" || cases !== null || !instructions) return;
    let current = true;
    void request<Record<string, unknown>>("retell/read", "POST", {
      revision,
      endpoint: "listTestCaseDefinitions",
      arguments: {
        type: "retell-llm",
        llm_id: instructions.data.llm_id,
        limit: 50,
      },
    })
      .then((value) => {
        if (!current) return;
        if (
          value.provider !== "retell" ||
          value.status !== "completed" ||
          value.endpoint !== "listTestCaseDefinitions"
        )
          throw new Error("No se pudo verificar la lista.");
        const data = value.data;
        const rows = Array.isArray(data)
          ? data
          : data && typeof data === "object"
            ? (data as Record<string, unknown>).test_case_definitions
            : undefined;
        if (!Array.isArray(rows))
          throw new Error("La lista de casos no está disponible.");
        setCases(
          rows.filter(
            (row): row is Record<string, unknown> =>
              !!row && typeof row === "object" && !Array.isArray(row),
          ),
        );
      })
      .catch(() => {
        if (current)
          setCaseError("No se pudieron consultar los casos de este motor.");
      });
    return () => {
      current = false;
    };
  }, [tab, cases, instructions, request, revision]);
  const body = (kind: "agent" | "instructions") =>
    voiceSchemaProperties(
      schemas[kind === "agent" ? "updateAgent" : "updateRetellLLM"],
    ).requestBody;
  function field(kind: "agent" | "instructions", key: string) {
    const snap = kind === "agent" ? agent : instructions;
    if (!snap)
      return {
        editable: false,
        reason: "Las instrucciones completas no están disponibles.",
      };
    return voiceHydrateField(
      body(kind),
      key,
      snap.data,
      snap.completeFields,
      snap.blockedFields,
    );
  }
  function value(kind: "agent" | "instructions", key: string): string {
    if (!field(kind, key).editable) return "";
    const draft = (kind === "agent" ? agentDrafts : llmDrafts)[key];
    if (draft?.enabled) return draft.null ? "" : (draft.raw ?? "");
    const raw = (kind === "agent" ? agent : instructions)?.data[key];
    return typeof raw === "string" || typeof raw === "number"
      ? String(raw)
      : "";
  }
  function change(
    kind: "agent" | "instructions",
    key: string,
    raw: string | null,
  ) {
    if (disabled || !field(kind, key).editable) return;
    const set = kind === "agent" ? setAgentDrafts : setLlmDrafts;
    set((previous) => ({
      ...previous,
      [key]:
        raw === null ? { enabled: true, null: true } : { enabled: true, raw },
    }));
    setError("");
  }
  const draftCount = [
    ...Object.values(agentDrafts),
    ...Object.values(llmDrafts),
  ].filter((d) => d.enabled).length;
  function operation(endpoint: string, args: Record<string, unknown> = {}) {
    if (disabled || !available.includes(endpoint)) return;
    setPanel({ kind: "operation", endpoint, arguments: args });
    setError("");
  }
  async function review() {
    if (disabled || lock.current) return;
    try {
      const changes = studioChanges(
        schemas,
        agent,
        instructions,
        agentDrafts,
        llmDrafts,
      );
      if (!changes.length) {
        setError("No hay cambios para revisar.");
        return;
      }
      // Validate both records before creating the first proposal. Creation is not execution.
      if (changes.some((item) => !available.includes(item.endpoint)))
        throw new Error("La edición no está disponible para esta conexión.");
      for (const item of changes)
        if (
          new TextEncoder().encode(
            JSON.stringify({ action: "retell.execute", arguments: item }),
          ).byteLength > 16384
        )
          throw new Error(
            "El borrador supera el tamaño permitido. No se ha recortado.",
          );
      lock.current = true;
      setPending(true);
      onPendingChange(true, pendingOwner.current);
      const proposals: NonNullable<ActionResult["proposals"]> = [];
      let partial = "";
      for (const item of changes) {
        if (!alive.current) break;
        try {
          const result = await request<ActionResult>("hermes/actions", "POST", {
            action: "retell.execute",
            arguments: item,
          });
          if (!Array.isArray(result.proposals) || !result.proposals.length)
            throw new Error("No se confirmó la propuesta.");
          proposals.push(...result.proposals);
        } catch {
          partial =
            "La preparación quedó incompleta. Revisa las propuestas recibidas antes de repetirla.";
          break;
        }
      }
      if (alive.current) {
        if (proposals.length)
          setPanel({ kind: "review", output: { proposals }, warning: partial });
        else
          setError(
            "No se confirmó la preparación. Conservamos el borrador; revisa el estado antes de repetirla.",
          );
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Revisa la configuración.",
      );
    } finally {
      lock.current = false;
      onPendingChange(false, pendingOwner.current);
      if (alive.current) setPending(false);
    }
  }
  async function prepareTest() {
    if (disabled || lock.current) return;
    const endpoint =
      testMode === "audio" ? "createWebCall" : "agentPlaygroundCompletion";
    if (!available.includes(endpoint)) return;
    try {
      const output = await guardedRequest<ActionResult>(
        "hermes/actions",
        "POST",
        {
          action: "retell.execute",
          arguments: {
            endpoint,
            arguments: studioTestArguments(testMode, agent.data, message),
          },
        },
      );
      if (alive.current) setPanel({ kind: "review", output });
    } catch {
      if (alive.current)
        setError(
          "No se confirmó la preparación de la prueba. Revisa su estado antes de repetirla.",
        );
    }
  }
  async function result(value: Record<string, unknown>) {
    if (
      value.provider === "retell" &&
      value.status === "completed" &&
      /^(create|update|delete)TestCaseDefinition$/.test(String(value.endpoint))
    ) {
      setCases(null);
      setCaseError("");
    }
    if (
      value.provider === "retell" &&
      value.status === "completed" &&
      typeof value.endpoint === "string" &&
      /^(update|publish|delete)/.test(value.endpoint)
    )
      setStale(true);
    await onResult(value);
  }
  function controls(groupKey: string, workflowKeys?: string[]) {
    const group = studioGroups.find((group) => group.key === groupKey)!;
    return (["agent", "instructions"] as const).map((kind) => {
      const snapshot = kind === "agent" ? agent : instructions;
      const keys = (workflowKeys ?? group[kind]).filter(
        (key) =>
          !(
            groupKey === "primary" &&
            !workflowKeys &&
            [
              "agent_name",
              "voice_id",
              "language",
              "general_prompt",
              "begin_message",
            ].includes(key)
          ),
      );
      if (!snapshot || !keys.length) return null;
      const schema =
        schemas[kind === "agent" ? "updateAgent" : "updateRetellLLM"];
      return (
        <VoiceSchemaEditor
          key={`${groupKey}-${kind}`}
          schema={schema}
          record={snapshot.data}
          completeFields={snapshot.completeFields}
          blockedFields={snapshot.blockedFields}
          drafts={kind === "agent" ? agentDrafts : llmDrafts}
          onChange={kind === "agent" ? setAgentDrafts : setLlmDrafts}
          exclude={Object.keys(voiceSchemaProperties(body(kind))).filter(
            (key) => !keys.includes(key),
          )}
          disabled={disabled}
          voices={voices}
          models={models}
        />
      );
    });
  }
  function select(
    kind: "agent" | "instructions",
    key: string,
    label: string,
    options: { value: string; label: string }[],
  ) {
    const current = value(kind, key);
    return (
      <label className="voice-studio-chip">
        <span>{label}</span>
        <select
          name={`studio_${key}`}
          aria-label={label}
          disabled={disabled || !field(kind, key).editable}
          value={current}
          onChange={(e) => change(kind, key, e.target.value)}
        >
          <option value="">Sin configurar</option>
          {current && !options.some((item) => item.value === current) ? (
            <option value={current}>
              {key === "language"
                ? (languageLabels[current] ?? current)
                : current}
            </option>
          ) : null}
          {options.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  function textField(key: "general_prompt" | "begin_message") {
    const state = field("instructions", key),
      nullable = voiceSchemaNullable(
        voiceSchemaProperties(body("instructions"))[key],
      );
    return (
      <section
        className={`voice-studio-text ${key === "general_prompt" ? "voice-studio-prompt" : ""}`}
      >
        <div className="voice-studio-field-title">
          <label htmlFor={`${id}-${key}`}>
            {key === "general_prompt" ? "Prompt del agente" : "Saludo inicial"}
          </label>
          {nullable ? (
            <button
              type="button"
              className="voice-studio-link"
              disabled={disabled || !state.editable}
              onClick={() => change("instructions", key, null)}
            >
              {key === "begin_message"
                ? "Saludo dinámico"
                : "Dejar sin instrucciones"}
            </button>
          ) : null}
        </div>
        <textarea
          id={`${id}-${key}`}
          name={`studio_${key}`}
          aria-describedby={
            !state.editable ? `${id}-${key}-blocked` : undefined
          }
          value={value("instructions", key)}
          readOnly={disabled || !state.editable}
          onChange={(e) => change("instructions", key, e.target.value)}
          placeholder={
            key === "general_prompt"
              ? "Define la identidad, el objetivo y los límites del agente."
              : "Escribe el mensaje de bienvenida."
          }
        />
        {!state.editable ? (
          <p id={`${id}-${key}-blocked`} className="voice-schema-warning">
            {state.reason}
          </p>
        ) : null}
      </section>
    );
  }
  const modelSchema = voiceSchemaResolve(
    voiceSchemaProperties(body("instructions")).model ?? {},
  );
  const modern =
    !!instructions?.data.model_config || !!llmDrafts.model_config?.enabled;
  return (
    <div className="voice-agent-studio">
      <header className="voice-studio-header">
        <button
          className="voice-studio-back"
          type="button"
          onClick={onClose}
          disabled={busy || pending}
          aria-label="Cerrar editor del agente"
        >
          <Icon name="chevron" />
        </button>
        <div className="voice-studio-identity">
          <input
            aria-label="Nombre del agente"
            value={value("agent", "agent_name")}
            readOnly={disabled || !field("agent", "agent_name").editable}
            onChange={(e) => change("agent", "agent_name", e.target.value)}
          />
          <span>
            Versión {String(agent.data.version ?? "sin dato")} ·{" "}
            {stale
              ? "Lectura anterior"
              : draftCount
                ? "Cambios sin guardar"
                : "Configuración guardada"}
          </span>
        </div>
        <div className="voice-studio-header-actions">
          <button
            type="button"
            className="crm-button crm-secondary"
            disabled={disabled}
            onClick={() =>
              operation("listAgentVersions", { agent_id: agent.data.agent_id })
            }
          >
            <Icon name="history" />
            Versiones
          </button>
          <button
            type="button"
            className="crm-button crm-secondary"
            disabled={
              disabled ||
              draftCount > 0 ||
              !available.includes("publishAgentVersion")
            }
            onClick={() =>
              operation("publishAgentVersion", {
                agent_id: agent.data.agent_id,
                requestBody: { version: agent.data.version },
              })
            }
          >
            Publicar
          </button>
          <button
            type="button"
            className="crm-button"
            disabled={disabled || !draftCount}
            onClick={() => void review()}
          >
            {pending ? "Preparando…" : "Revisar cambios"}
          </button>
        </div>
      </header>
      <nav className="voice-studio-tabs" aria-label="Editor del agente">
        {[
          ["agent", "Agente"],
          ["workflow", "Flujo de trabajo"],
          ["simulation", "Simulación"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-current={tab === key ? "page" : undefined}
            onClick={() => setTab(key)}
          >
            <Icon
              name={
                key === "agent"
                  ? "people"
                  : key === "workflow"
                    ? "connections"
                    : "task"
              }
            />
            {label}
          </button>
        ))}
      </nav>
      {warning ? <p className="voice-studio-notice">{warning}</p> : null}
      {stale ? (
        <p className="voice-studio-notice" role="status">
          La versión guardada cambió. Vuelve a cargarla antes de editar o
          probar.
          <button
            type="button"
            className="voice-studio-link"
            disabled={pending || busy}
            onClick={onReload}
          >
            Cargar versión guardada
          </button>
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="voice-error voice-studio-notice">
          {error}
        </p>
      ) : null}
      {tab === "agent" ? (
        <div className="voice-studio-columns">
          <section
            className="voice-studio-writing"
            aria-label="Prompt y modelo"
          >
            <div className="voice-studio-metadata">
              <span>Instrucciones del agente</span>
              <details>
                <summary>ID</summary>
                <code>{String(agent.data.agent_id)}</code>
              </details>
            </div>
            <div className="voice-studio-toolbar">
              {modern ? (
                <details className="voice-studio-model-menu">
                  <summary>Modelo configurado · Ajustes</summary>
                  {controls("primary")}
                </details>
              ) : (
                select(
                  "instructions",
                  "model",
                  "Modelo de respuesta",
                  (modelSchema?.enum ?? [])
                    .filter((item): item is string => typeof item === "string")
                    .map((item) => ({ value: item, label: item })),
                )
              )}
              {select(
                "agent",
                "voice_id",
                "Voz",
                voiceCatalogOptions(voices, "voice_id", "voice_name"),
              )}
              {Array.isArray(agent.data.language) ? (
                <details className="voice-studio-model-menu">
                  <summary>Idioma · Multilingüe</summary>
                  {controls("primary", ["language"])}
                </details>
              ) : (
                select(
                  "agent",
                  "language",
                  "Idioma",
                  [
                    ...new Set(
                      [
                        voiceSchemaResolve(
                          voiceSchemaProperties(body("agent")).language ?? {},
                        ),
                        ...voiceSchemaVariants(
                          voiceSchemaProperties(body("agent")).language ?? {},
                        ),
                      ]
                        .flatMap((schema) => schema.enum ?? [])
                        .filter(
                          (item): item is string => typeof item === "string",
                        ),
                    ),
                  ].map((item) => ({
                    value: item,
                    label: languageLabels[item] ?? item,
                  })),
                )
              )}
            </div>
            {textField("general_prompt")}
            {textField("begin_message")}
            <div className="voice-studio-welcome-settings">
              {controls("primary", [
                "start_speaker",
                "begin_after_user_silence_ms",
              ])}
            </div>
          </section>
          <aside
            className="voice-studio-settings"
            aria-label="Ajustes del agente"
          >
            {studioGroups
              .filter((group) => group.key !== "primary")
              .map((group) => (
                <details key={group.key} className="voice-studio-accordion">
                  <summary>
                    <Icon name={group.icon} />
                    <span>{group.label}</span>
                    <Icon name="chevron" />
                  </summary>
                  <div>{controls(group.key)}</div>
                </details>
              ))}
            <details className="voice-studio-accordion">
              <summary>
                <Icon name="settings" />
                <span>Configuración avanzada</span>
                <Icon name="chevron" />
              </summary>
              <div>{controls("primary")}</div>
            </details>
          </aside>
          <aside
            className="voice-studio-testing"
            aria-label="Pruebas del agente"
          >
            <nav aria-label="Modo de prueba">
              {(["audio", "llm"] as const).map((mode) => (
                <button
                  type="button"
                  key={mode}
                  aria-pressed={testMode === mode}
                  onClick={() => setTestMode(mode)}
                >
                  {mode === "audio" ? "Prueba de audio" : "Prueba LLM"}
                </button>
              ))}
            </nav>
            <div className="voice-studio-test-content">
              <Icon
                name={testMode === "audio" ? "microphone" : "message"}
                size={42}
              />
              <h3>
                {testMode === "audio"
                  ? "Escucha a tu agente"
                  : "Conversa con tu agente"}
              </h3>
              <p>
                Se probará la versión guardada. Los cambios del borrador no se
                incluyen.
              </p>
              {testMode === "llm" ? (
                <label>
                  Mensaje de prueba
                  <textarea
                    name="studio_test_message"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    placeholder="Escribe un mensaje…"
                  />
                </label>
              ) : null}
              <button
                type="button"
                className="crm-button crm-secondary"
                disabled={
                  disabled ||
                  !available.includes(
                    testMode === "audio"
                      ? "createWebCall"
                      : "agentPlaygroundCompletion",
                  ) ||
                  (testMode === "llm" && !message.trim())
                }
                onClick={() => void prepareTest()}
              >
                Preparar prueba {testMode === "audio" ? "de audio" : "LLM"}
              </button>
              <span className="voice-muted">
                Consume créditos · Requiere aprobación
                {testMode === "audio" ? " y permiso del micrófono" : ""}
              </span>
              {draftCount ? (
                <p className="voice-schema-warning">
                  Tienes cambios sin guardar.
                </p>
              ) : null}
            </div>
          </aside>
        </div>
      ) : tab === "workflow" ? (
        <section
          className="voice-studio-workflow"
          aria-label="Flujo de trabajo"
        >
          {[
            ["before", "Antes de la llamada", ["pre_session_tools"]],
            ["during", "Durante la llamada", []],
            [
              "after",
              "Después de la llamada",
              [
                "post_session_tools",
                "post_call_analysis_data",
                "post_call_analysis_model",
                "contact_memory_config",
                "webhook_url",
                "webhook_events",
                "webhook_timeout_ms",
              ],
            ],
          ].map(([key, label, keys]) => (
            <section key={String(key)} className="voice-studio-phase">
              <span className="voice-studio-phase-marker">
                <Icon
                  name={
                    key === "before"
                      ? "connections"
                      : key === "during"
                        ? "phone"
                        : "task"
                  }
                />
              </span>
              <h3>{String(label)}</h3>
              {key === "during" ? (
                <>
                  <p>Prompt, funciones, conocimiento y conversación.</p>
                  <button
                    type="button"
                    className="crm-button crm-secondary"
                    onClick={() => setTab("agent")}
                  >
                    Editar conversación
                  </button>
                </>
              ) : (
                <div className="voice-studio-settings">
                  {controls("functions", keys as string[])}
                </div>
              )}
            </section>
          ))}
        </section>
      ) : (
        <section className="voice-studio-simulation" aria-label="Simulación">
          <header>
            <h3>Pruebas de simulación</h3>
            <button
              type="button"
              className="crm-button crm-secondary"
              disabled={
                disabled || !available.includes("createTestCaseDefinition")
              }
              onClick={() =>
                operation("createTestCaseDefinition", {
                  requestBody: { response_engine: agent.data.response_engine },
                })
              }
            >
              <Icon name="plus" />
              Nuevo caso
            </button>
            <button
              type="button"
              className="crm-button"
              disabled={disabled || !available.includes("createBatchTest")}
              onClick={() =>
                operation("createBatchTest", {
                  requestBody: { response_engine: agent.data.response_engine },
                })
              }
            >
              Preparar simulación
            </button>
          </header>
          <nav aria-label="Resultados de simulación">
            <button
              type="button"
              aria-pressed={simulation === "cases"}
              onClick={() => setSimulation("cases")}
            >
              Casos de prueba
            </button>
            <button
              type="button"
              aria-pressed={simulation === "history"}
              onClick={() => setSimulation("history")}
            >
              Historial de pruebas
            </button>
          </nav>
          {simulation === "history" ? (
            <div className="voice-studio-empty">
              <Icon name="history" size={32} />
              <h4>Historial de ejecuciones</h4>
              <p>Consulta los lotes de pruebas y sus resultados.</p>
              <button
                type="button"
                className="crm-button crm-secondary"
                disabled={disabled || !available.includes("listBatchTests")}
                onClick={() => operation("listBatchTests")}
              >
                Consultar historial
              </button>
              <button
                type="button"
                className="crm-button crm-secondary"
                disabled={disabled || !available.includes("listTestRuns")}
                onClick={() => operation("listTestRuns")}
              >
                Consultar resultados de un lote
              </button>
            </div>
          ) : caseError ? (
            <p role="alert">{caseError}</p>
          ) : cases === null ? (
            <p role="status">
              {instructions
                ? "Consultando casos…"
                : "Este motor no tiene instrucciones Retell LLM vinculadas."}
            </p>
          ) : cases.length ? (
            <div className="voice-studio-case-list">
              {cases.map((row, index) => (
                <article key={String(row.test_case_definition_id ?? index)}>
                  <h4>
                    {String(
                      row.name ??
                        row.test_case_definition_name ??
                        "Caso de prueba",
                    )}
                  </h4>
                  <p>
                    {String(row.user_prompt ?? "Consulta el detalle del caso.")}
                  </p>
                  <button
                    type="button"
                    className="crm-button crm-secondary"
                    disabled={
                      disabled || !available.includes("getTestCaseDefinition")
                    }
                    onClick={() =>
                      operation("getTestCaseDefinition", {
                        test_case_definition_id: row.test_case_definition_id,
                      })
                    }
                  >
                    Ver caso
                  </button>
                  <button
                    type="button"
                    className="crm-button crm-secondary"
                    disabled={
                      disabled ||
                      !available.includes("updateTestCaseDefinition")
                    }
                    onClick={() =>
                      operation("updateTestCaseDefinition", {
                        test_case_definition_id: row.test_case_definition_id,
                        requestBody: {},
                      })
                    }
                  >
                    Editar caso
                  </button>
                  <button
                    type="button"
                    className="crm-button crm-secondary"
                    disabled={
                      disabled ||
                      !available.includes("deleteTestCaseDefinition")
                    }
                    onClick={() =>
                      operation("deleteTestCaseDefinition", {
                        test_case_definition_id: row.test_case_definition_id,
                      })
                    }
                  >
                    Eliminar caso
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <div className="voice-studio-empty">
              <Icon name="task" size={32} />
              <h4>No hay casos de prueba</h4>
              <p>Crea un escenario y define cómo evaluar la conversación.</p>
            </div>
          )}
        </section>
      )}
      <dialog
        className="voice-studio-action-dialog"
        ref={dialog}
        aria-labelledby={`${id}-review-title`}
        onCancel={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!pending && !busy) setPanel(null);
        }}
      >
        <header>
          <h3 id={`${id}-review-title`}>
            {panel?.kind === "review"
              ? "Revisar cambios"
              : "Función del agente"}
          </h3>
          <button
            type="button"
            className="crm-button crm-secondary"
            disabled={pending || busy}
            onClick={() => setPanel(null)}
          >
            Volver al editor
          </button>
        </header>
        {panel?.kind === "review" ? (
          <>
            {panel.warning ? (
              <p role="alert" className="voice-schema-warning">
                {panel.warning}
              </p>
            ) : null}
            <p className="voice-muted">
              Agente e instrucciones se guardan por separado. Cada propuesta
              requiere su aprobación.
            </p>
            <ActionOutput
              value={panel.output}
              presentation="friendly"
              request={guardedRequest}
              onChanged={onChanged}
              onResult={result}
            />
          </>
        ) : panel?.kind === "operation" ? (
          <RetellPanel
            key={panel.endpoint}
            request={guardedRequest}
            active
            operationsOnly
            friendly
            initialOperation={{
              endpoint: panel.endpoint,
              arguments: panel.arguments,
            }}
            onChanged={onChanged}
            onResult={result}
          />
        ) : null}
      </dialog>
    </div>
  );
}
