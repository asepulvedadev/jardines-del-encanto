"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ActionOutput, ActionResultDetails } from "./hermes-panel";
import { RetellPanel } from "./retell-panel";
import { VoiceAgentEditor } from "./voice-agent-editor";
import { VoiceAgentStudio } from "./voice-agent-studio";
import type { StudioSnapshot } from "./voice-agent-studio-model";
import type { RetellSchema } from "./retell-schema";
import type { ActionResult, SettingsRequest } from "./settings-types";
import { voiceRequest } from "./voice-request";
import {
  mergeConfirmed,
  object,
  resourceRows,
  resourceSeed,
  sections,
  text,
  type VoiceRecord,
  type VoiceSnapshot,
} from "./voice-workspace-data";

type State = {
  available: boolean;
  configured: boolean;
  verified: boolean;
  enabled: boolean;
  revision: number;
};
type Operation = {
  endpoint: string;
  group: string;
  available: boolean;
  blocked_reason?: string;
};
type Catalog = { revision: number; operations: Operation[] };
type Modal =
  | {
      kind: "studio";
      agent: StudioSnapshot;
      instructions?: StudioSnapshot;
      warning?: string;
      generation: number;
    }
  | { kind: "operation"; endpoint: string; arguments: VoiceRecord }
  | {
      kind: "agent" | "instructions";
      record?: VoiceRecord;
      completeFields?: string[];
      blockedFields?: Record<string, string>;
    }
  | { kind: "review"; output: ActionResult }
  | { kind: "details"; result: VoiceRecord };
type Inventory = {
  snapshots: VoiceSnapshot[];
  partial: true;
  errors?: { endpoint: string; code: string }[];
  cached?: boolean;
};
const automaticReads = new Set([
  ...sections.flatMap((item) => [item.list, item.get]),
  "listAgentVersions",
]);
const schemaEndpoints = [
  "createAgent",
  "updateAgent",
  "createRetellLLM",
  "updateRetellLLM",
];
export function VoiceWorkspace({
  csrf,
  active,
  onChanged,
  onOpenConnection,
}: {
  csrf: string;
  active: boolean;
  onChanged: () => Promise<void>;
  onOpenConnection: () => void;
}) {
  const router = useRouter();
  const [state, setState] = useState<State | null>(null),
    [catalog, setCatalog] = useState<Catalog | null>(null);
  const [snapshots, setSnapshots] = useState<VoiceSnapshot[]>([]),
    [schemas, setSchemas] = useState<Record<string, RetellSchema>>({});
  const [resourceErrors, setResourceErrors] = useState<string[]>([]);
  const [sectionKey, setSectionKey] = useState("agents"),
    [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [approvalBusy, setApprovalBusy] = useState(false),
    [error, setError] = useState("");
  const [modal, setModal] = useState<Modal | null>(null);
  const studioGeneration = useRef(0);
  const studioLockOwner = useRef<symbol | null>(null);
  const studioPending = useCallback((value: boolean, owner: symbol) => {
    if (value) {
      if (lock.current && studioLockOwner.current !== owner)
        throw new Error("Hay una solicitud en curso.");
      studioLockOwner.current = owner;
      lock.current = true;
      setBusy(true);
    } else if (studioLockOwner.current === owner) {
      studioLockOwner.current = null;
      lock.current = false;
      setBusy(false);
    }
  }, []);
  const dialog = useRef<HTMLDialogElement>(null),
    lock = useRef(false),
    alive = useRef(false),
    epoch = useRef(0),
    focusReturn = useRef<HTMLElement | null>(null);
  const baseRequest = useMemo(
    () => voiceRequest(csrf, () => router.replace("/login")),
    [csrf, router],
  );
  const request: SettingsRequest = useCallback(
    async <T,>(
      path: string,
      method?: string,
      payload?: unknown,
    ): Promise<T> => {
      const approval = /^hermes\/proposals\/[^/]+\/(approve|reject)$/.test(
        path,
      );
      if (approval) setApprovalBusy(true);
      try {
        return await baseRequest<T>(path, method, payload);
      } finally {
        if (approval && alive.current) setApprovalBusy(false);
      }
    },
    [baseRequest],
  );
  const load = useCallback(async () => {
    const run = ++epoch.current;
    if (alive.current) {
      setLoading(true);
      setError("");
    }
    try {
      const settings = await request<State>("retell/settings");
      const [saved, operations] = await Promise.allSettled([
        settings.available &&
        settings.configured &&
        settings.enabled &&
        settings.verified
          ? request<Inventory>("retell/inventory", "POST", {
              revision: settings.revision,
            })
          : Promise.resolve({
              snapshots: [],
              partial: true,
              errors: [],
            } as Inventory),
        settings.available && settings.configured
          ? request<Catalog>("retell/catalog", "POST", {
              revision: settings.revision,
            })
          : Promise.resolve(null),
      ]);
      if (!alive.current || run !== epoch.current) return;
      setState(settings);
      setSnapshots(saved.status === "fulfilled" ? saved.value.snapshots : []);
      setCatalog(operations.status === "fulfilled" ? operations.value : null);
      setResourceErrors(
        saved.status === "fulfilled"
          ? (saved.value.errors ?? []).map((item) => item.endpoint)
          : [],
      );
      const failed = [saved, operations].find(
        (item) => item.status === "rejected",
      );
      if (failed?.status === "rejected")
        setError(
          failed.reason instanceof Error
            ? failed.reason.message
            : "No se pudo actualizar esta vista.",
        );
      setSchemas({});
    } catch (cause) {
      if (alive.current && run === epoch.current) {
        setError(
          cause instanceof Error ? cause.message : "No se pudo cargar Retell.",
        );
        setState(null);
        setCatalog(null);
        setSnapshots([]);
      }
    } finally {
      if (alive.current && run === epoch.current) setLoading(false);
    }
  }, [request]);
  useEffect(() => {
    alive.current = true;
    if (active) void load();
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, [active, load]);
  useEffect(() => {
    if (modal && active) {
      if (!dialog.current?.open) {
        focusReturn.current ??= document.activeElement as HTMLElement;
        dialog.current?.showModal();
      }
    } else if (dialog.current?.open) {
      dialog.current.close();
      if (active) focusReturn.current?.focus();
      focusReturn.current = null;
    }
  }, [modal, active]);
  useEffect(() => {
    if (!active) setModal(null);
  }, [active]);
  const section =
    sections.find((item) => item.key === sectionKey) ?? sections[0];
  const enabled = !!(
    state?.available &&
    state.configured &&
    state.verified &&
    state.enabled &&
    catalog?.revision === state.revision
  );
  const operation = (endpoint: string) =>
    catalog?.operations.find((item) => item.endpoint === endpoint);
  const rows = useMemo(
    () => resourceRows(snapshots, section, state?.revision ?? -1),
    [snapshots, section, state?.revision],
  );
  const filtered = rows.filter((row) =>
    `${text(row[section.name])} ${text(row[section.id])}`
      .toLocaleLowerCase("es")
      .includes(query.toLocaleLowerCase("es")),
  );
  const voices = resourceRows(snapshots, sections[1], state?.revision ?? -1),
    models = resourceRows(snapshots, sections[6], state?.revision ?? -1);
  const last = snapshots
    .filter(
      (s) =>
        s.provider_revision === state?.revision &&
        [section.list, section.get].includes(s.endpoint),
    )
    .at(-1)?.created_at;
  function rememberFocus() {
    if (!dialog.current?.open)
      focusReturn.current = document.activeElement as HTMLElement;
  }
  async function task(work: () => Promise<void>) {
    if (lock.current) return;
    rememberFocus();
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (cause) {
      if (alive.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "No se pudo preparar la operación.",
        );
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function prepare(endpoint: string, args: VoiceRecord) {
    if (!enabled || !operation(endpoint)?.available)
      throw new Error(
        "La función no está disponible. Actualiza la conexión y el catálogo.",
      );
    const run = epoch.current;
    const output = await request<ActionResult>("hermes/actions", "POST", {
      action: "retell.execute",
      arguments: { endpoint, arguments: args },
    });
    if (alive.current && run === epoch.current)
      setModal({ kind: "review", output });
  }
  async function readResource(endpoint: string, args: VoiceRecord) {
    if (!state || !enabled || !automaticReads.has(endpoint))
      throw new Error("Esta consulta no está disponible.");
    return request<VoiceRecord>("retell/read", "POST", {
      revision: state.revision,
      endpoint,
      arguments: args,
    });
  }
  async function readEditor(
    kind: "agent" | "instructions",
    id: string,
    version?: unknown,
  ) {
    if (!state || !enabled)
      throw new Error("Esta consulta no está disponible.");
    const result = await request<VoiceRecord>("retell/editor", "POST", {
      revision: state.revision,
      kind,
      id,
      ...(version != null ? { version } : {}),
    });
    const key = kind === "agent" ? "agent_id" : "llm_id";
    const endpoint = kind === "agent" ? "getAgent" : "getRetellLLM";
    const metadata = result.editor;
    if (
      result.provider !== "retell" ||
      result.status !== "completed" ||
      result.endpoint !== endpoint ||
      !object(result.data) ||
      result.data[key] !== id ||
      (version != null && result.data.version !== version) ||
      !object(metadata) ||
      !Array.isArray(metadata.complete_fields) ||
      !metadata.complete_fields.every((field) => typeof field === "string") ||
      !object(metadata.blocked_fields) ||
      !Object.values(metadata.blocked_fields).every(
        (reason) => typeof reason === "string",
      )
    )
      throw new Error(
        "No se pudo verificar la lectura completa de la configuración. No se habilitó la edición.",
      );
    return {
      data: result.data,
      completeFields: metadata.complete_fields as string[],
      blockedFields: metadata.blocked_fields as Record<string, string>,
    };
  }
  async function agentStudio(record: VoiceRecord) {
    await task(async () => {
      if (!state || !enabled) return;
      const run = epoch.current;
      const agent = await readEditor("agent", text(record.agent_id));
      if (!alive.current || run !== epoch.current) return;
      const engine = agent.data.response_engine;
      let instructions: StudioSnapshot | undefined;
      let warning: string | undefined;
      if (
        object(engine) &&
        engine.type === "retell-llm" &&
        text(engine.llm_id)
      ) {
        try {
          instructions = await readEditor(
            "instructions",
            text(engine.llm_id),
            engine.version,
          );
        } catch {
          warning =
            "No se pudieron cargar las instrucciones completas. Los ajustes seguros del agente siguen disponibles.";
        }
      } else {
        warning =
          object(engine) && engine.type === "conversation-flow"
            ? "Este agente usa un flujo de conversación. El prompt de Retell LLM no está disponible; el motor no se convertirá."
            : "Este agente no tiene instrucciones Retell LLM editables. Su motor se conserva sin cambios.";
      }
      if (!alive.current || run !== epoch.current) return;
      const definitions = await Promise.all(
        schemaEndpoints.map(async (endpoint) => {
          const result = await request<{ input_schema: RetellSchema }>(
            "retell/schema",
            "POST",
            { revision: state.revision, endpoint },
          );
          return [endpoint, result.input_schema] as const;
        }),
      );
      if (!alive.current || run !== epoch.current) return;
      setSchemas(Object.fromEntries(definitions));
      setModal({
        kind: "studio",
        agent,
        instructions,
        warning,
        generation: ++studioGeneration.current,
      });
    });
  }
  async function editor(
    kind: "agent" | "instructions",
    record?: VoiceRecord,
    fromAgent = false,
  ) {
    if (record?.agent_id && (kind === "agent" || fromAgent)) {
      await agentStudio(record);
      return;
    }
    await task(async () => {
      if (!state || !enabled) return;
      const run = epoch.current;
      let currentRecord = record;
      let completeFields: string[] | undefined;
      let blockedFields: Record<string, string> | undefined;
      if (fromAgent) {
        const agentId = text(record?.agent_id);
        const result = await readEditor("agent", agentId);
        if (!object(result.data) || result.data.agent_id !== agentId)
          throw new Error(
            "No se pudo verificar el agente. No se abrió ningún prompt.",
          );
        if (!alive.current || run !== epoch.current) return;
        const engine = result.data.response_engine;
        if (
          !object(engine) ||
          engine.type !== "retell-llm" ||
          !text(engine.llm_id)
        )
          throw new Error(
            object(engine) && engine.type === "conversation-flow"
              ? "Este agente usa un flujo de conversación. Su comportamiento se edita en Flujos."
              : "Este agente no tiene un prompt de Retell LLM vinculado.",
          );
        if (
          engine.version != null &&
          (!Number.isSafeInteger(engine.version) || Number(engine.version) < 0)
        )
          throw new Error(
            "No se pudo verificar la versión de las instrucciones.",
          );
        currentRecord = {
          llm_id: engine.llm_id,
          ...(engine.version != null ? { version: engine.version } : {}),
        };
      }
      if (currentRecord) {
        const key = kind === "agent" ? "agent_id" : "llm_id";
        const target = currentRecord;
        const result = await readEditor(
          kind,
          text(target[key]),
          fromAgent ? target.version : undefined,
        );
        if (!alive.current || run !== epoch.current) return;
        // Full editor records stay in this modal, never in the partial inventory cache.
        currentRecord = result.data;
        completeFields = result.completeFields;
        blockedFields = result.blockedFields;
      }
      const definitions = await Promise.all(
        schemaEndpoints.map(async (endpoint) => {
          const value = await request<{ input_schema: RetellSchema }>(
            "retell/schema",
            "POST",
            { revision: state.revision, endpoint },
          );
          return [endpoint, value.input_schema] as const;
        }),
      );
      if (alive.current && run === epoch.current) {
        setSchemas(Object.fromEntries(definitions));
        setModal({
          kind,
          record: currentRecord,
          completeFields,
          blockedFields,
        });
      }
    });
  }
  function openOperation(endpoint: string, args: VoiceRecord = {}) {
    if (operation(endpoint)) {
      if (automaticReads.has(endpoint)) {
        void task(async () => {
          const run = epoch.current;
          const result = await readResource(endpoint, args);
          if (alive.current && run === epoch.current && state) {
            setSnapshots((old) => mergeConfirmed(old, result, state.revision));
            setModal({ kind: "details", result });
          }
        });
        return;
      }
      rememberFocus();
      setModal({ kind: "operation", endpoint, arguments: args });
    }
  }
  async function confirmed(result: VoiceRecord) {
    if (!alive.current || !state) return;
    setSnapshots((old) => mergeConfirmed(old, result, state.revision));
    // Only fixed safe inventory reads may follow a confirmed write, never re-dispatch it.
    if (
      result.provider === "retell" &&
      result.status === "completed" &&
      !/^(get|list)/.test(text(result.endpoint))
    ) {
      try {
        const run = epoch.current;
        const fresh = await request<Inventory>("retell/inventory", "POST", {
          revision: state.revision,
        });
        if (alive.current && run === epoch.current) {
          setSnapshots((old) => [
            ...fresh.snapshots,
            ...old.filter(
              (item) =>
                !sections.some((section) => section.list === item.endpoint),
            ),
          ]);
          setResourceErrors((fresh.errors ?? []).map((item) => item.endpoint));
        }
      } catch {
        if (alive.current)
          setError(
            "El cambio ya se confirmó. La sincronización está pendiente; no repitas la acción.",
          );
      }
    }
  }
  async function changed() {
    try {
      await onChanged();
    } catch {
      if (alive.current)
        setError(
          "La acción ya respondió; no pudimos actualizar el CRM. No la repitas.",
        );
    }
  }
  function close() {
    if (busy || approvalBusy) return;
    setModal(null);
  }
  const status = loading
    ? "Consultando conexión…"
    : !state?.available
      ? "No disponible"
      : !state.configured
        ? "Sin conectar"
        : !state.verified
          ? "Sin verificar"
          : !state.enabled
            ? "Pausado"
            : "Conectado";
  return (
    <section
      className="voice-workspace"
      aria-label="Voz con Retell AI"
      aria-busy={loading || busy}
    >
      <div className="voice-toolbar">
        <div className="voice-provider">
          <span className="voice-provider-mark" aria-hidden="true">
            R
          </span>
          <div>
            <strong>Retell AI</strong>
            <span className="voice-muted" role="status">
              {status}
            </span>
          </div>
        </div>
        <div className="voice-actions">
          <button
            className="crm-button crm-secondary"
            disabled={loading || busy || approvalBusy}
            onClick={() => void load()}
          >
            Sincronizar
          </button>
          <button
            className="crm-button crm-secondary"
            disabled={approvalBusy}
            onClick={onOpenConnection}
          >
            Configurar conexión
          </button>
        </div>
      </div>
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      <div className="voice-navigation">
        <nav aria-label="Herramientas de voz">
          {sections.slice(0, 6).map((item) => (
            <button
              key={item.key}
              className={sectionKey === item.key ? "is-selected" : ""}
              aria-current={sectionKey === item.key ? "page" : undefined}
              onClick={() => {
                setSectionKey(item.key);
                setQuery("");
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <label className="voice-more">
          <span className="sr-only">Más herramientas de Retell</span>
          <select
            value={
              sections.slice(0, 6).some((s) => s.key === sectionKey)
                ? ""
                : sectionKey
            }
            onChange={(event) => {
              if (event.target.value) {
                setSectionKey(event.target.value);
                setQuery("");
              }
            }}
          >
            <option value="">Más herramientas</option>
            {sections.slice(6).map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
            <option value="all">Todas las funciones</option>
          </select>
        </label>
      </div>
      {sectionKey === "all" ? (
        active && (
          <RetellPanel
            request={request}
            active={active}
            onChanged={changed}
            operationsOnly
            friendly
            onResult={confirmed}
          />
        )
      ) : (
        <>
          <div className="voice-section-heading">
            <div>
              <h2>{section.label}</h2>
              <p className="voice-muted">
                {last
                  ? `Sincronizado · ${new Date(last).toLocaleString("es-CO")}`
                  : "Sincronización automática"}
              </p>
            </div>
            <div className="voice-actions">
              {section.create && (
                <button
                  className="crm-button"
                  disabled={
                    !enabled || busy || !operation(section.create)?.available
                  }
                  onClick={() =>
                    sectionKey === "agents"
                      ? void editor("agent")
                      : sectionKey === "models"
                        ? void editor("instructions")
                        : openOperation(section.create!)
                  }
                >
                  {sectionKey === "agents"
                    ? "Nuevo agente"
                    : sectionKey === "models"
                      ? "Nuevas instrucciones"
                      : "Crear"}
                </button>
              )}
            </div>
          </div>
          {resourceErrors.includes(section.list) && (
            <p className="crm-error" role="alert">
              No se pudo sincronizar esta sección. Las demás siguen disponibles.{" "}
              <button
                type="button"
                className="crm-button crm-secondary"
                disabled={loading || busy}
                onClick={() => void load()}
              >
                Reintentar
              </button>
            </p>
          )}
          <div className="voice-search">
            <label htmlFor="voice-resource-search" className="sr-only">
              Buscar en {section.label}
            </label>
            <input
              id="voice-resource-search"
              type="search"
              placeholder={`Buscar en ${section.label.toLocaleLowerCase("es")}…`}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <span className="voice-muted">
              {filtered.length} en esta lectura
            </span>
          </div>
          {!loading && !enabled && (
            <div className="voice-empty">
              <h3>
                {state?.configured
                  ? "Revisa las funciones de tu conexión."
                  : "Conecta tu espacio de voz."}
              </h3>
              <p>
                Revisa o activa Retell en Conexiones para trabajar con tus
                recursos.
              </p>
              <button className="crm-button" onClick={onOpenConnection}>
                Ir a Conexiones
              </button>
            </div>
          )}
          {loading ? (
            <p role="status" className="voice-empty">
              Cargando el espacio de voz…
            </p>
          ) : enabled && !filtered.length ? (
            <div className="voice-empty">
              <h3>
                {query
                  ? "No encontramos coincidencias."
                  : resourceErrors.includes(section.list)
                    ? "Sincronización pendiente."
                    : "Todavía no hay registros."}
              </h3>
              <p>
                {query
                  ? "Prueba con otro nombre o identificador."
                  : resourceErrors.includes(section.list)
                    ? "Puedes reintentar la consulta sin afectar tu configuración."
                    : "Los recursos de Retell aparecen aquí automáticamente."}
              </p>
            </div>
          ) : (
            <div className="voice-resource-list">
              {filtered.map((row) => (
                <article key={text(row[section.id])} className="voice-resource">
                  <div className="voice-resource-title">
                    <span className="voice-resource-symbol" aria-hidden="true">
                      {section.label.slice(0, 1)}
                    </span>
                    <div>
                      <h3>
                        {text(row[section.name]) || text(row[section.id])}
                      </h3>
                      <details className="voice-resource-id">
                        <summary>Identificador</summary>
                        <code>{text(row[section.id])}</code>
                      </details>
                    </div>
                  </div>
                  {sectionKey === "agents" && (
                    <p className="voice-muted">
                      Voz:{" "}
                      {text(
                        voices.find((voice) => voice.voice_id === row.voice_id)
                          ?.voice_name,
                      ) || (row.voice_id ? "Configurada" : "Sin dato")}{" "}
                      · Versión: {text(row.version) || "Sin dato"}
                    </p>
                  )}
                  {sectionKey === "voices" && (
                    <p className="voice-muted">
                      {[text(row.provider), text(row.accent), text(row.gender)]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  )}
                  <div className="voice-actions">
                    {sectionKey === "agents" && (
                      <button
                        className="crm-button crm-secondary"
                        disabled={!enabled || busy}
                        onClick={() => void editor("agent", row)}
                      >
                        Editar agente
                      </button>
                    )}
                    {sectionKey === "agents" && (
                      <button
                        className="crm-button crm-secondary"
                        disabled={
                          !enabled ||
                          busy ||
                          !operation("getAgent")?.available ||
                          !operation("getRetellLLM")?.available
                        }
                        onClick={() => void editor("instructions", row, true)}
                      >
                        Prompt del agente
                      </button>
                    )}
                    {sectionKey === "models" && (
                      <button
                        className="crm-button crm-secondary"
                        disabled={!enabled || busy}
                        onClick={() => void editor("instructions", row)}
                      >
                        Editar instrucciones
                      </button>
                    )}
                    {section.actions
                      .filter(([endpoint]) => operation(endpoint))
                      .map(([endpoint, label]) => (
                        <button
                          key={endpoint}
                          className="crm-button crm-secondary"
                          disabled={
                            !enabled || busy || !operation(endpoint)?.available
                          }
                          onClick={() =>
                            openOperation(
                              endpoint,
                              resourceSeed(endpoint, row, section),
                            )
                          }
                        >
                          {label}
                        </button>
                      ))}
                  </div>
                </article>
              ))}
            </div>
          )}
          <p className="voice-footnote">
            Sincronización automática con vistas limitadas. Más herramientas
            reúne las opciones avanzadas.
          </p>
          <button
            className="voice-catalog-link"
            onClick={() => setSectionKey("all")}
          >
            Explorar todas las funciones de Retell ↗
          </button>
        </>
      )}
      <dialog
        ref={dialog}
        className={
          modal?.kind === "studio"
            ? "voice-dialog voice-studio-dialog"
            : "voice-dialog"
        }
        aria-labelledby="voice-dialog-title"
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <header
          className="voice-dialog-heading"
          hidden={modal?.kind === "studio"}
        >
          <h2 id="voice-dialog-title">
            {modal?.kind === "studio"
              ? "Editor del agente"
              : modal?.kind === "review"
                ? "Revisar acción"
                : modal?.kind === "operation"
                  ? "Función de Retell"
                  : modal?.kind === "details"
                    ? "Detalle de Retell"
                    : modal?.kind === "instructions"
                      ? "Prompt e instrucciones"
                      : "Configuración del agente"}
          </h2>
          <button
            type="button"
            className="crm-button crm-secondary"
            disabled={busy || approvalBusy}
            onClick={close}
            aria-label="Cerrar panel de voz"
          >
            Cerrar
          </button>
        </header>
        <div className="voice-dialog-body">
          {active && modal?.kind === "studio" && state && (
            <VoiceAgentStudio
              key={modal.generation}
              agent={modal.agent}
              instructions={modal.instructions}
              warning={modal.warning}
              schemas={schemas}
              voices={voices}
              models={models}
              revision={state.revision}
              available={(catalog?.operations ?? [])
                .filter((item) => item.available)
                .map((item) => item.endpoint)}
              request={request}
              busy={busy || approvalBusy}
              onPendingChange={studioPending}
              onClose={close}
              onReload={() => void agentStudio(modal.agent.data)}
              onChanged={changed}
              onResult={confirmed}
            />
          )}
          {active && modal?.kind === "details" && (
            <ActionResultDetails
              result={modal.result}
              request={request}
              presentation="friendly"
            />
          )}
          {active && modal?.kind === "operation" && (
            <RetellPanel
              key={modal.endpoint}
              request={request}
              active
              onChanged={changed}
              operationsOnly
              friendly
              initialOperation={{
                endpoint: modal.endpoint,
                arguments: modal.arguments,
              }}
              onResult={confirmed}
            />
          )}
          {active &&
            (modal?.kind === "agent" || modal?.kind === "instructions") && (
              <VoiceAgentEditor
                key={`${modal.kind}:${text(modal.record?.agent_id) || text(modal.record?.llm_id) || "new"}:${text(modal.record?.version)}`}
                kind={modal.kind}
                record={modal.record}
                completeFields={modal.completeFields}
                blockedFields={modal.blockedFields}
                schemas={schemas}
                voices={voices}
                models={models}
                busy={busy || approvalBusy}
                onSubmit={async (endpoint, args) => {
                  if (lock.current)
                    throw new Error("Hay una solicitud en curso.");
                  lock.current = true;
                  setBusy(true);
                  try {
                    await prepare(endpoint, args);
                  } finally {
                    lock.current = false;
                    if (alive.current) setBusy(false);
                  }
                }}
                onCancel={close}
                onCreateModel={() => void editor("instructions")}
              />
            )}
          {active && modal?.kind === "review" && (
            <ActionOutput
              value={modal.output}
              presentation="friendly"
              request={request}
              onChanged={changed}
              onResult={confirmed}
            />
          )}
        </div>
      </dialog>
    </section>
  );
}
