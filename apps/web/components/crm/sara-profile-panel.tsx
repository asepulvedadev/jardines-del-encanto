"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { settingsError, type SettingsRequest } from "./settings-types";
import "./sara-profile.css";

type ProfileDocument = {
  name: string;
  instructions: string;
  knowledge: string;
  greeting: string;
  response_style: "brief" | "balanced" | "detailed";
};
type Profile = ProfileDocument & { version: number; updated_at: string };
type ProfileVersion = {
  version: number;
  document: ProfileDocument;
  author: string;
  source: string;
  created_at: string;
};
type Simulation = {
  id: string;
  title?: string;
  status: string;
  synthetic: true;
  profile_version: number;
  transcript?: { role: "user" | "assistant"; content: string }[];
  error?: string | null;
};
type SimulationRequest = {
  request_id: string;
  title: string;
  customer_turns: string[];
};
const styles = {
  brief: "Breve",
  balanced: "Equilibrado",
  detailed: "Detallado",
};
const jobLabels: Record<string, string> = {
  queued: "En cola",
  processing: "Simulando",
  completed: "Completada",
  failed: "Fallida",
};
const emptyDocument: ProfileDocument = {
  name: "",
  instructions: "",
  knowledge: "",
  greeting: "",
  response_style: "balanced",
};
function documentFrom(profile: Profile): ProfileDocument {
  return {
    name: profile.name,
    instructions: profile.instructions,
    knowledge: profile.knowledge,
    greeting: profile.greeting,
    response_style: profile.response_style,
  };
}
function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible"
    : date.toLocaleString("es-CO", {
        timeZone: "America/Bogota",
        dateStyle: "short",
        timeStyle: "short",
      });
}
function publishedDocument(document: ProfileDocument) {
  return (
    <dl className="sara-profile-document">
      <dt>Nombre</dt>
      <dd>{document.name}</dd>
      <dt>Instrucciones</dt>
      <dd>{document.instructions || "Sin instrucciones"}</dd>
      <dt>Conocimiento</dt>
      <dd>{document.knowledge || "Sin conocimiento"}</dd>
      <dt>Saludo</dt>
      <dd>{document.greeting || "Sin saludo"}</dd>
      <dt>Estilo</dt>
      <dd>{styles[document.response_style] ?? "No disponible"}</dd>
    </dl>
  );
}

export function SaraProfilePanel({
  request,
  active = true,
}: {
  request: SettingsRequest;
  active?: boolean;
}) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [draft, setDraft] = useState<ProfileDocument>(emptyDocument);
  const [draftVersion, setDraftVersion] = useState(0);
  const [versions, setVersions] = useState<ProfileVersion[]>([]);
  const [jobs, setJobs] = useState<Simulation[]>([]);
  const [selected, setSelected] = useState<Simulation | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [review, setReview] = useState(false);
  const [reviewedVersion, setReviewedVersion] = useState<number | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [jobsError, setJobsError] = useState("");
  const [title, setTitle] = useState("");
  const [turns, setTurns] = useState<string[]>([""]);
  const [simulationError, setSimulationError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [jobLoading, setJobLoading] = useState(false);
  const [pollProblem, setPollProblem] = useState("");
  const [pollStopped, setPollStopped] = useState(false);
  const [pageVisible, setPageVisible] = useState(true);
  const dirty = useRef(false);
  const initialized = useRef(false);
  const profileLock = useRef(false);
  const simulationLock = useRef(false);
  const jobLock = useRef(false);
  const jobGeneration = useRef(0);
  const submission = useRef<SimulationRequest | null>(null);

  const loadVersions = useCallback(async () => {
    try {
      const result = await request<{ versions: ProfileVersion[] }>(
        "sara/config/versions",
      );
      setVersions(result.versions);
      setHistoryError("");
    } catch {
      setHistoryError("No pudimos actualizar el historial de versiones.");
    }
  }, [request]);
  const loadJobs = useCallback(async () => {
    try {
      const result = await request<{ simulations: Simulation[] }>(
        "sara/simulations",
      );
      setJobs(result.simulations.filter((job) => job.synthetic === true));
      setJobsError("");
    } catch {
      setJobsError("No pudimos actualizar las simulaciones.");
    }
  }, [request]);
  const loadProfile = useCallback(async () => {
    if (profileLock.current) return;
    profileLock.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await request<Profile>("sara/config");
      setProfile(result);
      if (dirty.current) {
        setReview(true);
        setReviewedVersion(result.version);
        setNotice(
          "Conservamos tu borrador. Compara la versión publicada antes de reemplazarla.",
        );
      } else {
        setDraft(documentFrom(result));
        setDraftVersion(result.version);
        setReview(false);
        setReviewedVersion(null);
      }
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      profileLock.current = false;
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    if (active && !initialized.current) {
      initialized.current = true;
      void Promise.all([loadProfile(), loadVersions(), loadJobs()]);
    }
  }, [active, loadProfile, loadVersions, loadJobs]);
  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => setPageVisible(document.visibilityState !== "hidden");
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  const rememberJob = useCallback((job: Simulation) => {
    if (job.synthetic !== true)
      throw new Error("El servidor no confirmó una simulación sintética.");
    setSelected(job);
    setJobs((old) =>
      [job, ...old.filter((item) => item.id !== job.id)].slice(0, 20),
    );
  }, []);
  useEffect(() => {
    if (
      !active ||
      !pageVisible ||
      pollStopped ||
      !selected ||
      !["queued", "processing"].includes(selected.status)
    )
      return;
    let cancelled = false;
    let failures = 0;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const id = selected.id;
    const generation = jobGeneration.current;
    const poll = async () => {
      if (cancelled || generation !== jobGeneration.current) return;
      attempts++;
      let continuePolling = true;
      try {
        const result = await request<Simulation>(`sara/simulations/${id}`);
        if (cancelled || generation !== jobGeneration.current) return;
        rememberJob(result);
        failures = 0;
        setPollProblem("");
        continuePolling = ["queued", "processing"].includes(result.status);
      } catch {
        if (cancelled || generation !== jobGeneration.current) return;
        failures++;
        if (failures >= 3) {
          setPollProblem(
            "No pudimos confirmar el estado. Consulta el resultado; no crees otra simulación.",
          );
          setPollStopped(true);
          return;
        }
      }
      if (continuePolling && attempts >= 40) {
        setPollProblem(
          "Se agotó la espera. El estado actual es desconocido; consulta el resultado.",
        );
        setPollStopped(true);
        return;
      }
      if (!cancelled && continuePolling) timer = setTimeout(poll, 4000);
    };
    timer = setTimeout(poll, 4000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    active,
    pageVisible,
    selected?.id,
    selected?.status,
    pollStopped,
    request,
    rememberJob,
  ]);

  function edit<K extends keyof ProfileDocument>(
    key: K,
    value: ProfileDocument[K],
  ) {
    dirty.current = true;
    setDraft((old) => ({ ...old, [key]: value }));
    setNotice("");
  }
  async function saveProfile() {
    if (profileLock.current || simulationLock.current || !profile || review)
      return;
    if (!draft.name.trim() || !draft.instructions.trim()) {
      setError("Escribe el nombre y las instrucciones de Sara.");
      return;
    }
    profileLock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<Profile>("sara/config", "PATCH", {
        version: draftVersion,
        ...draft,
      });
      setProfile(result);
      setDraft(documentFrom(result));
      setDraftVersion(result.version);
      dirty.current = false;
      setReview(false);
      setReviewedVersion(null);
      setNotice(
        "Perfil publicado. Las nuevas conversaciones usarán esta versión.",
      );
      await loadVersions();
    } catch (cause) {
      setError(
        `${settingsError(cause)} Actualiza el perfil antes de intentar de nuevo.`,
      );
      setReview(true);
      setReviewedVersion(null);
    } finally {
      profileLock.current = false;
      setBusy(false);
    }
  }
  async function simulate(retry = false) {
    if (
      simulationLock.current ||
      profileLock.current ||
      jobLock.current ||
      (!retry && uncertain)
    )
      return;
    if (!retry) {
      if (
        !title.trim() ||
        turns.length < 1 ||
        turns.length > 4 ||
        turns.some((turn) => !turn.trim() || turn.length > 800)
      ) {
        setSimulationError(
          "Escribe un título y entre 1 y 4 mensajes ficticios, de máximo 800 caracteres.",
        );
        return;
      }
      submission.current = {
        request_id: crypto.randomUUID(),
        title: title.trim(),
        customer_turns: turns.map((turn) => turn.trim()),
      };
    }
    if (!submission.current) return;
    simulationLock.current = true;
    jobGeneration.current++;
    setBusy(true);
    setSimulationError("");
    try {
      const result = await request<Simulation>(
        "sara/simulations",
        "POST",
        submission.current,
      );
      rememberJob(result);
      setUncertain(false);
      submission.current = null;
      setPollProblem("");
      setPollStopped(false);
    } catch (cause) {
      setUncertain(true);
      setSimulationError(
        `No sabemos si se creó la simulación. ${settingsError(cause)} Reintenta la misma solicitud para recuperar su resultado.`,
      );
    } finally {
      simulationLock.current = false;
      setBusy(false);
    }
  }
  async function openJob(id: string) {
    if (jobLock.current || simulationLock.current) return;
    jobLock.current = true;
    jobGeneration.current++;
    setJobLoading(true);
    setPollProblem("");
    // Stop an older job's timer before requesting the newly selected transcript.
    setPollStopped(true);
    try {
      const result = await request<Simulation>(`sara/simulations/${id}`);
      rememberJob(result);
      setPollStopped(false);
    } catch {
      setPollProblem(
        "No pudimos confirmar el estado. Consulta el resultado nuevamente.",
      );
    } finally {
      jobLock.current = false;
      setJobLoading(false);
    }
  }

  const disabled = loading || busy;
  return (
    <div className="sara-profile-panel" aria-busy={disabled}>
      <header className="sara-profile-heading">
        <div>
          <h3>Perfil de Sara</h3>
          <p>Instrucciones publicadas para la atención web y WhatsApp.</p>
        </div>
        <button
          type="button"
          disabled={disabled}
          onClick={async () => {
            await Promise.all([loadProfile(), loadVersions()]);
          }}
        >
          Actualizar perfil
        </button>
      </header>
      {loading && <p role="status">Consultando el perfil publicado…</p>}
      {error && (
        <p className="sara-profile-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="sara-profile-notice" role="status">
          {notice}
        </p>
      )}
      {profile && (
        <>
          <p className="sara-profile-meta">
            Versión {profile.version} · {formatDate(profile.updated_at)}{" "}
            (Bogotá)
          </p>
          {review && (
            <div className="sara-profile-review">
              <p>
                Tu borrador sigue aquí. Actualiza y revisa antes de publicar.
              </p>
              {reviewedVersion !== null && (
                <>
                  <details>
                    <summary>
                      Comparar perfil publicado · versión {profile.version}
                    </summary>
                    {publishedDocument(profile)}
                  </details>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setDraftVersion(reviewedVersion);
                      setReviewedVersion(null);
                      setReview(false);
                      setNotice(
                        "Borrador conservado. Publicar reemplazará la versión revisada.",
                      );
                    }}
                  >
                    Revisé la versión publicada
                  </button>
                </>
              )}
            </div>
          )}
          <fieldset className="sara-profile-fields" disabled={disabled}>
            <legend>Perfil publicado</legend>
            <div className="sara-profile-grid">
              <label htmlFor="sara-profile-name">
                Nombre
                <input
                  id="sara-profile-name"
                  value={draft.name}
                  maxLength={80}
                  required
                  onChange={(event) => edit("name", event.target.value)}
                />
              </label>
              <label htmlFor="sara-profile-style">
                Estilo de respuesta
                <select
                  id="sara-profile-style"
                  value={draft.response_style}
                  onChange={(event) =>
                    edit(
                      "response_style",
                      event.target.value as ProfileDocument["response_style"],
                    )
                  }
                >
                  {Object.entries(styles).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label htmlFor="sara-profile-greeting">
              Saludo
              <textarea
                id="sara-profile-greeting"
                rows={2}
                maxLength={300}
                value={draft.greeting}
                onChange={(event) => edit("greeting", event.target.value)}
              />
            </label>
            <label htmlFor="sara-profile-instructions">
              Instrucciones
              <textarea
                id="sara-profile-instructions"
                rows={4}
                maxLength={2000}
                required
                value={draft.instructions}
                onChange={(event) => edit("instructions", event.target.value)}
              />
            </label>
            <label htmlFor="sara-profile-knowledge">
              Conocimiento aprobado
              <textarea
                id="sara-profile-knowledge"
                rows={5}
                maxLength={4000}
                value={draft.knowledge}
                onChange={(event) => edit("knowledge", event.target.value)}
              />
            </label>
          </fieldset>
          <div className="sara-profile-actions">
            <button
              className="sara-profile-primary"
              type="button"
              disabled={disabled || review || !dirty.current}
              onClick={saveProfile}
            >
              Publicar cambios
            </button>
          </div>
        </>
      )}
      <details className="sara-profile-history">
        <summary>Historial de versiones</summary>
        {historyError && (
          <p className="sara-profile-error" role="alert">
            {historyError}
          </p>
        )}
        {!versions.length && <p>No hay versiones disponibles.</p>}
        {versions.map((version) => (
          <details key={version.version}>
            <summary>
              Versión {version.version} · {version.author} ·{" "}
              {formatDate(version.created_at)} (Bogotá)
            </summary>
            <p className="sara-profile-meta">Origen: {version.source}</p>
            {publishedDocument(version.document)}
          </details>
        ))}
      </details>
      <section
        className="sara-simulation"
        aria-labelledby="sara-simulation-title-heading"
      >
        <div>
          <h4 id="sara-simulation-title-heading">Simular una conversación</h4>
          <p>
            Prueba con un cliente ficticio y el perfil publicado. No envía
            mensajes reales ni crea clientes; no entrena a Sara.
          </p>
        </div>
        {dirty.current && (
          <p className="sara-profile-notice">
            La simulación no usa tu borrador sin publicar.
          </p>
        )}
        {simulationError && (
          <p className="sara-profile-error" role="alert">
            {simulationError}
          </p>
        )}
        <fieldset className="sara-profile-fields" disabled={busy || uncertain}>
          <legend>Escenario ficticio</legend>
          <label htmlFor="sara-simulation-title">
            Título
            <input
              id="sara-simulation-title"
              maxLength={120}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          {turns.map((turn, index) => (
            <div className="sara-simulation-turn" key={index}>
              <label htmlFor={`sara-simulation-turn-${index}`}>
                Mensaje del cliente ficticio {index + 1}
                <textarea
                  id={`sara-simulation-turn-${index}`}
                  maxLength={800}
                  rows={2}
                  value={turn}
                  onChange={(event) =>
                    setTurns((old) =>
                      old.map((value, i) =>
                        i === index ? event.target.value : value,
                      ),
                    )
                  }
                />
              </label>
              {turns.length > 1 && (
                <button
                  type="button"
                  aria-label={`Quitar mensaje ${index + 1}`}
                  onClick={() =>
                    setTurns((old) => old.filter((_, i) => i !== index))
                  }
                >
                  Quitar
                </button>
              )}
            </div>
          ))}
          <div className="sara-profile-actions">
            <button
              type="button"
              disabled={turns.length >= 4}
              onClick={() =>
                setTurns((old) => (old.length < 4 ? [...old, ""] : old))
              }
            >
              Agregar mensaje
            </button>
          </div>
        </fieldset>
        <div className="sara-profile-actions">
          {uncertain ? (
            <button
              type="button"
              disabled={busy || jobLoading}
              onClick={() => simulate(true)}
            >
              Reintentar misma solicitud
            </button>
          ) : (
            <button
              type="button"
              className="sara-profile-primary"
              disabled={disabled || jobLoading || !profile}
              onClick={() => simulate()}
            >
              Simular conversación
            </button>
          )}
          <button
            type="button"
            disabled={busy || jobLoading}
            onClick={loadJobs}
          >
            Actualizar simulaciones
          </button>
        </div>
        {jobsError && (
          <p className="sara-profile-error" role="alert">
            {jobsError}
          </p>
        )}
        {!jobs.length && <p>Aún no hay simulaciones.</p>}
        <ul className="sara-simulation-list">
          {jobs.map((job) => (
            <li key={job.id}>
              <button
                type="button"
                disabled={jobLoading || busy}
                aria-pressed={selected?.id === job.id}
                onClick={() => openJob(job.id)}
              >
                {job.title || "Simulación"} ·{" "}
                {jobLabels[job.status] ?? "Estado desconocido"} · perfil v
                {job.profile_version}
              </button>
            </li>
          ))}
        </ul>
        {jobLoading && <p role="status">Consultando el resultado…</p>}
        {pollProblem && (
          <p className="sara-profile-error" role="alert">
            {pollProblem}
          </p>
        )}
        {selected && (
          <section
            className="sara-simulation-result"
            aria-labelledby="sara-simulation-result-title"
          >
            <div className="sara-profile-heading">
              <h4 id="sara-simulation-result-title">
                Resultado sintético · perfil v{selected.profile_version}
              </h4>
              <button
                type="button"
                disabled={jobLoading || busy}
                onClick={() => openJob(selected.id)}
              >
                Consultar resultado
              </button>
            </div>
            <p role="status">
              {jobLabels[selected.status] ?? "Estado desconocido"}
              {pollStopped ? " · sin actualización automática" : ""}
            </p>
            {selected.status === "failed" && (
              <p className="sara-profile-error" role="alert">
                La simulación no se completó. Revisa la conexión de Sara antes
                de iniciar otra.
              </p>
            )}
            {!["queued", "processing", "completed", "failed"].includes(
              selected.status,
            ) && (
              <p>
                No podemos confirmar el resultado. Consulta su estado antes de
                iniciar otra prueba.
              </p>
            )}
            {selected.transcript?.length ? (
              <ol className="sara-simulation-transcript">
                {selected.transcript.map((message, index) => (
                  <li
                    key={index}
                    className={
                      message.role === "assistant"
                        ? "sara-simulation-assistant"
                        : ""
                    }
                  >
                    <strong>
                      {message.role === "assistant"
                        ? "Sara · simulación"
                        : "Cliente ficticio"}
                    </strong>
                    <p>{message.content}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p>El resultado aún no incluye mensajes.</p>
            )}
          </section>
        )}
      </section>
    </div>
  );
}
