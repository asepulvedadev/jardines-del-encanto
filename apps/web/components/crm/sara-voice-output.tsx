"use client";

import { useRef, useState } from "react";
import { ActionOutput } from "./hermes-panel";
import {
  settingsError,
  type ActionResult,
  type SettingsRequest,
} from "./settings-types";

/** Use the same approved voice operation as the rest of the CRM. */
export function SaraVoiceOutput({
  text,
  request,
  onChanged,
}: {
  text: string;
  request: SettingsRequest;
  onChanged: () => Promise<void>;
}) {
  const locked = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [output, setOutput] = useState<ActionResult | null>(null);

  async function propose() {
    if (locked.current) return;
    locked.current = true;
    setPending(true);
    setError("");
    try {
      const state = await request<{
        configured: boolean;
        verified: boolean;
        enabled: boolean;
        defaults: { voice_id: string; model_id: string };
      }>("voice/settings");
      if (
        !state.configured ||
        !state.verified ||
        !state.enabled ||
        !state.defaults?.voice_id ||
        !state.defaults?.model_id
      ) {
        setError("Configura y activa una voz de ElevenLabs en Conexiones.");
        return;
      }
      setOutput(
        await request<ActionResult>("hermes/actions", "POST", {
          action: "voice.execute",
          arguments: {
            operation: "tts",
            arguments: {
              text,
              voice_id: state.defaults.voice_id,
              model_id: state.defaults.model_id,
            },
          },
        }),
      );
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  if (!text.trim() || text.length > 1500) return null;
  return (
    <div className="sara-voice-output">
      <button
        type="button"
        className="crm-button crm-secondary"
        disabled={pending || output !== null}
        onClick={() => void propose()}
        aria-label="Proponer audio de esta respuesta con ElevenLabs"
      >
        {pending ? "Preparando audio…" : "Crear audio"}
      </button>
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      {output && (
        <ActionOutput value={output} request={request} onChanged={onChanged} />
      )}
    </div>
  );
}
