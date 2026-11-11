"use client";
import { useEffect, useRef, useState } from "react";
import {
  settingsError,
  type ActionResult,
  type Proposal,
  type SettingsRequest,
} from "./settings-types";
type HermesStatus = {
  configured: boolean;
  available: boolean;
  enabled: boolean;
  model: string | null;
  tools_count: number;
};
export function ActionProposals({
  proposals,
  request,
  onChanged,
}: {
  proposals: Proposal[];
  request: SettingsRequest;
  onChanged: () => Promise<void>;
}) {
  const [decisions, setDecisions] = useState<Record<string, Proposal>>({});
  const [results, setResults] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [pending, setPending] = useState("");
  const lock = useRef(false);
  const [error, setError] = useState("");
  async function decide(proposal: Proposal, decision: "approve" | "reject") {
    if (lock.current) return;
    lock.current = true;
    setPending(proposal.id);
    setError("");
    try {
      const result = await request<{
        proposal: Proposal;
        result?: Record<string, unknown>;
      }>(`hermes/proposals/${proposal.id}/${decision}`, "POST", {
        version: proposal.version,
      });
      setDecisions((old) => ({ ...old, [proposal.id]: result.proposal }));
      if (result.result)
        setResults((old) => ({ ...old, [proposal.id]: result.result! }));
      await onChanged();
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      lock.current = false;
      setPending("");
    }
  }
  return (
    <div className="settings-proposals">
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      {proposals.map((original) => {
        const proposal = decisions[original.id] ?? original;
        return (
          <article key={proposal.id} className="settings-proposal">
            <strong>{proposal.action}</strong>
            <span className="social-status">
              {
                {
                  pending: "Pendiente de revisión",
                  approved: "Aprobado",
                  rejected: "Rechazado",
                  expired: "Vencido",
                }[proposal.status]
              }
            </span>
            <pre aria-label={`Argumentos exactos de ${proposal.action}`}>
              {JSON.stringify(proposal.arguments, null, 2)}
            </pre>
            {results[proposal.id] && (
              <ActionResultDetails result={results[proposal.id]} />
            )}
            {proposal.status === "pending" && (
              <div className="social-actions">
                <button
                  className="crm-button"
                  disabled={!!pending}
                  onClick={() => void decide(proposal, "approve")}
                >
                  Aprobar acción exacta
                </button>
                <button
                  className="crm-button crm-secondary"
                  disabled={!!pending}
                  onClick={() => void decide(proposal, "reject")}
                >
                  Rechazar
                </button>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
export function ActionResultDetails({
  result,
}: {
  result: Record<string, unknown>;
}) {
  const uncertain = [
    "external_outcome_unconfirmed",
    "dispatch_reserved",
  ].includes(String(result.status));
  return (
    <details open>
      <summary>Resultado de la acción</summary>
      {uncertain && (
        <p className="social-warning" role="status">
          Resultado externo no confirmado. No repitas la acción; revisa su
          estado con el proveedor.
        </p>
      )}
      <pre className="settings-result">{JSON.stringify(result, null, 2)}</pre>
    </details>
  );
}
export function ActionOutput({
  value,
  request,
  onChanged,
}: {
  value: ActionResult;
  request: SettingsRequest;
  onChanged: () => Promise<void>;
}) {
  return (
    <>
      {value.result && <ActionResultDetails result={value.result} />}
      {!!value.proposals?.length && (
        <ActionProposals
          proposals={value.proposals}
          request={request}
          onChanged={onChanged}
        />
      )}
    </>
  );
}
export function HermesPanel({
  request,
  onChanged,
  revision,
}: {
  request: SettingsRequest;
  onChanged: () => Promise<void>;
  revision: number;
}) {
  const [status, setStatus] = useState<HermesStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const lock = useRef(false);
  const [response, setResponse] = useState<{
    run_id: string;
    reply: string;
    results: Record<string, unknown>[];
    proposals: Proposal[];
  } | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    request<HermesStatus>("hermes/status")
      .then((value) => {
        if (active) setStatus(value);
      })
      .catch((cause) => {
        if (active) setError(settingsError(cause));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [request, revision]);
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lock.current || !message.trim()) return;
    lock.current = true;
    setPending(true);
    setError("");
    setResponse(null);
    try {
      const result = await request<NonNullable<typeof response>>(
        "hermes/chat",
        "POST",
        { message: message.trim() },
      );
      setResponse(result);
      await onChanged();
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      lock.current = false;
      setPending(false);
    }
  }
  return (
    <section
      className="settings-hermes"
      aria-labelledby="hermes-panel-title"
      aria-busy={pending || loading}
    >
      <div className="settings-section-heading">
        <h3 id="hermes-panel-title">Hermes</h3>
        <span className="social-status">
          {loading
            ? "Consultando…"
            : status?.available && status.enabled
              ? "Disponible"
              : status?.configured
                ? "No disponible"
                : "Sin configurar"}
        </span>
      </div>
      {status && (
        <p className="settings-meta">
          {status.model ?? "Sin modelo"} · {status.tools_count} herramientas ·
          Cambios sujetos a tu aprobación
        </p>
      )}
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      <form onSubmit={submit}>
        <label htmlFor="hermes-message">¿Qué necesitas gestionar?</label>
        <textarea
          id="hermes-message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          maxLength={4000}
          required
          disabled={pending}
          placeholder="Consulta clientes o prepara un seguimiento…"
        />
        <button
          className="crm-button"
          disabled={
            loading ||
            pending ||
            !status?.available ||
            !status.enabled ||
            !message.trim()
          }
        >
          Enviar a Hermes
        </button>
      </form>
      {pending && <p role="status">Hermes está consultando la aplicación…</p>}
      {response && (
        <div className="settings-hermes-reply">
          <h4>Respuesta de Hermes</h4>
          <p>{response.reply}</p>
          {response.results.map((result, index) => (
            <ActionOutput
              key={`${response.run_id}-${index}`}
              value={{ result }}
              request={request}
              onChanged={onChanged}
            />
          ))}
          <ActionProposals
            key={response.run_id}
            proposals={response.proposals}
            request={request}
            onChanged={onChanged}
          />
        </div>
      )}
    </section>
  );
}
