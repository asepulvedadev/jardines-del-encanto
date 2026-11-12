"use client";
import { useEffect, useRef, useState } from "react";
import {
  settingsError,
  type ActionResult,
  type Proposal,
  type SettingsRequest,
} from "./settings-types";
import { ElevenLabsVoiceResult } from "./elevenlabs-result";
import { RetellVoiceResult } from "./retell-result";
import {
  VoiceProposalSummary,
  VoiceResultSummary,
  voiceOperationTitle,
} from "./voice-summary";

export type ActionPresentation = "technical" | "friendly";

function requiresConsent(proposal: Proposal) {
  return proposal.action === "retell.execute"
    ? (proposal.requirements?.consent ?? true)
    : proposal.action === "voice.execute" &&
        proposal.arguments.operation === "outbound_call";
}
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
  onResult,
  presentation = "technical",
}: {
  proposals: Proposal[];
  presentation?: ActionPresentation;
  onResult?: (result: Record<string, unknown>) => void | Promise<void>;
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
  const [consents, setConsents] = useState<Record<string, boolean>>({});
  async function decide(proposal: Proposal, decision: "approve" | "reject") {
    const outbound = requiresConsent(proposal);
    if (
      lock.current ||
      (decision === "approve" && outbound && !consents[proposal.id])
    )
      return;
    lock.current = true;
    setPending(proposal.id);
    setError("");
    try {
      const result = await request<{
        proposal: Proposal;
        result?: Record<string, unknown>;
      }>(`hermes/proposals/${proposal.id}/${decision}`, "POST", {
        version: proposal.version,
        ...(decision === "approve" && outbound
          ? { consent_confirmed: consents[proposal.id] === true }
          : {}),
      });
      setDecisions((old) => ({ ...old, [proposal.id]: result.proposal }));
      if (result.result)
        setResults((old) => ({ ...old, [proposal.id]: result.result! }));
      // Provider execution has finished. A failed view refresh must never replay it.
      try {
        if (result.result) await onResult?.(result.result);
        await onChanged();
      } catch {
        setError(
          "La acción ya respondió. No la repitas; actualiza la vista para revisar el resultado.",
        );
      }
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
            <strong>
              {presentation === "friendly" &&
              proposal.action === "retell.execute"
                ? voiceOperationTitle(proposal.arguments.endpoint)
                : proposal.action}
            </strong>
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
            {presentation === "friendly" &&
            proposal.action === "retell.execute" ? (
              <VoiceProposalSummary proposal={proposal} />
            ) : (
              <pre aria-label={`Argumentos exactos de ${proposal.action}`}>
                {JSON.stringify(proposal.arguments, null, 2)}
              </pre>
            )}
            {results[proposal.id] && (
              <ActionResultDetails
                result={results[proposal.id]}
                request={request}
                presentation={presentation}
              />
            )}
            {proposal.status === "pending" && requiresConsent(proposal) && (
              <label className="elevenlabs-consent">
                <input
                  type="checkbox"
                  checked={consents[proposal.id] === true}
                  onChange={(event) =>
                    setConsents((old) => ({
                      ...old,
                      [proposal.id]: event.target.checked,
                    }))
                  }
                  disabled={!!pending}
                />
                {proposal.action === "retell.execute"
                  ? proposal.requirements?.kind === "recipient"
                    ? "Confirmo que todos los destinatarios indicados autorizaron este contacto y acepto los cargos que pueda generar."
                    : "Revisé los argumentos exactos y autorizo los cambios, accesos, eliminaciones o cargos indicados para esta operación."
                  : "Confirmo que el destinatario indicado autorizó recibir esta llamada."}
              </label>
            )}
            {proposal.status === "pending" && (
              <div className="social-actions">
                <button
                  className="crm-button"
                  disabled={
                    !!pending ||
                    (requiresConsent(proposal) && !consents[proposal.id])
                  }
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
  request,
  presentation = "technical",
}: {
  result: Record<string, unknown>;
  request?: SettingsRequest;
  presentation?: ActionPresentation;
}) {
  const uncertain = [
    "external_outcome_unconfirmed",
    "dispatch_reserved",
  ].includes(String(result.status));
  const friendly = presentation === "friendly";
  const content = (
    <>
      {uncertain && (
        <p className="social-warning" role="status">
          Resultado externo no confirmado. No repitas la acción; revisa su
          estado con el proveedor.
        </p>
      )}
      {(result.provider === undefined || result.provider === "elevenlabs") && (
        <ElevenLabsVoiceResult result={result} request={request} />
      )}
      {result.provider === "retell" && (
        <RetellVoiceResult result={result} request={request} />
      )}
      {friendly ? (
        <VoiceResultSummary result={result} />
      ) : (
        <pre className="settings-result">{JSON.stringify(result, null, 2)}</pre>
      )}
    </>
  );
  return friendly ? (
    <section
      className="voice-result-summary"
      aria-label="Resultado de la acción"
    >
      {content}
    </section>
  ) : (
    <details open>
      <summary>Resultado de la acción</summary>
      {content}
    </details>
  );
}
export function ActionOutput({
  value,
  request,
  onChanged,
  onResult,
  presentation = "technical",
}: {
  onResult?: (result: Record<string, unknown>) => void | Promise<void>;
  presentation?: ActionPresentation;
  value: ActionResult;
  request: SettingsRequest;
  onChanged: () => Promise<void>;
}) {
  return (
    <>
      {value.result && (
        <ActionResultDetails
          result={value.result}
          request={request}
          presentation={presentation}
        />
      )}
      {!!value.proposals?.length && (
        <ActionProposals
          proposals={value.proposals}
          request={request}
          onChanged={onChanged}
          onResult={onResult}
          presentation={presentation}
        />
      )}
    </>
  );
}
export function HermesPanel({
  request,
  onChanged,
  revision,
  onOpenChat,
}: {
  request: SettingsRequest;
  onChanged: () => Promise<void>;
  revision: number;
  onOpenChat?: () => void;
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
        <h3 id="hermes-panel-title">Sara IA</h3>
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
      {onOpenChat ? (
        <button className="crm-button" onClick={onOpenChat}>
          Abrir chat de Sara IA
        </button>
      ) : (
        <>
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
              Enviar a Sara IA
            </button>
          </form>
          {pending && (
            <p role="status">Sara IA está consultando la aplicación…</p>
          )}
          {response && (
            <div className="settings-hermes-reply">
              <h4>Respuesta de Sara IA</h4>
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
        </>
      )}
    </section>
  );
}
