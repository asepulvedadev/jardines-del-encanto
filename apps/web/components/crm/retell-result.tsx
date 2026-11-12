"use client";
import { useEffect, useRef, useState } from "react";
import type { RetellWebClient } from "retell-client-js-sdk";
import type { SettingsRequest } from "./settings-types";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function RetellVoiceResult({
  result,
  request,
}: {
  result: Record<string, unknown>;
  request?: SettingsRequest;
}) {
  const sessionId = String(result.session_id ?? "");
  const [phase, setPhase] = useState("idle");
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  const live = useRef<RetellWebClient | null>(null);
  const generation = useRef(0),
    consumed = useRef(false),
    starting = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const root = useRef<HTMLDivElement>(null);
  function release() {
    generation.current++;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const client = live.current;
    live.current = null;
    client?.removeAllListeners();
    client?.stopCall();
    starting.current = false;
  }
  function stop() {
    release();
    setMuted(false);
    setPhase(consumed.current ? "ended" : "idle");
  }
  useEffect(() => {
    consumed.current = false;
    setPhase("idle");
    setError("");
    const dialog = root.current?.closest("dialog");
    const details: HTMLDetailsElement[] = [];
    let parent = root.current?.parentElement;
    while (parent) {
      if (parent.tagName === "DETAILS")
        details.push(parent as HTMLDetailsElement);
      parent = parent.parentElement;
    }
    const collapse = () => {
      if (details.some((element) => !element.open)) stop();
    };
    dialog?.addEventListener("close", stop);
    details.forEach((element) => element.addEventListener("toggle", collapse));
    return () => {
      dialog?.removeEventListener("close", stop);
      details.forEach((element) =>
        element.removeEventListener("toggle", collapse),
      );
      release();
    };
  }, [sessionId]);
  async function start() {
    if (
      !request ||
      consumed.current ||
      starting.current ||
      !uuid.test(sessionId)
    )
      return;
    consumed.current = true;
    starting.current = true;
    const run = ++generation.current;
    setPhase("starting");
    setError("");
    let client: RetellWebClient | null = null;
    try {
      const { RetellWebClient: Client } = await import("retell-client-js-sdk");
      if (run !== generation.current) return;
      const material = await request<{ access_token: string }>(
        `retell/sessions/${sessionId}/claim`,
        "POST",
        {},
      );
      if (run !== generation.current) return;
      if (!material.access_token || typeof material.access_token !== "string")
        throw new Error("invalid_session");
      client = new Client();
      live.current = client;
      client.on("call_ended", () => {
        if (run !== generation.current) return;
        stop();
      });
      client.on("error", () => {
        if (run !== generation.current) return;
        setError(
          "La sesión terminó con un error. Prepara una nueva autorización.",
        );
        stop();
      });
      await client.startCall({ accessToken: material.access_token });
      if (run !== generation.current) {
        client.removeAllListeners();
        client.stopCall();
        return;
      }
      setPhase("active");
      timer.current = setTimeout(stop, 5 * 60 * 1000);
    } catch {
      if (run === generation.current) {
        setError(
          "No se pudo iniciar la sesión. Revisa el permiso del micrófono y prepara una nueva autorización.",
        );
        stop();
      }
    } finally {
      if (run === generation.current) starting.current = false;
    }
  }
  if (
    result.provider !== "retell" ||
    result.status !== "ready" ||
    !uuid.test(sessionId) ||
    !request
  )
    return null;
  return (
    <div className="retell-result" ref={root}>
      <strong>Agente de Retell</strong>
      <p className="settings-meta">
        Requiere micrófono. El navegador finalizará a los 5 minutos; no es una
        garantía de facturación del proveedor.
      </p>
      <div className="social-actions">
        <button
          type="button"
          className="crm-button"
          disabled={phase !== "idle"}
          onClick={() => void start()}
        >
          {phase === "starting"
            ? "Iniciando…"
            : phase === "active"
              ? "Sesión activa"
              : phase === "ended"
                ? "Sesión finalizada"
                : "Iniciar sesión de voz"}
        </button>
        {phase === "active" && (
          <button
            type="button"
            className="crm-button crm-secondary"
            aria-pressed={muted}
            onClick={() => {
              if (!live.current) return;
              if (muted) live.current.unmute();
              else live.current.mute();
              setMuted(!muted);
            }}
          >
            {muted ? "Activar micrófono" : "Silenciar micrófono"}
          </button>
        )}
        {["starting", "active"].includes(phase) && (
          <button
            type="button"
            className="crm-button crm-secondary"
            onClick={stop}
          >
            Finalizar
          </button>
        )}
      </div>
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
