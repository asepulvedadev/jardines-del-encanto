"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActionOutput } from "./hermes-panel";
import { saraFileBase64, saraUploadMime } from "./sara-types";
import {
  settingsError,
  type ActionResult,
  type SettingsRequest,
} from "./settings-types";
type Defaults = {
  voice_id: string;
  model_id: string;
  agent_id: string;
  phone_number_id: string;
};
type State = {
  configured: boolean;
  verified: boolean;
  revision: number;
  enabled: boolean;
  available?: boolean;
  key_suffix?: string;
  defaults: Defaults;
};
type Entry = { id: string; name: string };
type Catalog = {
  revision: number;
  voices: Entry[];
  models: Entry[];
  agents: Entry[];
  phone_numbers: Entry[];
  limited: boolean;
  errors: string[];
};
type Contact = { id: string; name: string; phone: string };
const labels = {
  voice_id: "Voz",
  model_id: "Modelo",
  agent_id: "Agente",
  phone_number_id: "Línea telefónica",
};
const catalogLabels: Record<string, string> = {
  voices: "voces",
  models: "modelos",
  agents: "agentes",
  phone_numbers: "líneas",
};
const empty: Defaults = {
  voice_id: "",
  model_id: "",
  agent_id: "",
  phone_number_id: "",
};
export function ElevenLabsPanel({
  request,
  onChanged,
  active,
}: {
  request: SettingsRequest;
  onChanged: () => Promise<void>;
  active: boolean;
}) {
  const [state, setState] = useState<State | null>(null),
    [catalog, setCatalog] = useState<Catalog | null>(null),
    [defaults, setDefaults] = useState<Defaults>(empty);
  const [key, setKey] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [disconnect, setDisconnect] = useState(false);
  const [operation, setOperation] = useState("tts"),
    [text, setText] = useState(""),
    [attachment, setAttachment] = useState<{
      attachment_id: string;
      filename: string;
    } | null>(null),
    [contacts, setContacts] = useState<Contact[]>([]),
    [contactId, setContactId] = useState("");
  const [output, setOutput] = useState<ActionResult | null>(null),
    [outputKey, setOutputKey] = useState(0);
  const mounted = useRef(false),
    lock = useRef(false),
    generation = useRef(0),
    fileInput = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    const run = generation.current;
    const value = await request<State>("voice/settings");
    if (mounted.current && run === generation.current) {
      setState(value);
      setDefaults({ ...empty, ...value.defaults });
    }
    return value;
  }, [request]);
  useEffect(() => {
    mounted.current = true;
    const run = ++generation.current;
    setLoading(true);
    load()
      .catch((cause) => {
        if (run === generation.current) setError(settingsError(cause));
      })
      .finally(() => {
        if (run === generation.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, [load]);
  useEffect(() => {
    if (!active) {
      setKey("");
      setDisconnect(false);
      setOutput(null);
    }
  }, [active]);
  async function act(task: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function save() {
    if (!state) return;
    const secret = key;
    setKey("");
    await act(async () => {
      await request("voice/settings", "POST", {
        revision: state.revision,
        ...(secret ? { api_key: secret } : {}),
        defaults,
      });
      setCatalog(null);
      setOutput(null);
      const saved = await load();
      await onChanged();
      try {
        const current = await request<Catalog>("voice/catalog", "POST", {
          revision: saved.revision,
        });
        if (mounted.current) setCatalog(current);
      } catch {
        throw new Error(
          "La conexión se guardó. No pudimos actualizar el catálogo; pulsa Consultar catálogo antes de preparar una propuesta.",
        );
      }
    });
  }
  async function refresh() {
    if (!state) return;
    await act(async () => {
      const value = await request<Catalog>("voice/catalog", "POST", {
        revision: state.revision,
      });
      setCatalog(value);
    });
  }
  async function upload(file: File) {
    await act(async () => {
      const mime = saraUploadMime(file.name, file.type);
      if (!mime.startsWith("audio/"))
        throw new Error("Selecciona un audio WebM, Ogg, MP3, WAV o MP4.");
      const data_base64 = await saraFileBase64(file);
      setAttachment(
        await request<{ attachment_id: string; filename: string }>(
          "voice/attachments",
          "POST",
          { filename: file.name, mime_type: mime, data_base64 },
        ),
      );
    });
  }
  async function prepare() {
    await act(async () => {
      let args: Record<string, unknown>;
      switch (operation) {
        case "tts":
          args = {
            text: text.trim(),
            voice_id: defaults.voice_id,
            model_id: defaults.model_id,
          };
          break;
        case "stt":
          if (!attachment) throw new Error("Adjunta un audio primero.");
          args = { attachment_id: attachment.attachment_id };
          break;
        case "agent_session":
          args = { agent_id: defaults.agent_id };
          break;
        default: {
          const recipient = contacts.find((c) => c.id === contactId);
          if (!recipient) throw new Error("Selecciona un cliente del CRM.");
          args = {
            agent_id: defaults.agent_id,
            phone_number_id: defaults.phone_number_id,
            contact_id: recipient.id,
            expected_phone: recipient.phone,
          };
        }
      }
      const value = await request<ActionResult>("hermes/actions", "POST", {
        action: "voice.execute",
        arguments: { operation, arguments: args },
      });
      setOutput(value);
      setOutputKey((n) => n + 1);
    });
  }
  const available = !!state?.configured && state.verified && state.enabled;
  const catalogFor = (field: keyof Defaults) =>
    catalog?.[
      {
        voice_id: "voices",
        model_id: "models",
        agent_id: "agents",
        phone_number_id: "phone_numbers",
      }[field] as "voices"
    ] ?? [];
  return (
    <section
      className="elevenlabs-panel"
      aria-labelledby="elevenlabs-title"
      aria-busy={busy || loading}
    >
      <div className="settings-section-heading">
        <h3 id="elevenlabs-title">ElevenLabs</h3>
        <span className="social-status">
          {loading
            ? "Consultando…"
            : !state?.enabled
              ? "Pausado"
              : state?.verified
                ? "Verificado"
                : state?.configured
                  ? "Requiere verificación"
                  : "Sin conectar"}
        </span>
      </div>
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
        className="elevenlabs-form"
      >
        <label htmlFor="elevenlabs-key">
          Clave de API
          <input
            id="elevenlabs-key"
            type="password"
            autoComplete="new-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            maxLength={512}
            placeholder={
              state?.configured
                ? "Guardada · escribe solo para reemplazar"
                : "Nueva clave"
            }
            disabled={busy || loading}
          />
        </label>
        <div className="elevenlabs-fields">
          {(Object.keys(labels) as (keyof Defaults)[]).map((field) => (
            <label key={field} htmlFor={`elevenlabs-${field}`}>
              {labels[field]}
              <input
                id={`elevenlabs-${field}`}
                list={`elevenlabs-options-${field}`}
                value={defaults[field]}
                maxLength={128}
                onChange={(e) =>
                  setDefaults((old) => ({ ...old, [field]: e.target.value }))
                }
                disabled={busy || loading}
              />
              <datalist id={`elevenlabs-options-${field}`}>
                {catalogFor(field).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
              </datalist>
            </label>
          ))}
        </div>
        <div className="social-actions">
          <button className="crm-button" disabled={busy || loading || !state}>
            Guardar conexión
          </button>
          <button
            type="button"
            className="crm-button crm-secondary"
            onClick={() => void refresh()}
            disabled={busy || !state?.configured}
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
      </form>
      {catalog && (
        <p className="settings-meta" role="status">
          {catalog.voices.length} voces · {catalog.models.length} modelos ·{" "}
          {catalog.agents.length} agentes · {catalog.phone_numbers.length}{" "}
          líneas{catalog.limited ? " · Catálogo parcial" : ""}
          {catalog.errors.length
            ? ` · No disponible: ${catalog.errors.map((name) => catalogLabels[name] ?? name).join(", ")}`
            : ""}
        </p>
      )}
      {disconnect && (
        <div
          className="elevenlabs-disconnect"
          role="group"
          aria-label="Confirmar desconexión de ElevenLabs"
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
                void act(async () => {
                  await request("voice/disconnect", "POST", {
                    revision: state?.revision,
                  });
                  setCatalog(null);
                  setDisconnect(false);
                  setKey("");
                  setOutput(null);
                  await load();
                  await onChanged();
                })
              }
            >
              Confirmar desconexión
            </button>
          </div>
        </div>
      )}
      <div className="elevenlabs-workspace">
        <h4>Voz y agentes</h4>
        <div
          className="elevenlabs-modes"
          role="group"
          aria-label="Operación de voz"
        >
          {[
            ["tts", "Crear audio"],
            ["stt", "Transcribir"],
            ["agent_session", "Agente de voz"],
            ["outbound_call", "Llamar"],
          ].map(([id, label]) => (
            <button
              type="button"
              key={id}
              aria-pressed={operation === id}
              disabled={busy}
              onClick={() => {
                setOperation(id);
                if (id === "outbound_call")
                  void act(async () => {
                    const value = await request<{ contacts: Contact[] }>(
                      "workspace",
                    );
                    setContacts(value.contacts);
                  });
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void prepare();
          }}
        >
          {operation === "tts" && (
            <label htmlFor="elevenlabs-text">
              Texto del audio
              <textarea
                id="elevenlabs-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={1500}
                required
                disabled={busy}
              />
            </label>
          )}
          {operation === "stt" && (
            <>
              <label htmlFor="elevenlabs-audio">
                Audio · máximo 512 KiB
                <input
                  ref={fileInput}
                  id="elevenlabs-audio"
                  type="file"
                  accept=".webm,.ogg,.mp3,.wav,.mp4,.m4a,audio/*"
                  disabled={busy}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file) void upload(file);
                  }}
                />
              </label>
              {attachment && (
                <p className="settings-meta">{attachment.filename}</p>
              )}
            </>
          )}
          {operation === "agent_session" && (
            <p className="settings-meta">
              Agente de ElevenLabs, independiente de Sara IA. El micrófono se
              solicita solo después de aprobar e iniciar la sesión.
            </p>
          )}
          {operation === "outbound_call" && (
            <label htmlFor="elevenlabs-recipient">
              Cliente del CRM
              <select
                id="elevenlabs-recipient"
                value={contactId}
                onChange={(e) => setContactId(e.target.value)}
                required
                disabled={busy}
              >
                <option value="">Selecciona un cliente</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} · {c.phone}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            className="crm-button"
            disabled={
              !available ||
              busy ||
              loading ||
              (operation === "tts" &&
                (!text.trim() || !defaults.voice_id || !defaults.model_id)) ||
              (operation === "stt" && !attachment) ||
              (operation === "agent_session" && !defaults.agent_id) ||
              (operation === "outbound_call" &&
                (!contactId || !defaults.agent_id || !defaults.phone_number_id))
            }
          >
            Preparar propuesta
          </button>
        </form>
        <p className="settings-meta">
          Operaciones de pago. Revisa y aprueba cada propuesta antes de
          ejecutarla.
        </p>
        {active && output && (
          <ActionOutput
            key={outputKey}
            value={output}
            request={request}
            onChanged={onChanged}
          />
        )}
      </div>
    </section>
  );
}
