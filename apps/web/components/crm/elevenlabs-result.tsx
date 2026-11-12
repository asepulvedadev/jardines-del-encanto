"use client";
import { useEffect, useRef, useState } from "react";
import type { Conversation as VoiceConversation } from "@elevenlabs/client";
import { settingsError, type SettingsRequest } from "./settings-types";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function voiceArtifactPath(
  result: Record<string, unknown>,
): string | null {
  const id = String(result.artifact_id ?? "");
  const path = `/api/crm/voice/artifacts/${id}/content`;
  return uuid.test(id) && result.content_path === path ? path : null;
}
export function ElevenLabsVoiceResult({
  result,
  request,
}: {
  result: Record<string, unknown>;
  request?: SettingsRequest;
}) {
  const path = voiceArtifactPath(result);
  const sessionId = String(result.session_id ?? "");
  const [muted, setMuted] = useState(false);
  const [phase, setPhase] = useState("idle"),
    [error, setError] = useState("");
  const live = useRef<VoiceConversation | null>(null),
    generation = useRef(0),
    starting = useRef(false),
    consumed = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const root = useRef<HTMLDivElement>(null);
  function stop() {
    generation.current += 1;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const current = live.current;
    live.current = null;
    if (current) void current.endSession().catch(() => {});
    starting.current = false;
    setMuted(false);
    setPhase(consumed.current ? "ended" : "idle");
  }
  useEffect(() => {
    const dialog = root.current?.closest("dialog");
    const details: HTMLDetailsElement[] = [];
    let ancestor = root.current?.parentElement;
    while (ancestor) {
      if (ancestor.tagName === "DETAILS")
        details.push(ancestor as HTMLDetailsElement);
      ancestor = ancestor.parentElement;
    }
    const collapse = () => {
      if (details.some((value) => !value.open)) stop();
    };
    dialog?.addEventListener("close", stop);
    for (const element of details) element.addEventListener("toggle", collapse);
    return () => {
      dialog?.removeEventListener("close", stop);
      for (const element of details)
        element.removeEventListener("toggle", collapse);
      generation.current += 1;
      if (timer.current) clearTimeout(timer.current);
      const current = live.current;
      live.current = null;
      if (current) void current.endSession().catch(() => {});
    };
  }, []);
  async function start() {
    if (
      !request ||
      starting.current ||
      consumed.current ||
      !uuid.test(sessionId)
    )
      return;
    starting.current = true;
    consumed.current = true;
    const run = ++generation.current;
    setPhase("starting");
    setError("");
    try {
      const { Conversation } = await import("@elevenlabs/client");
      if (run !== generation.current) return;
      const material = await request<{ token: string }>(
        `voice/sessions/${sessionId}/claim`,
        "POST",
        {},
      );
      if (run !== generation.current) return;
      const current = await Conversation.startSession({
        conversationToken: material.token,
        connectionType: "webrtc",
        onDisconnect: () => {
          if (run === generation.current) {
            generation.current += 1;
            starting.current = false;
            live.current = null;
            setMuted(false);
            setPhase("ended");
            if (timer.current) clearTimeout(timer.current);
            timer.current = null;
          }
        },
        onError: () => {
          if (run === generation.current) {
            setError(
              "La sesión de voz terminó con un error. Solicita una nueva autorización.",
            );
            stop();
          }
        },
      });
      if (run !== generation.current) {
        await current.endSession();
        return;
      }
      live.current = current;
      setPhase("active");
      timer.current = setTimeout(stop, 5 * 60 * 1000);
    } catch (cause) {
      if (run === generation.current) {
        setError(
          cause instanceof DOMException && cause.name === "NotAllowedError"
            ? "No se autorizó el micrófono. Solicita una nueva sesión para intentarlo de nuevo."
            : "No se pudo iniciar la sesión. La autorización es de un solo uso; prepara otra sesión.",
        );
        setPhase("ended");
      }
    } finally {
      if (run === generation.current) starting.current = false;
    }
  }
  return (
    <div className="elevenlabs-result" ref={root}>
      {path && (
        <audio
          controls
          preload="none"
          src={path}
          aria-label="Audio generado por ElevenLabs"
        />
      )}
      {result.status === "ready" && uuid.test(sessionId) && request && (
        <>
          <strong>Agente de ElevenLabs</strong>
          <p className="settings-meta">
            Requiere micrófono. El navegador finalizará a los 5 minutos; no es
            una garantía de facturación del proveedor.
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
                  const next = !muted;
                  live.current?.setMicMuted(next);
                  setMuted(next);
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
        </>
      )}
      {error && (
        <p className="crm-error" role="alert">
          {settingsError(new Error(error))}
        </p>
      )}
    </div>
  );
}
