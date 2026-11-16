"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./icon";
import { WorkflowCanvas } from "./workflow-canvas";
export { WorkflowCanvas };
import { kindIcons } from "./workflow-node-presentation";
import {
  phoneLabel,
  sourceLabel,
  sources,
  stages,
  type Contact,
} from "./types";
import {
  canActivate,
  channelBindingKey,
  connectionOptions,
  dayLabels,
  graphIssues,
  initialDocument,
  insertNode,
  layoutDocument,
  nodeLabels,
  multichannelPrepareArguments,
  removeNode,
  runLabels,
  workflowError,
  type ConversationBinding,
  type NodeKind,
  type RetellOptions,
  type RunDetail,
  type RunReview,
  type Workflow,
  type WorkflowCatalog,
  type WorkflowDocument,
  type WorkflowNode,
  type WorkflowRun,
  type ZernioOptions,
} from "./workflow-types";
import "./workflows.css";

type Tab = "builder" | "schedule" | "history";
type Request = <T>(
  path: string,
  method?: string,
  payload?: unknown,
) => Promise<T>;
const tabs: [Tab, string][] = [
  ["builder", "Constructor"],
  ["schedule", "Programación"],
  ["history", "Clientes e historial"],
];
const emptyZernio: ZernioOptions = {
  available: false,
  accounts: [],
  templates: [],
  conversations: [],
};
const emptyRetell: RetellOptions = {
  available: false,
  agents: [],
  numbers: [],
};
const formatDate = (value?: string) =>
  value
    ? new Intl.DateTimeFormat("es-CO", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "America/Bogota",
      }).format(new Date(value))
    : "Sin fecha confirmada";
const signature = (
  name: string,
  description: string,
  document: WorkflowDocument,
) => JSON.stringify({ name, description, document });

export function WorkflowPanel({
  csrf,
  contacts,
  onOpenConnections,
  onDirtyChange,
}: {
  csrf: string;
  contacts: Contact[];
  onOpenConnections: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [catalog, setCatalog] = useState<WorkflowCatalog | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [name, setName] = useState("Nueva secuencia");
  const [description, setDescription] = useState("");
  const [document, setDocument] = useState<WorkflowDocument>(initialDocument);
  const [baseline, setBaseline] = useState(() =>
    signature("Nueva secuencia", "", initialDocument()),
  );
  const [selectedNodeId, setSelectedNodeId] = useState("end");
  const [tab, setTab] = useState<Tab>("builder");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [audience, setAudience] = useState<string[]>([]);
  const [bindings, setBindings] = useState<Record<string, ConversationBinding>>(
    {},
  );
  const [contactQuery, setContactQuery] = useState("");
  const [audienceConsent, setAudienceConsent] = useState(false);
  const [review, setReview] = useState<RunReview | null>(null);
  const [approvalConsent, setApprovalConsent] = useState(false);
  const [activationUncertain, setActivationUncertain] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [zernio, setZernio] = useState<ZernioOptions>(emptyZernio);
  const [zernioAccounts, setZernioAccounts] = useState<
    ZernioOptions["accounts"]
  >([]);
  const [zernioAccountId, setZernioAccountId] = useState("");
  const [channelConversations, setChannelConversations] = useState<
    Record<string, ZernioOptions["conversations"]>
  >({});
  const [retell, setRetell] = useState<RetellOptions>(emptyRetell);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [stepQuery, setStepQuery] = useState("");
  const [wideCanvas, setWideCanvas] = useState(false);
  const paletteTrigger = useRef<HTMLButtonElement>(null);
  const stepSearch = useRef<HTMLInputElement>(null);
  const stepName = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (inspectorOpen) stepName.current?.focus({ preventScroll: true });
  }, [inspectorOpen, selectedNodeId]);
  useEffect(() => {
    if (paletteOpen) stepSearch.current?.focus();
  }, [paletteOpen]);
  function selectStep(id: string) {
    setSelectedNodeId(id);
    setInspectorOpen(true);
    setPaletteOpen(false);
  }
  const busy = useRef(false),
    optionsBusy = useRef(false),
    reviewDialog = useRef<HTMLDialogElement>(null),
    reviewTrigger = useRef<HTMLButtonElement>(null);
  const detailGeneration = useRef(0);
  const dirty = signature(name, description, document) !== baseline;
  const issues = useMemo(() => graphIssues(document), [document]);
  const selectedNode = document.nodes.find(
    (node) => node.id === selectedNodeId,
  );
  const socialNodes = document.nodes.filter(
    (node) => node.kind === "social_message",
  );
  const filteredContacts = contacts.filter((contact) =>
    `${contact.name} ${contact.phone} ${sourceLabel(contact.source)}`
      .toLocaleLowerCase("es")
      .includes(contactQuery.toLocaleLowerCase("es")),
  );
  const socialAccountIds = [
    ...new Set(
      socialNodes.map((node) => String(node.settings.account_id ?? "")),
    ),
  ];
  const missingBinding =
    socialNodes.length > 0 &&
    audience.some((id) =>
      socialAccountIds.some(
        (accountId) =>
          !accountId ||
          !bindings[channelBindingKey(id, accountId)]?.conversation_id,
      ),
    );
  const externalActions =
    document.nodes.filter((node) =>
      ["social_message", "whatsapp_template", "retell_call"].includes(
        node.kind,
      ),
    ).length * audience.length;
  const reviewBudgetExceeded = externalActions > 10;
  const callRouteBlocked =
    document.nodes.some((node) => node.kind === "retell_call") &&
    audience.some((id) =>
      contacts.find((person) => person.id === id)?.phone.startsWith("+57"),
    );
  const canPrepare = Boolean(
    workflowId &&
    !dirty &&
    !conflict &&
    audience.length &&
    audienceConsent &&
    !missingBinding &&
    !reviewBudgetExceeded &&
    !callRouteBlocked &&
    !issues.length &&
    !pending,
  );
  const workerReady = Boolean(
    catalog?.worker.enabled && catalog.worker.available,
  );
  const request: Request = useCallback(
    async <T,>(path: string, method = "GET", payload?: unknown): Promise<T> => {
      const response = await fetch(`/api/crm/workflows/${path}`, {
        method,
        cache: "no-store",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: method === "GET" ? undefined : JSON.stringify(payload ?? {}),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        const code = result?.detail;
        if (
          response.status === 409 &&
          path.startsWith("definitions/") &&
          (code === "record_changed" || code === "workflow_version_conflict")
        )
          setConflict(true);
        throw new Error(workflowError(code));
      }
      return result as T;
    },
    [csrf],
  );
  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      request<WorkflowCatalog>("catalog"),
      request<{ workflows: Workflow[] }>("definitions"),
      request<{ runs: WorkflowRun[] }>("runs"),
    ])
      .then(([nextCatalog, definitions, history]) => {
        if (!active) return;
        setCatalog(nextCatalog);
        setWorkflows(definitions.workflows);
        setRuns(history.runs);
        if (definitions.workflows[0]) {
          const item = definitions.workflows[0];
          setWorkflowId(item.id);
          setVersion(item.version);
          setName(item.name);
          setDescription(item.description);
          setDocument(item.document);
          setSelectedNodeId(item.document.entry_id);
          setBaseline(signature(item.name, item.description, item.document));
        }
      })
      .catch((cause) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [request]);
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  useEffect(() => {
    if (!review) return;
    const dialog = reviewDialog.current;
    dialog?.showModal();
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(timer);
      dialog?.close();
    };
  }, [review]);
  function invalidateReview() {
    setReview(null);
    setApprovalConsent(false);
    setAudienceConsent(false);
  }
  function changeDocument(next: WorkflowDocument) {
    setDocument(next);
    invalidateReview();
    setNotice("");
  }
  function updateNode(patch: Partial<WorkflowNode>) {
    setDocument((previous) => ({
      ...previous,
      nodes: previous.nodes.map((node) =>
        node.id === selectedNodeId ? { ...node, ...patch } : node,
      ),
    }));
    invalidateReview();
    setNotice("");
  }
  function updateSetting(
    key: string,
    value: string | number | boolean | string[],
  ) {
    setDocument((previous) => ({
      ...previous,
      nodes: previous.nodes.map((node) =>
        node.id === selectedNodeId
          ? { ...node, settings: { ...node.settings, [key]: value } }
          : node,
      ),
    }));
    invalidateReview();
    setNotice("");
  }
  function selectWorkflow(id: string) {
    if (
      dirty &&
      !window.confirm(
        "Hay cambios sin guardar. ¿Descartarlos y abrir otra secuencia?",
      )
    )
      return;
    const item = workflows.find((flow) => flow.id === id);
    const nextDocument = item?.document ?? initialDocument();
    const nextName = item?.name ?? "Nueva secuencia",
      nextDescription = item?.description ?? "";
    setWorkflowId(item?.id ?? null);
    setVersion(item?.version ?? 0);
    setName(nextName);
    setDescription(nextDescription);
    setDocument(nextDocument);
    setBaseline(signature(nextName, nextDescription, nextDocument));
    setSelectedNodeId(nextDocument.entry_id);
    setInspectorOpen(false);
    setPaletteOpen(false);
    setConflict(false);
    setError("");
    setNotice("");
    setAudience([]);
    setBindings({});
    invalidateReview();
    setDetail(null);
  }
  async function action(operation: () => Promise<void>) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : workflowError(null));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  async function save() {
    await action(async () => {
      const saved = await request<Workflow>(
        workflowId
          ? `definitions/${encodeURIComponent(workflowId)}`
          : "definitions",
        workflowId ? "PATCH" : "POST",
        {
          ...(workflowId ? { version } : {}),
          name: name.trim(),
          description,
          document,
        },
      );
      setWorkflows((previous) => [
        saved,
        ...previous.filter((item) => item.id !== saved.id),
      ]);
      setWorkflowId(saved.id);
      setVersion(saved.version);
      setName(saved.name);
      setDescription(saved.description);
      setDocument(saved.document);
      setBaseline(signature(saved.name, saved.description, saved.document));
      setConflict(false);
      setNotice(
        "Borrador guardado. No se enviará ningún mensaje ni se iniciará una llamada.",
      );
    });
  }
  async function reloadSaved() {
    await action(async () => {
      const result = await request<{ workflows: Workflow[] }>("definitions");
      setWorkflows(result.workflows);
      const saved = result.workflows.find((item) => item.id === workflowId);
      if (
        saved &&
        window.confirm(
          "¿Reemplazar tu borrador local por la versión guardada? Esta acción descarta los cambios sin guardar.",
        )
      ) {
        setVersion(saved.version);
        setName(saved.name);
        setDescription(saved.description);
        setDocument(saved.document);
        setBaseline(signature(saved.name, saved.description, saved.document));
        setSelectedNodeId(saved.document.entry_id);
        setConflict(false);
        invalidateReview();
      }
    });
  }
  async function refreshHistory() {
    await action(async () => {
      const [result, nextCatalog] = await Promise.all([
        request<{ runs: WorkflowRun[] }>("runs"),
        request<WorkflowCatalog>("catalog"),
      ]);
      setRuns(result.runs);
      setCatalog(nextCatalog);
      setNotice("Historial y disponibilidad actualizados.");
      if (detail)
        setDetail(
          await request<RunDetail>(`runs/${encodeURIComponent(detail.run.id)}`),
        );
    });
  }
  async function prepare() {
    await action(async () => {
      if (!canPrepare || !workflowId) return;
      const result = await request<RunReview>(
        `definitions/${encodeURIComponent(workflowId)}/prepare`,
        "POST",
        multichannelPrepareArguments(
          version,
          audience,
          bindings,
          audienceConsent,
          socialAccountIds,
        ),
      );
      setReview(result);
      setApprovalConsent(false);
      setActivationUncertain(false);
      setRuns((previous) => [
        result.run,
        ...previous.filter((item) => item.id !== result.run.id),
      ]);
    });
  }
  async function activate() {
    await action(async () => {
      if (
        !canActivate(
          review,
          catalog?.worker,
          dirty,
          approvalConsent,
          Date.now(),
        ) ||
        activationUncertain ||
        !review
      )
        return;
      try {
        const run = await request<WorkflowRun>(
          `runs/${encodeURIComponent(review.run.id)}/activate`,
          "POST",
          {
            fingerprint: review.fingerprint,
            consent_confirmed: approvalConsent,
          },
        );
        setRuns((previous) => [
          run,
          ...previous.filter((item) => item.id !== run.id),
        ]);
        setReview(null);
        setTab("history");
        setNotice(
          `Activación confirmada: ${runLabels[run.status]}. Consulta los eventos para conocer los resultados.`,
        );
      } catch (cause) {
        setActivationUncertain(true);
        throw cause;
      }
    });
  }
  async function loadDetail(id: string) {
    if (busy.current) return;
    const generation = ++detailGeneration.current;
    setDetailLoading(true);
    setError("");
    setDetail(null);
    try {
      const result = await request<RunDetail>(`runs/${encodeURIComponent(id)}`);
      if (generation === detailGeneration.current) setDetail(result);
    } catch (cause) {
      if (generation === detailGeneration.current)
        setError(cause instanceof Error ? cause.message : workflowError(null));
    } finally {
      if (generation === detailGeneration.current) setDetailLoading(false);
    }
  }
  async function control(
    run: WorkflowRun,
    command: "pause" | "resume" | "stop",
  ) {
    if (
      command === "stop" &&
      !window.confirm(
        "¿Detener esta ejecución? No se reanudarán sus pasos pendientes. Las acciones ya confirmadas no se deshacen.",
      )
    )
      return;
    await action(async () => {
      const result = await request<WorkflowRun>(
        `runs/${encodeURIComponent(run.id)}/${command}`,
        "POST",
        { version: run.version },
      );
      setRuns((previous) =>
        previous.map((item) => (item.id === result.id ? result : item)),
      );
      if (detail?.run.id === result.id) setDetail({ ...detail, run: result });
      setNotice(
        `${runLabels[result.status]}. Una acción ya en curso puede terminar; no se repite por este control.`,
      );
    });
  }
  async function loadOptions(provider: "zernio" | "retell", accountId = "") {
    if (optionsBusy.current || busy.current) return;
    optionsBusy.current = true;
    setOptionsLoading(true);
    setError("");
    try {
      if (provider === "zernio") {
        const result = await request<ZernioOptions>("options", "POST", {
          provider,
          ...(accountId ? { account_id: accountId } : {}),
        });
        setZernio(result);
        setZernioAccountId(accountId);
        setZernioAccounts(result.accounts);
        if (accountId)
          setChannelConversations((previous) => ({
            ...previous,
            [accountId]: result.available ? result.conversations : [],
          }));
      } else
        setRetell(
          await request<RetellOptions>("options", "POST", { provider }),
        );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : workflowError(null));
      if (provider === "zernio") {
        setZernio(emptyZernio);
        setZernioAccountId("");
      } else setRetell(emptyRetell);
    } finally {
      optionsBusy.current = false;
      setOptionsLoading(false);
    }
  }
  function addStep(kind: NodeKind) {
    try {
      const id = crypto.randomUUID();
      changeDocument(insertNode(document, kind, id));
      selectStep(id);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }
  function toggleContact(id: string) {
    if (!audience.includes(id) && audience.length >= 50) {
      setError("Cada ejecución admite hasta 50 clientes.");
      return;
    }
    setAudience((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : [...previous, id],
    );
    invalidateReview();
  }
  function closeReview() {
    setReview(null);
    setApprovalConsent(false);
    requestAnimationFrame(() => reviewTrigger.current?.focus());
  }

  return (
    <section
      className="workflow-workspace"
      aria-label="Secuencias comerciales"
      aria-busy={loading || pending}
    >
      <div className="workflow-toolbar">
        <label className="workflow-picker">
          Secuencia
          <select
            aria-label="Abrir secuencia"
            value={workflowId ?? ""}
            onChange={(event) => selectWorkflow(event.target.value)}
            disabled={pending || loading}
          >
            <option value="">Nueva secuencia</option>
            {workflows.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · v{item.version}
              </option>
            ))}
          </select>
        </label>
        <div className="workflow-toolbar-actions">
          <span className="workflow-save-label">
            {workflowId ? `Versión ${version}` : "Sin guardar"}
            {dirty ? " · Cambios sin guardar" : workflowId ? " · Guardado" : ""}
          </span>
          <button
            className="crm-button crm-secondary"
            disabled={pending || loading}
            onClick={() => selectWorkflow("")}
          >
            <Icon name="plus" />
            Nueva
          </button>
          <button
            className="crm-button"
            disabled={
              pending ||
              loading ||
              !name.trim() ||
              Boolean(issues.length) ||
              conflict ||
              (Boolean(workflowId) && !dirty)
            }
            onClick={() => void save()}
          >
            <Icon name="check" />
            Guardar borrador
          </button>
        </div>
      </div>
      <div
        className={`workflow-worker ${workerReady ? "is-ready" : "is-held"}`}
      >
        <Icon name={workerReady ? "check" : "history"} />
        <div>
          <strong>
            {loading
              ? "Consultando ejecutor…"
              : workerReady
                ? "Ejecución automática disponible"
                : catalog?.worker.enabled
                  ? "Ejecutor no disponible"
                  : "Ejecución automática deshabilitada"}
          </strong>
          <details className="workflow-worker-details">
            <summary>Detalles</summary>
            <p>
              {workerReady
                ? "Solo se ejecuta la audiencia y la versión que apruebes. No se inscriben clientes nuevos automáticamente."
                : "Puedes guardar borradores. La activación está bloqueada hasta confirmar un ejecutor disponible."}
            </p>
          </details>
        </div>
        <button
          className="workflow-text-button"
          disabled={pending}
          onClick={() => void refreshHistory()}
        >
          Actualizar estado
        </button>
      </div>
      {error ? (
        <p className="workflow-error" role="alert">
          {error}
        </p>
      ) : null}
      {conflict ? (
        <div className="workflow-warning">
          <p>
            El servidor conserva una versión distinta. Tu borrador local no se
            sobrescribió.
          </p>
          <button
            className="crm-button crm-secondary"
            disabled={pending}
            onClick={() => void reloadSaved()}
          >
            Recargar versión guardada
          </button>
        </div>
      ) : null}
      <p className="workflow-notice" role="status" aria-live="polite">
        {pending ? "Procesando solicitud…" : notice}
      </p>
      {loading ? (
        <p className="workflow-empty">
          Cargando borradores, conexiones e historial…
        </p>
      ) : (
        <>
          <div
            className="workflow-tabs"
            role="tablist"
            aria-label="Vista de secuencias"
          >
            {tabs.map(([key, label]) => (
              <button
                key={key}
                role="tab"
                id={`workflow-tab-${key}`}
                aria-controls={`workflow-panel-${key}`}
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                onKeyDown={(event) => {
                  const index = tabs.findIndex(([value]) => value === tab);
                  const next =
                    event.key === "ArrowRight"
                      ? tabs[(index + 1) % tabs.length][0]
                      : event.key === "ArrowLeft"
                        ? tabs[(index + tabs.length - 1) % tabs.length][0]
                        : event.key === "Home"
                          ? tabs[0][0]
                          : event.key === "End"
                            ? tabs[tabs.length - 1][0]
                            : null;
                  if (next) {
                    event.preventDefault();
                    setTab(next);
                    event.currentTarget.parentElement
                      ?.querySelector<HTMLButtonElement>(
                        `#workflow-tab-${next}`,
                      )
                      ?.focus();
                  }
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            role="tabpanel"
            id={`workflow-panel-${tab}`}
            aria-labelledby={`workflow-tab-${tab}`}
          >
            {tab === "builder" ? (
              <>
                <details className="workflow-properties">
                  <summary>
                    <Icon name="edit" size={16} />
                    {name || "Nueva secuencia"}
                    <span>Editar nombre y objetivo</span>
                  </summary>
                  <div className="workflow-definition">
                    <label>
                      Nombre de la secuencia
                      <input
                        maxLength={120}
                        value={name}
                        disabled={pending}
                        onChange={(event) => {
                          setName(event.target.value);
                          invalidateReview();
                        }}
                      />
                    </label>
                    <label>
                      Objetivo interno <span>(opcional)</span>
                      <input
                        maxLength={1000}
                        value={description}
                        disabled={pending}
                        placeholder="¿Qué seguimiento quieres organizar?"
                        onChange={(event) => {
                          setDescription(event.target.value);
                          invalidateReview();
                        }}
                      />
                    </label>
                  </div>
                </details>
                <div
                  className={`workflow-editor ${paletteOpen ? "has-palette" : ""} ${inspectorOpen ? "has-inspector" : ""} ${wideCanvas ? "is-wide" : ""}`}
                >
                  <aside
                    className="workflow-palette"
                    aria-label="Pasos disponibles"
                    hidden={!paletteOpen}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        setPaletteOpen(false);
                        paletteTrigger.current?.focus();
                      }
                    }}
                  >
                    <div className="workflow-panel-heading">
                      <h2>Agregar paso</h2>
                      <button
                        className="workflow-icon-button"
                        aria-label="Cerrar pasos disponibles"
                        onClick={() => {
                          setPaletteOpen(false);
                          paletteTrigger.current?.focus();
                        }}
                      >
                        <Icon name="close" />
                      </button>
                    </div>
                    <label className="workflow-step-search">
                      <Icon name="search" size={16} />
                      <input
                        ref={stepSearch}
                        aria-label="Buscar paso"
                        placeholder="Buscar paso…"
                        value={stepQuery}
                        onChange={(event) => setStepQuery(event.target.value)}
                      />
                    </label>
                    {catalog?.nodes.length ? (
                      catalog.nodes
                        .filter(
                          (item) =>
                            item.kind !== "end" &&
                            nodeLabels[item.kind]
                              .toLocaleLowerCase("es")
                              .includes(stepQuery.toLocaleLowerCase("es")),
                        )
                        .map((item) => (
                          <div key={item.kind}>
                            <button
                              className="workflow-palette-step"
                              disabled={
                                pending ||
                                !item.available ||
                                document.nodes.length >= 20
                              }
                              onClick={() => addStep(item.kind)}
                              title={item.reason}
                            >
                              <Icon name={kindIcons[item.kind]} />
                              <span>
                                {nodeLabels[item.kind]}
                                {!item.available ? (
                                  <small>No disponible</small>
                                ) : null}
                              </span>
                              <Icon name="plus" size={14} />
                            </button>
                          </div>
                        ))
                    ) : (
                      <p>
                        No hay un catálogo disponible. Actualiza el estado antes
                        de agregar acciones.
                      </p>
                    )}
                    {catalog?.nodes.length &&
                    !catalog.nodes.some(
                      (item) =>
                        item.kind !== "end" &&
                        nodeLabels[item.kind]
                          .toLocaleLowerCase("es")
                          .includes(stepQuery.toLocaleLowerCase("es")),
                    ) ? (
                      <p role="status">No hay pasos con ese nombre.</p>
                    ) : null}
                    <div className="workflow-palette-footer">
                      <strong>{document.nodes.length} de 20 pasos</strong>
                      <button
                        className="workflow-text-button"
                        onClick={onOpenConnections}
                      >
                        Revisar conexiones
                      </button>
                    </div>
                  </aside>
                  <div className="workflow-canvas-column">
                    <div className="workflow-canvas-toolbar">
                      <button
                        ref={paletteTrigger}
                        className="crm-button workflow-add-step"
                        aria-expanded={paletteOpen}
                        disabled={pending}
                        onClick={() => {
                          setPaletteOpen(!paletteOpen);
                          setInspectorOpen(false);
                          setStepQuery("");
                        }}
                      >
                        <Icon name="plus" size={16} />
                        Agregar paso
                      </button>
                      <div className="workflow-canvas-actions">
                        <span className="workflow-step-count">
                          {document.nodes.length}/20 pasos
                        </span>
                        <button
                          className="workflow-text-button"
                          disabled={pending}
                          onClick={() =>
                            changeDocument(layoutDocument(document))
                          }
                        >
                          Ordenar
                        </button>
                        <button
                          className="workflow-icon-button"
                          aria-label={
                            wideCanvas ? "Reducir lienzo" : "Ampliar lienzo"
                          }
                          aria-pressed={wideCanvas}
                          onClick={() => {
                            setWideCanvas(!wideCanvas);
                            setPaletteOpen(false);
                            setInspectorOpen(false);
                          }}
                        >
                          <Icon name={wideCanvas ? "close" : "arrow"} />
                        </button>
                      </div>
                    </div>
                    <WorkflowCanvas
                      key={workflowId ?? "new"}
                      document={document}
                      selected={selectedNodeId}
                      onSelect={selectStep}
                      disabled={pending}
                      onMove={(id, position) =>
                        changeDocument({
                          ...document,
                          nodes: document.nodes.map((node) =>
                            node.id === id ? { ...node, position } : node,
                          ),
                        })
                      }
                    />
                    <details className="workflow-step-list">
                      <summary>Lista de pasos</summary>
                      <ol aria-label="Lista de pasos">
                        {document.nodes.map((node) => (
                          <li key={node.id}>
                            <button
                              aria-pressed={selectedNodeId === node.id}
                              onClick={() => selectStep(node.id)}
                            >
                              {node.label}
                              {node.id === document.entry_id ? " · Inicio" : ""}
                            </button>
                            <span>
                              {node.kind === "condition"
                                ? `Si coincide: ${document.nodes.find((n) => n.id === node.on_true)?.label ?? "Sin conectar"} · Si no coincide: ${document.nodes.find((n) => n.id === node.on_false)?.label ?? "Sin conectar"}`
                                : node.next_id
                                  ? `Siguiente: ${document.nodes.find((n) => n.id === node.next_id)?.label ?? "Sin conectar"}`
                                  : "Fin"}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </details>
                  </div>
                  <aside
                    className="workflow-inspector"
                    aria-label="Inspector del paso seleccionado"
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        setInspectorOpen(false);
                        paletteTrigger.current?.focus();
                      }
                    }}
                    hidden={!inspectorOpen}
                  >
                    <div className="workflow-panel-heading">
                      <h2>Configurar paso</h2>
                      <button
                        className="workflow-icon-button"
                        aria-label="Cerrar configuración del paso"
                        onClick={() => {
                          setInspectorOpen(false);
                          paletteTrigger.current?.focus();
                        }}
                      >
                        <Icon name="close" />
                      </button>
                    </div>
                    {selectedNode ? (
                      <fieldset disabled={pending}>
                        <div className="workflow-section-title">
                          <h2>
                            <Icon name={kindIcons[selectedNode.kind]} />
                            {nodeLabels[selectedNode.kind]}
                          </h2>
                        </div>
                        <label>
                          Nombre del paso
                          <input
                            maxLength={120}
                            ref={stepName}
                            value={selectedNode.label}
                            onChange={(event) =>
                              updateNode({ label: event.target.value })
                            }
                          />
                        </label>
                        <NodeSettings
                          node={selectedNode}
                          onChange={updateSetting}
                          zernio={zernio}
                          accounts={zernioAccounts}
                          zernioAccountId={zernioAccountId}
                          retell={retell}
                          optionsLoading={optionsLoading}
                          loadOptions={loadOptions}
                        />
                        <details className="workflow-connections">
                          <summary>Conexiones avanzadas</summary>
                          <label>
                            Inicio de la secuencia
                            <select
                              value={document.entry_id}
                              onChange={(event) =>
                                changeDocument({
                                  ...document,
                                  entry_id: event.target.value,
                                })
                              }
                            >
                              {document.nodes.map((node) => (
                                <option value={node.id} key={node.id}>
                                  {node.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          {selectedNode.kind === "condition" ? (
                            <>
                              {(
                                [
                                  ["on_true", "Si coincide"],
                                  ["on_false", "Si no coincide"],
                                ] as const
                              ).map(([key, label]) => (
                                <label key={key}>
                                  {label}
                                  <select
                                    value={selectedNode[key] ?? ""}
                                    onChange={(event) =>
                                      updateNode({
                                        [key]: event.target.value || null,
                                      })
                                    }
                                  >
                                    <option value="">Sin conectar</option>
                                    {connectionOptions(
                                      document,
                                      selectedNode.id,
                                    ).map((node) => (
                                      <option key={node.id} value={node.id}>
                                        {node.label}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              ))}
                              <p>
                                Si el CRM no tiene el dato requerido, el cliente
                                queda en espera; no se toma la salida «no
                                coincide».
                              </p>
                            </>
                          ) : selectedNode.kind !== "end" ? (
                            <label>
                              Siguiente paso
                              <select
                                value={selectedNode.next_id ?? ""}
                                onChange={(event) =>
                                  updateNode({
                                    next_id: event.target.value || null,
                                  })
                                }
                              >
                                <option value="">Sin conectar</option>
                                {connectionOptions(
                                  document,
                                  selectedNode.id,
                                ).map((node) => (
                                  <option key={node.id} value={node.id}>
                                    {node.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                          ) : (
                            <p>Este paso finaliza la ejecución del cliente.</p>
                          )}
                        </details>
                        {selectedNode.kind !== "end" ? (
                          <button
                            className="workflow-delete"
                            onClick={() => {
                              changeDocument(
                                removeNode(document, selectedNode.id),
                              );
                              setSelectedNodeId(
                                document.nodes.find(
                                  (node) => node.kind === "end",
                                )?.id ?? "",
                              );
                            }}
                          >
                            <Icon name="trash" size={16} />
                            Eliminar paso
                          </button>
                        ) : null}
                      </fieldset>
                    ) : (
                      <p>Selecciona un paso del mapa para configurarlo.</p>
                    )}
                  </aside>
                </div>
                {issues.length ? (
                  <div className="workflow-warning">
                    <strong>Antes de guardar</strong>
                    <ul>
                      {issues.map((issue, index) => (
                        <li key={index}>{issue}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="workflow-next">
                  <div>
                    <span>Guardar no envía mensajes ni inicia llamadas.</span>
                  </div>
                  <button
                    className="crm-button crm-secondary"
                    onClick={() => setTab("history")}
                  >
                    Seleccionar clientes
                    <Icon name="chevron" />
                  </button>
                </div>
              </>
            ) : tab === "schedule" ? (
              <div className="workflow-schedule-layout">
                <section className="workflow-card">
                  <span className="crm-eyebrow">CUÁNDO EJECUTAR</span>
                  <h2>Horario y límites</h2>
                  <p>
                    La programación se congela al preparar la revisión. Zona
                    horaria: Colombia (America/Bogota).
                  </p>
                  <fieldset disabled={pending}>
                    <legend>Días de la semana</legend>
                    <div className="workflow-days">
                      {dayLabels.map((day, index) => (
                        <label key={day}>
                          <input
                            type="checkbox"
                            checked={document.schedule.days.includes(index + 1)}
                            onChange={(event) =>
                              changeDocument({
                                ...document,
                                schedule: {
                                  ...document.schedule,
                                  days: event.target.checked
                                    ? [
                                        ...document.schedule.days,
                                        index + 1,
                                      ].sort()
                                    : document.schedule.days.filter(
                                        (d) => d !== index + 1,
                                      ),
                                },
                              })
                            }
                          />
                          {day}
                        </label>
                      ))}
                    </div>
                    <div className="workflow-form-pair">
                      <label>
                        Desde
                        <input
                          type="time"
                          value={document.schedule.start_time}
                          onChange={(event) =>
                            changeDocument({
                              ...document,
                              schedule: {
                                ...document.schedule,
                                start_time: event.target.value,
                              },
                            })
                          }
                        />
                      </label>
                      <label>
                        Hasta
                        <input
                          type="time"
                          value={document.schedule.end_time}
                          onChange={(event) =>
                            changeDocument({
                              ...document,
                              schedule: {
                                ...document.schedule,
                                end_time: event.target.value,
                              },
                            })
                          }
                        />
                      </label>
                    </div>
                    <label>
                      Límite diario de acciones
                      <input
                        type="number"
                        min={1}
                        max={100}
                        step={1}
                        value={document.schedule.daily_limit}
                        onChange={(event) =>
                          changeDocument({
                            ...document,
                            schedule: {
                              ...document.schedule,
                              daily_limit: Number(event.target.value),
                            },
                          })
                        }
                      />
                    </label>
                    <label className="workflow-check">
                      <input
                        type="checkbox"
                        checked={document.stop_on_reply}
                        onChange={(event) =>
                          changeDocument({
                            ...document,
                            stop_on_reply: event.target.checked,
                          })
                        }
                      />
                      <span>
                        Detener pasos pendientes cuando exista una respuesta
                        verificada del cliente.
                      </span>
                    </label>
                  </fieldset>
                </section>
                <aside className="workflow-card workflow-schedule-note">
                  <Icon name="calendar" size={30} />
                  <h2>Una aprobación, un alcance exacto</h2>
                  <p>
                    La revisión vence a los 10 minutos. La autorización de
                    ejecución tiene vigencia limitada, máximo 30 días; consulta
                    la fecha confirmada de cada ejecución.
                  </p>
                  <p>
                    Un envío incierto no se repite automáticamente. Pausar o
                    detener no deshace acciones que ya ocurrieron.
                  </p>
                  <button
                    className="crm-button crm-secondary"
                    onClick={() => setTab("history")}
                  >
                    Revisar audiencia
                  </button>
                </aside>
              </div>
            ) : (
              <>
                <div className="workflow-audience-layout">
                  <section className="workflow-card">
                    <div className="workflow-section-heading">
                      <div>
                        <span className="crm-eyebrow">
                          AUDIENCIA DE ESTA EJECUCIÓN
                        </span>
                        <h2>Selecciona clientes existentes</h2>
                      </div>
                      <strong>{audience.length} / 50</strong>
                    </div>
                    <p>
                      Solo nombre, celular y medio del CRM. Esta selección no
                      inscribe futuros clientes.
                    </p>
                    <label className="workflow-search">
                      Buscar cliente
                      <input
                        type="search"
                        value={contactQuery}
                        onChange={(event) =>
                          setContactQuery(event.target.value)
                        }
                        placeholder="Nombre, celular o medio"
                      />
                    </label>
                    <div className="workflow-contact-list">
                      {filteredContacts.length ? (
                        filteredContacts.map((contact) => (
                          <div
                            key={contact.id}
                            className="workflow-contact-row"
                          >
                            <label className="workflow-contact-check">
                              <input
                                type="checkbox"
                                disabled={
                                  pending ||
                                  (!audience.includes(contact.id) &&
                                    audience.length >= 50)
                                }
                                checked={audience.includes(contact.id)}
                                onChange={() => toggleContact(contact.id)}
                              />
                              <span>
                                <strong>{contact.name}</strong>
                                <span>
                                  {phoneLabel(contact.phone)} ·{" "}
                                  {sourceLabel(contact.source)}
                                </span>
                              </span>
                            </label>
                            {audience.includes(contact.id)
                              ? socialAccountIds.map((accountId) => (
                                  <label
                                    className="workflow-binding"
                                    key={accountId}
                                  >
                                    Conversación ·{" "}
                                    {zernioAccounts.find(
                                      (item) => item.id === accountId,
                                    )?.name ??
                                      (accountId ||
                                        "Selecciona una cuenta en el paso")}
                                    <select
                                      aria-label={`Conversación de ${contact.name} en ${accountId}`}
                                      value={
                                        bindings[
                                          channelBindingKey(
                                            contact.id,
                                            accountId,
                                          )
                                        ]?.conversation_id ?? ""
                                      }
                                      disabled={pending || !accountId}
                                      onChange={(event) => {
                                        const conversation =
                                          channelConversations[accountId]?.find(
                                            (item) =>
                                              item.id === event.target.value &&
                                              item.account_id === accountId,
                                          );
                                        setBindings((previous) => ({
                                          ...previous,
                                          [channelBindingKey(
                                            contact.id,
                                            accountId,
                                          )]: {
                                            account_id: accountId,
                                            conversation_id:
                                              conversation?.id ?? "",
                                          },
                                        }));
                                        invalidateReview();
                                      }}
                                    >
                                      <option value="">
                                        Sin vincular · no se inferirá del
                                        celular
                                      </option>
                                      {bindings[
                                        channelBindingKey(contact.id, accountId)
                                      ]?.conversation_id &&
                                      !channelConversations[accountId]?.some(
                                        (item) =>
                                          item.id ===
                                          bindings[
                                            channelBindingKey(
                                              contact.id,
                                              accountId,
                                            )
                                          ].conversation_id,
                                      ) ? (
                                        <option
                                          value={
                                            bindings[
                                              channelBindingKey(
                                                contact.id,
                                                accountId,
                                              )
                                            ].conversation_id
                                          }
                                          disabled
                                        >
                                          Vinculación pendiente de verificar
                                        </option>
                                      ) : null}
                                      {(
                                        channelConversations[accountId] ?? []
                                      ).map((item) => (
                                        <option
                                          key={item.id}
                                          value={item.id}
                                          disabled={
                                            (!item.can_reply &&
                                              item.reason !==
                                                "zernio_window_verification_required") ||
                                            !socialNodes
                                              .filter(
                                                (node) =>
                                                  node.settings.account_id ===
                                                  accountId,
                                              )
                                              .every(
                                                (node) =>
                                                  node.settings.platform ===
                                                  item.platform,
                                              )
                                          }
                                        >
                                          {item.label} · {item.platform}
                                          {!item.can_reply
                                            ? item.reason ===
                                              "zernio_window_verification_required"
                                              ? " · Ventana pendiente de verificar"
                                              : " · No disponible"
                                            : ""}
                                        </option>
                                      ))}
                                    </select>
                                  </label>
                                ))
                              : null}
                          </div>
                        ))
                      ) : (
                        <p className="workflow-empty">
                          {contacts.length
                            ? "No hay clientes que coincidan con la búsqueda."
                            : "Aún no hay clientes en el CRM. Registra uno en Clientes para preparar una ejecución."}
                        </p>
                      )}
                    </div>
                    {socialNodes.length ? (
                      <div className="workflow-warning">
                        <p>
                          Cada destinatario necesita una conversación real de la
                          cuenta elegida. El teléfono no es una identidad
                          social. Vincula una conversación por cliente y cuenta;
                          puedes combinar Facebook, Instagram y WhatsApp en el
                          mismo recorrido.
                        </p>
                        {socialAccountIds.map((accountId) => (
                          <button
                            key={accountId}
                            className="crm-button crm-secondary"
                            disabled={optionsLoading || pending || !accountId}
                            onClick={() =>
                              void loadOptions("zernio", accountId)
                            }
                          >
                            Consultar conversaciones ·{" "}
                            {zernioAccounts.find(
                              (item) => item.id === accountId,
                            )?.name ?? accountId}
                          </button>
                        ))}
                        {missingBinding ? (
                          <p>
                            Faltan conversaciones vinculadas para la audiencia
                            seleccionada.
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </section>
                  <aside className="workflow-card workflow-preflight">
                    <span className="crm-eyebrow">
                      REVISAR ANTES DE ACTIVAR
                    </span>
                    <h2>{name || "Sin nombre"}</h2>
                    <dl>
                      <div>
                        <dt>Versión</dt>
                        <dd>
                          {workflowId ? version : "Sin guardar"}
                          {dirty ? " · Cambios pendientes" : ""}
                        </dd>
                      </div>
                      <div>
                        <dt>Audiencia</dt>
                        <dd>
                          {audience.length}{" "}
                          {audience.length === 1
                            ? "cliente seleccionado"
                            : "clientes seleccionados"}
                        </dd>
                      </div>
                      <div>
                        <dt>Horario</dt>
                        <dd>
                          {document.schedule.start_time}–
                          {document.schedule.end_time} · Colombia
                        </dd>
                      </div>
                      <div>
                        <dt>Límite diario</dt>
                        <dd>{document.schedule.daily_limit} acciones</dd>
                      </div>
                      <div>
                        <dt>Acciones externas por revisar</dt>
                        <dd>{externalActions} / 10</dd>
                      </div>
                    </dl>
                    {callRouteBlocked ? (
                      <p className="workflow-warning-text">
                        Hay destinatarios +57 y un paso de llamada. Falta
                        verificar la ruta telefónica de Colombia; elimina ese
                        paso para revisar solo mensajes o configura primero la
                        telefonía.
                      </p>
                    ) : null}
                    {reviewBudgetExceeded ? (
                      <p className="workflow-warning-text">
                        Esta revisión supera el límite de 10 acciones externas
                        (clientes × pasos de mensaje o llamada). Reduce la
                        audiencia o los pasos externos.
                      </p>
                    ) : null}
                    <label className="workflow-check">
                      <input
                        type="checkbox"
                        checked={audienceConsent}
                        disabled={pending}
                        onChange={(event) => {
                          setAudienceConsent(event.target.checked);
                          setReview(null);
                        }}
                      />
                      <span>
                        Confirmo que estos clientes autorizaron este contacto y
                        que puedo usar los canales seleccionados.
                      </span>
                    </label>
                    <button
                      ref={reviewTrigger}
                      className="crm-button"
                      disabled={!canPrepare}
                      onClick={() => void prepare()}
                    >
                      <Icon name="eye" />
                      Preparar revisión
                    </button>
                    <p>
                      No envía mensajes, no llama y no ejecuta acciones. Verás
                      destinatarios, cuentas y contenido antes de aprobar. Hasta
                      60 segundos de validación de proveedor; no se reserva ni
                      envía una acción durante la revisión.
                    </p>
                    {!workflowId || dirty ? (
                      <p className="workflow-warning-text">
                        Guarda el borrador actual antes de preparar.
                      </p>
                    ) : null}
                    <button
                      className="workflow-text-button"
                      onClick={() => setTab("builder")}
                    >
                      Volver al constructor
                    </button>
                  </aside>
                </div>
                <section className="workflow-history">
                  <div className="workflow-section-heading">
                    <div>
                      <span className="crm-eyebrow">
                        EJECUCIONES CONFIRMADAS
                      </span>
                      <h2>Estado e historial</h2>
                    </div>
                    <button
                      className="crm-button crm-secondary"
                      disabled={pending}
                      onClick={() => void refreshHistory()}
                    >
                      <Icon name="refresh" />
                      Actualizar historial
                    </button>
                  </div>
                  <p>
                    Un paso enviado al proveedor no prueba entrega, llamada
                    contestada ni venta. Los resultados inciertos quedan
                    retenidos, sin reenvío automático.
                  </p>
                  {runs.length ? (
                    <div className="workflow-run-list">
                      {runs.map((run) => (
                        <article key={run.id} className="workflow-run">
                          <div>
                            <strong>{run.workflow_name}</strong>
                            <span>
                              v{run.workflow_version} ·{" "}
                              {formatDate(run.created_at)}
                            </span>
                            <span
                              className={`workflow-status is-${run.status}`}
                            >
                              {runLabels[run.status]}
                            </span>
                            <span>
                              {run.counts.completed} finalizados ·{" "}
                              {run.counts.active} activos · {run.counts.blocked}{" "}
                              bloqueados · {run.counts.unknown} inciertos ·{" "}
                              {run.counts.total} en total
                            </span>
                          </div>
                          <div className="workflow-run-actions">
                            <button
                              className="crm-button crm-secondary"
                              disabled={pending || detailLoading}
                              onClick={() => void loadDetail(run.id)}
                            >
                              Ver historial
                            </button>
                            {run.status === "active" ? (
                              <button
                                className="crm-button crm-secondary"
                                disabled={pending}
                                onClick={() => void control(run, "pause")}
                              >
                                Pausar
                              </button>
                            ) : null}
                            {run.status === "paused" ? (
                              <button
                                className="crm-button crm-secondary"
                                disabled={pending || !workerReady}
                                onClick={() => void control(run, "resume")}
                              >
                                Reanudar
                              </button>
                            ) : null}
                            {[
                              "active",
                              "paused",
                              "blocked",
                              "unknown",
                            ].includes(run.status) ? (
                              <button
                                className="workflow-delete"
                                disabled={pending}
                                onClick={() => void control(run, "stop")}
                              >
                                Detener
                              </button>
                            ) : null}
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="workflow-empty">
                      No hay ejecuciones. Guardar una secuencia no crea
                      actividad ni envíos.
                    </p>
                  )}
                  {detailLoading ? (
                    <p role="status">Consultando eventos confirmados…</p>
                  ) : null}
                  {detail ? <RunHistory detail={detail} /> : null}
                </section>
              </>
            )}
          </div>
        </>
      )}
      <dialog
        ref={reviewDialog}
        className="workflow-review"
        aria-labelledby="workflow-review-title"
        onCancel={(event) => {
          if (pending) {
            event.preventDefault();
            return;
          }
          closeReview();
        }}
      >
        {review ? (
          <>
            <header>
              <div>
                <span className="crm-eyebrow">
                  APROBACIÓN EXACTA · NO ES UN BORRADOR
                </span>
                <h2 id="workflow-review-title">Revisar y activar secuencia</h2>
              </div>
              <button
                aria-label="Cerrar revisión"
                className="workflow-icon-button"
                disabled={pending}
                onClick={closeReview}
              >
                <Icon name="close" />
              </button>
            </header>
            <div className="workflow-review-body">
              <p>
                <strong>{review.run.workflow_name}</strong> · versión{" "}
                {review.run.workflow_version}. Revisión válida hasta{" "}
                {formatDate(review.expires_at)} (Colombia).
              </p>
              <div className="workflow-warning">
                <strong>
                  {workerReady
                    ? "La aprobación habilita ejecución automática dentro del alcance revisado."
                    : "Ejecutor no disponible: la activación está bloqueada."}
                </strong>
                <p>
                  No autoriza versiones futuras, nuevos clientes ni contenido
                  generado sin revisar.
                </p>
              </div>
              <h3>Destinatarios exactos ({review.recipients.length})</h3>
              <ul className="workflow-review-recipients">
                {review.recipients.map((recipient) => (
                  <li key={recipient.contact_id}>
                    <strong>{recipient.name}</strong>
                    <span>
                      {phoneLabel(recipient.phone)} ·{" "}
                      {sources.find(([key]) => key === recipient.source)?.[1] ??
                        recipient.source}
                    </span>
                    {recipient.channel_recipient ? (
                      <span>
                        Destino social:{" "}
                        {typeof recipient.channel_recipient === "string"
                          ? recipient.channel_recipient
                          : Object.entries(recipient.channel_recipient)
                              .filter(([, v]) => typeof v === "string")
                              .map(([key, value]) => `${key}: ${value}`)
                              .join(" · ")}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
              <h3>Acciones y contenido congelados</h3>
              <ol className="workflow-review-steps">
                {review.steps.map((step) => (
                  <li key={step.node_id}>
                    <strong>{step.label}</strong>
                    <p>{step.description}</p>
                  </li>
                ))}
              </ol>
              <h3>Programación y límites</h3>
              <p>
                {document.schedule.days
                  .map((day) => dayLabels[day - 1])
                  .join(", ")}{" "}
                · {document.schedule.start_time}–{document.schedule.end_time} ·
                America/Bogota · máximo {document.schedule.daily_limit} acciones
                por día.
              </p>
              <p>
                {document.stop_on_reply
                  ? "Se detienen los pasos pendientes ante una respuesta verificada."
                  : "Esta versión no detiene los pasos pendientes al recibir una respuesta."}{" "}
                La autorización vence como máximo en 30 días después de activar;
                la fecha definitiva se consulta en la ejecución confirmada.
              </p>
              {review.warnings.length ? (
                <div className="workflow-warning">
                  <strong>Condiciones y advertencias</strong>
                  <ul>
                    {review.warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <label className="workflow-check">
                <input
                  type="checkbox"
                  checked={approvalConsent}
                  disabled={pending || activationUncertain}
                  onChange={(event) => setApprovalConsent(event.target.checked)}
                />
                <span>
                  Apruebo estos destinatarios, cuentas remitentes, agente y
                  número de Retell, contenido, horario y límites exactos.
                  Confirmo el consentimiento de contacto y autorizo la ejecución
                  automática solo de esta versión.
                </span>
              </label>
              {Date.parse(review.expires_at) <= now ? (
                <p className="workflow-error">
                  La revisión venció. Ciérrala y prepara una nueva.
                </p>
              ) : null}
              {activationUncertain ? (
                <p className="workflow-error" role="alert">
                  No se confirmó la activación en esta pantalla. No la repitas:
                  cierra esta revisión y actualiza el historial para conocer el
                  estado del servidor.
                </p>
              ) : null}
              {error ? (
                <p className="workflow-error" role="alert">
                  {error}
                </p>
              ) : null}
            </div>
            <footer>
              <button
                className="crm-button crm-secondary"
                disabled={pending}
                onClick={closeReview}
              >
                Volver sin activar
              </button>
              <button
                className="crm-button"
                disabled={
                  pending ||
                  activationUncertain ||
                  !canActivate(
                    review,
                    catalog?.worker,
                    dirty,
                    approvalConsent,
                    now,
                  )
                }
                onClick={() => void activate()}
              >
                Aprobar y activar
              </button>
            </footer>
          </>
        ) : null}
      </dialog>
    </section>
  );
}

function NodeSettings({
  node,
  onChange,
  zernio,
  accounts,
  zernioAccountId,
  retell,
  optionsLoading,
  loadOptions,
}: {
  node: WorkflowNode;
  onChange: (key: string, value: string | number | boolean | string[]) => void;
  zernio: ZernioOptions;
  accounts: ZernioOptions["accounts"];
  zernioAccountId: string;
  retell: RetellOptions;
  optionsLoading: boolean;
  loadOptions: (
    provider: "zernio" | "retell",
    accountId?: string,
  ) => Promise<void>;
}) {
  const s = node.settings;
  const value = (key: string) => String(s[key] ?? "");
  const matchingAccount = zernioAccountId === value("account_id");
  const template = zernio.templates.find(
    (item) =>
      item.name === value("template_name") &&
      item.language === value("language"),
  );
  const params = Array.isArray(s.parameters) ? s.parameters : [];
  const account = accounts.find((item) => item.id === value("account_id"));
  return (
    <div className="workflow-node-settings">
      {node.kind === "wait" ? (
        <label>
          Tiempo de espera (horas)
          <input
            type="number"
            min={0}
            max={720}
            value={value("hours")}
            onChange={(event) => onChange("hours", Number(event.target.value))}
          />
          <small>
            Entre 0 y 720 horas. Se respeta el horario de ejecución.
          </small>
        </label>
      ) : null}
      {node.kind === "condition" ? (
        <>
          <label>
            Dato del CRM
            <select
              value={value("field")}
              onChange={(event) => {
                onChange("field", event.target.value);
              }}
            >
              <option value="stage">Etapa comercial</option>
              <option value="source">Medio de llegada</option>
            </select>
          </label>
          <label>
            Es igual a
            <select
              value={value("value")}
              onChange={(event) => onChange("value", event.target.value)}
            >
              <option value="">Seleccionar valor</option>
              {(value("field") === "source" ? sources : stages).map(
                ([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ),
              )}
            </select>
          </label>
        </>
      ) : null}
      {node.kind === "crm_note" ? (
        <label>
          Contenido de la nota
          <textarea
            rows={5}
            maxLength={2000}
            value={value("body")}
            onChange={(event) => onChange("body", event.target.value)}
            placeholder="Seguimiento acordado con {{nombre}}"
          />
        </label>
      ) : null}
      {node.kind === "crm_task" ? (
        <>
          <label>
            Título del seguimiento
            <input
              maxLength={160}
              value={value("title")}
              onChange={(event) => onChange("title", event.target.value)}
            />
          </label>
          <label>
            Vence después de (días)
            <input
              type="number"
              min={0}
              max={365}
              value={value("due_days")}
              onChange={(event) =>
                onChange("due_days", Number(event.target.value))
              }
            />
          </label>
        </>
      ) : null}
      {node.kind === "retell_call" ? (
        <>
          <p className="workflow-warning-text">
            Llamadas a Colombia (+57): requieren una ruta telefónica verificada;
            siguen bloqueadas mientras no esté configurada. Tener la API de
            Retell conectada no confirma cobertura ni autoriza llamadas.
          </p>
          <button
            className="crm-button crm-secondary"
            disabled={optionsLoading}
            onClick={() => void loadOptions("retell")}
          >
            <Icon name="refresh" size={16} />
            Consultar agentes y números
          </button>
          {!retell.available ? (
            <p className="workflow-warning-text">
              {retell.reason ?? "Aún no se han confirmado opciones de Retell."}
            </p>
          ) : null}
          <label>
            Agente de Retell
            <select
              value={value("agent_id")}
              disabled={optionsLoading || !retell.available}
              onChange={(event) => onChange("agent_id", event.target.value)}
            >
              <option value="">Seleccionar agente</option>
              {value("agent_id") &&
              !retell.agents.some((item) => item.id === value("agent_id")) ? (
                <option value={value("agent_id")}>
                  Guardado · sin verificar: {value("agent_id")}
                </option>
              ) : null}
              {retell.agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name} · {agent.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            Número de salida
            <select
              value={value("from_number")}
              disabled={optionsLoading || !retell.available}
              onChange={(event) => onChange("from_number", event.target.value)}
            >
              <option value="">Seleccionar número</option>
              {value("from_number") &&
              !retell.numbers.some(
                (item) => item.number === value("from_number"),
              ) ? (
                <option value={value("from_number")}>
                  Guardado · sin verificar: {value("from_number")}
                </option>
              ) : null}
              {retell.numbers.map((number) => (
                <option key={number.number} value={number.number}>
                  {number.label} · {number.number}
                </option>
              ))}
            </select>
          </label>
          <p className="workflow-warning-text">
            La revisión conserva las restricciones de llamadas del CRM. Tener un
            número no garantiza una ruta a Colombia ni permiso para este
            destinatario.
          </p>
        </>
      ) : null}
      {node.kind === "whatsapp_template" || node.kind === "social_message" ? (
        <>
          <button
            className="crm-button crm-secondary"
            disabled={optionsLoading}
            onClick={() => void loadOptions("zernio")}
          >
            <Icon name="refresh" size={16} />
            Consultar cuentas de Zernio
          </button>
          <label>
            Cuenta remitente
            <select
              value={value("account_id")}
              disabled={optionsLoading}
              onChange={(event) => {
                onChange("account_id", event.target.value);
                if (node.kind === "whatsapp_template") {
                  onChange("template_name", "");
                  onChange("language", "");
                  onChange("parameters", []);
                } else {
                  onChange("allow_provider_takeover", false);
                  onChange(
                    "platform",
                    accounts.find((item) => item.id === event.target.value)
                      ?.platform ?? "",
                  );
                }
                if (event.target.value)
                  void loadOptions("zernio", event.target.value);
              }}
            >
              <option value="">Seleccionar cuenta real</option>
              {value("account_id") &&
              !accounts.some((item) => item.id === value("account_id")) ? (
                <option value={value("account_id")}>
                  Guardada · sin verificar: {value("account_id")}
                </option>
              ) : null}
              {accounts
                .filter(
                  (item) =>
                    node.kind !== "whatsapp_template" ||
                    item.platform === "whatsapp",
                )
                .map((item) => (
                  <option
                    key={item.id}
                    value={item.id}
                    disabled={!item.available}
                  >
                    {item.name} · {item.platform}
                    {!item.available ? " · No disponible" : ""}
                  </option>
                ))}
            </select>
          </label>
          {value("account_id") && !matchingAccount ? (
            <button
              className="workflow-text-button"
              disabled={optionsLoading}
              onClick={() => void loadOptions("zernio", value("account_id"))}
            >
              Consultar opciones de esta cuenta
            </button>
          ) : null}
          {matchingAccount && !zernio.available ? (
            <p className="workflow-warning-text">
              {zernio.reason ?? "Esta cuenta no permite la acción solicitada."}
            </p>
          ) : null}
          {account?.reason ? (
            <p className="workflow-warning-text">{account.reason}</p>
          ) : null}
        </>
      ) : null}
      {node.kind === "whatsapp_template" ? (
        <>
          <label>
            Plantilla aprobada
            <select
              value={
                matchingAccount && template
                  ? `${template.name}|${template.language}`
                  : ""
              }
              disabled={optionsLoading || !matchingAccount || !zernio.available}
              onChange={(event) => {
                const item = zernio.templates.find(
                  (t) => `${t.name}|${t.language}` === event.target.value,
                );
                if (item) {
                  onChange("template_name", item.name);
                  onChange("language", item.language);
                  onChange(
                    "parameters",
                    Array.from({ length: item.parameter_count ?? 0 }, () => ""),
                  );
                }
              }}
            >
              <option value="">Seleccionar plantilla aprobada</option>
              {zernio.templates
                .filter((item) => item.status.toLowerCase() === "approved")
                .map((item) => (
                  <option
                    key={`${item.name}|${item.language}`}
                    value={`${item.name}|${item.language}`}
                  >
                    {item.name} · {item.language}
                  </option>
                ))}
            </select>
          </label>
          {value("template_name") ? (
            <p>
              Guardada: {value("template_name")} · {value("language")}
            </p>
          ) : null}
          {matchingAccount && template ? (
            <>
              <div className="workflow-template-preview">
                <strong>Contenido de la plantilla</strong>
                <p>
                  {template.body ??
                    "El proveedor no devolvió el cuerpo. No se puede verificar el contenido aquí; la preparación debe aportar evidencia o bloquear la acción."}
                </p>
              </div>
              {Array.from(
                { length: template.parameter_count ?? 0 },
                (_, index) => (
                  <label key={index}>
                    Parámetro {index + 1}
                    <input
                      value={params[index] ?? ""}
                      maxLength={1000}
                      onChange={(event) =>
                        onChange(
                          "parameters",
                          Array.from(
                            { length: template.parameter_count ?? 0 },
                            (_, i) =>
                              i === index
                                ? event.target.value
                                : (params[i] ?? ""),
                          ),
                        )
                      }
                    />
                  </label>
                ),
              )}
            </>
          ) : null}
          <p>
            Solo plantillas de Meta aprobadas. Los parámetros se revisan antes
            de activar; no se genera contenido automático.
          </p>
        </>
      ) : null}
      {node.kind === "social_message" ? (
        <>
          <label>
            Canal de esta cuenta
            <select
              value={value("platform")}
              onChange={(event) => {
                onChange("platform", event.target.value);
                onChange("allow_provider_takeover", false);
              }}
            >
              <option value="">Seleccionar canal verificado</option>
              {account &&
              [
                "facebook",
                "instagram",
                "telegram",
                "tiktok",
                "whatsapp",
              ].includes(account.platform) ? (
                <option value={account.platform}>{account.platform}</option>
              ) : null}
              {value("platform") && value("platform") !== account?.platform ? (
                <option value={value("platform")} disabled>
                  Guardado · sin verificar: {value("platform")}
                </option>
              ) : null}
            </select>
          </label>
          {["facebook", "instagram"].includes(value("platform")) ? (
            <label className="workflow-check">
              <input
                type="checkbox"
                checked={s.allow_provider_takeover === true}
                onChange={(event) =>
                  onChange("allow_provider_takeover", event.target.checked)
                }
              />
              <span>
                Autorizo que Zernio recupere el control de esta conversación y
                reenvíe una vez si Meta cambia su propietario. Solo respuestas
                dentro de 24 horas; no mensajes fríos ni HUMAN_AGENT automático.
              </span>
            </label>
          ) : null}
          <label>
            Mensaje exacto
            <textarea
              rows={5}
              maxLength={2000}
              value={value("text")}
              onChange={(event) => onChange("text", event.target.value)}
            />
          </label>
          <p className="workflow-warning-text">
            Solo conversaciones existentes y ventanas autorizadas. No permite
            mensajes fríos desde el celular del CRM. Los canales sin soporte
            permanecen bloqueados.
          </p>
        </>
      ) : null}
      {["whatsapp_template", "social_message", "crm_note", "crm_task"].includes(
        node.kind,
      ) ? (
        <p className="workflow-placeholders">
          Variables permitidas: <code>{"{{nombre}}"}</code> y{" "}
          <code>{"{{celular}}"}</code>.
        </p>
      ) : null}
      {node.kind === "end" ? (
        <p>No crea mensajes ni cambia el CRM. Finaliza este recorrido.</p>
      ) : null}
    </div>
  );
}

function RunHistory({ detail }: { detail: RunDetail }) {
  return (
    <section
      className="workflow-run-detail"
      aria-label="Historial de la ejecución seleccionada"
    >
      <div className="workflow-section-heading">
        <h3>
          {detail.run.workflow_name} · {runLabels[detail.run.status]}
        </h3>
        <span>Actualización manual · hora de Colombia</span>
      </div>
      <div className="workflow-recipient-history">
        {detail.recipients.map((recipient) => (
          <article key={recipient.contact_id}>
            <strong>{recipient.name}</strong>
            <span>{phoneLabel(recipient.phone)}</span>
            <span>
              {runLabels[recipient.status as keyof typeof runLabels] ??
                recipient.status}
            </span>
            {recipient.current_node_id ? (
              <span>
                Paso: {recipient.current_node_label ?? "Paso pendiente"}
              </span>
            ) : null}
            {recipient.due_at ? (
              <span>
                Próximo intento programado: {formatDate(recipient.due_at)}
              </span>
            ) : null}
            {recipient.error ? (
              <p className="workflow-warning-text">{recipient.error}</p>
            ) : null}
          </article>
        ))}
      </div>
      <h3>Eventos registrados</h3>
      {detail.events.length ? (
        <ol className="workflow-timeline">
          {detail.events.map((event) => (
            <li key={event.id}>
              <time dateTime={event.created_at}>
                {formatDate(event.created_at)}
              </time>
              <div>
                <strong>{event.kind}</strong>
                <p>{event.message}</p>
                {event.contact_id ? (
                  <small>
                    Cliente:{" "}
                    {detail.recipients.find(
                      (recipient) => recipient.contact_id === event.contact_id,
                    )?.name ?? event.contact_id}
                  </small>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="workflow-empty">
          Todavía no hay eventos confirmados. No se han inferido entregas ni
          resultados.
        </p>
      )}
    </section>
  );
}
