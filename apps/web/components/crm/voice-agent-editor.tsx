"use client";

import { useId, useRef, useState } from "react";
import type { RetellSchema } from "./retell-schema";
import { VoiceSchemaEditor } from "./voice-schema-editor";
import {
  voiceHydrateField,
  voiceSchemaProperties,
  voiceSchemaNullable,
  type VoiceSchemaDrafts,
} from "./voice-schema-model";
import {
  voiceCatalogOptions,
  voiceEditorArguments,
  voiceEditorFields,
  voiceInitialValues,
  type VoiceEditorKind,
  type VoiceReplacements,
} from "./voice-agent-model";

export type VoiceAgentEditorProps = {
  kind: VoiceEditorKind;
  record?: Record<string, unknown>;
  schemas: Record<string, RetellSchema>;
  voices: Record<string, unknown>[];
  models: Record<string, unknown>[];
  busy: boolean;
  completeFields?: string[];
  blockedFields?: Record<string, string>;
  onSubmit: (
    endpoint: string,
    arguments_: Record<string, unknown>,
  ) => Promise<void>;
  onCancel: () => void;
  onCreateModel?: () => void;
};

// The workspace keys this editor by kind, resource identity and version.
export function VoiceAgentEditor({
  kind,
  record,
  schemas,
  voices,
  models,
  busy,
  completeFields = [],
  blockedFields = {},
  onSubmit,
  onCancel,
  onCreateModel,
}: VoiceAgentEditorProps) {
  const id = useId();
  const endpoint = `${record ? "update" : "create"}${kind === "agent" ? "Agent" : "RetellLLM"}`;
  const schema = schemas[endpoint];
  const body = schema ? voiceSchemaProperties(schema).requestBody : undefined;
  const properties = body ? voiceSchemaProperties(body) : {};
  const fields = schema ? voiceEditorFields(kind, schema, record) : [];
  const state = (key: string) =>
    body
      ? voiceHydrateField(body, key, record, completeFields, blockedFields)
      : { editable: false, reason: "El esquema no está disponible." };
  const [values, setValues] = useState<Record<string, string>>(() => {
    if (!record) return {};
    const initial = voiceInitialValues(kind, record);
    const allowed =
      kind === "agent"
        ? ["agent_name", "voice_id"]
        : ["general_prompt", "begin_message"];
    return Object.fromEntries(
      allowed.flatMap((key) => {
        const hydrated = state(key);
        return hydrated.editable
          ? [[key, hydrated.draft?.raw ?? initial[key] ?? ""]]
          : [];
      }),
    );
  });
  const [replacements, setReplacements] = useState<VoiceReplacements>({});
  const [drafts, setDrafts] = useState<VoiceSchemaDrafts>({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pending = useRef(false);
  const disabled = busy || submitting;
  const voiceOptions = voiceCatalogOptions(voices, "voice_id", "voice_name");
  const modelOptions = voiceCatalogOptions(models, "llm_id", "agent_name");
  const title =
    kind === "agent"
      ? record
        ? "Editar agente"
        : "Nuevo agente"
      : record
        ? "Prompt e instrucciones"
        : "Nuevas instrucciones";
  function update(key: string, value: string) {
    if (record && !state(key).editable) return;
    setValues((previous) => ({ ...previous, [key]: value }));
    if (key === "general_prompt" || key === "begin_message") {
      setReplacements((previous) => ({ ...previous, [key]: true }));
      setDrafts((previous) => ({ ...previous, [key]: { enabled: false } }));
    }
    setError("");
  }
  function explicitText(
    key: "general_prompt" | "begin_message",
    value: null | string,
  ) {
    if (disabled || (record && !state(key).editable) || !body) return;
    setDrafts((previous) => ({
      ...previous,
      [key]:
        value === null
          ? { enabled: true, null: true }
          : { enabled: true, raw: value },
    }));
    setError("");
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || pending.current || !schema) return;
    let proposal: ReturnType<typeof voiceEditorArguments>;
    try {
      proposal = voiceEditorArguments(
        kind,
        schema,
        record,
        values,
        replacements,
        drafts,
        { completeFields, blockedFields },
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Revisa los campos del formulario.",
      );
      return;
    }
    pending.current = true;
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(proposal.endpoint, proposal.arguments);
    } catch (cause) {
      const oversize =
        cause instanceof Error &&
        /16\s?(?:KiB|KB)|demasiado grande|excede.{0,30}(?:tama[nñ]o|l[ií]mite)|supera.{0,30}(?:tama[nñ]o|l[ií]mite)|too large/i.test(
          cause.message,
        );
      setError(
        oversize
          ? "El borrador supera el límite de tamaño permitido. Reduce su contenido; no se ha recortado ni aplicado."
          : "No se pudo preparar la revisión. Conservamos tu borrador; vuelve a intentarlo.",
      );
    } finally {
      pending.current = false;
      setSubmitting(false);
    }
  }
  const nameEditable = !record || state("agent_name").editable;
  const voiceEditable = !record || state("voice_id").editable;
  const visibleVoice = values.voice_id ?? "";
  return (
    <form
      className="voice-editor"
      aria-labelledby={`${id}-title`}
      aria-busy={disabled}
      onSubmit={submit}
    >
      <header className="voice-editor-header">
        <h3 id={`${id}-title`}>{title}</h3>
        <p className="voice-muted">
          {kind === "instructions"
            ? "Define qué hace el agente, cómo habla y qué debe evitar. Los cambios requieren revisión antes de aplicarse."
            : "Edita los ajustes y revisa los cambios antes de aplicarlos en Retell."}
        </p>
      </header>
      {!schema ? (
        <p role="alert">
          El esquema aprobado no está disponible para este formulario.
        </p>
      ) : null}
      {record && !completeFields.length ? (
        <p className="voice-schema-warning">
          Esta lectura está incompleta. Actualiza la configuración completa para
          editarla con seguridad.
        </p>
      ) : null}
      <fieldset className="voice-editor-fields" disabled={disabled || !schema}>
        <legend className="sr-only">Configuración principal</legend>
        {kind === "agent" ? (
          <>
            <div className="voice-field" data-voice-field="agent_name">
              <label htmlFor={`${id}-agent-name`}>Nombre del agente</label>
              <input
                className="crm-input"
                id={`${id}-agent-name`}
                name="agent_name"
                value={values.agent_name ?? ""}
                readOnly={!nameEditable}
                onChange={(event) => update("agent_name", event.target.value)}
              />
              {!nameEditable ? (
                <p className="voice-muted">{state("agent_name").reason}</p>
              ) : null}
            </div>
            <div className="voice-field" data-voice-field="voice_id">
              <label htmlFor={`${id}-voice`}>Voz</label>
              <select
                className="crm-input"
                id={`${id}-voice`}
                name="voice_id"
                value={visibleVoice}
                disabled={!voiceEditable}
                onChange={(event) => update("voice_id", event.target.value)}
              >
                <option value="">Selecciona una voz</option>
                {visibleVoice &&
                !voiceOptions.some(
                  (option) => option.value === visibleVoice,
                ) ? (
                  <option value={visibleVoice}>Voz actual</option>
                ) : null}
                {voiceOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {voiceEditable ? (
                <details className="voice-schema-reference">
                  <summary>Usar un identificador de voz</summary>
                  <label htmlFor={`${id}-voice-manual`}>
                    Identificador exacto de la voz
                  </label>
                  <input
                    className="crm-input"
                    id={`${id}-voice-manual`}
                    name="voice_id_manual"
                    value={visibleVoice}
                    onChange={(event) => update("voice_id", event.target.value)}
                  />
                </details>
              ) : (
                <p className="voice-muted">{state("voice_id").reason}</p>
              )}
            </div>
            {!record ? (
              <div className="voice-field">
                <label htmlFor={`${id}-language`}>Idioma</label>
                <select
                  className="crm-input"
                  name="language"
                  id={`${id}-language`}
                  value={values.language ?? ""}
                  onChange={(event) => update("language", event.target.value)}
                >
                  <option value="">Usar idioma del proveedor</option>
                  {fields
                    .find((field) => field.key === "language")
                    ?.schema.enum?.filter(
                      (option): option is string => typeof option === "string",
                    )
                    .map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                </select>
              </div>
            ) : null}
            {!record && !drafts.response_engine?.enabled ? (
              <section className="voice-engine">
                <h4>Instrucciones del agente</h4>
                <label htmlFor={`${id}-llm`}>Instrucciones Retell LLM</label>
                <select
                  className="crm-input"
                  id={`${id}-llm`}
                  name="llm_id"
                  value={values.llm_id ?? ""}
                  onChange={(event) => update("llm_id", event.target.value)}
                >
                  <option value="">Selecciona las instrucciones</option>
                  {values.llm_id &&
                  !modelOptions.some(
                    (option) => option.value === values.llm_id,
                  ) ? (
                    <option value={values.llm_id}>
                      Instrucciones elegidas
                    </option>
                  ) : null}
                  {modelOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label === option.value
                        ? "Instrucciones Retell LLM"
                        : option.label}
                    </option>
                  ))}
                </select>
                <details className="voice-schema-reference">
                  <summary>Usar un identificador de instrucciones</summary>
                  <label htmlFor={`${id}-llm-manual`}>
                    Identificador exacto de las instrucciones
                  </label>
                  <input
                    className="crm-input"
                    id={`${id}-llm-manual`}
                    name="llm_id_manual"
                    value={values.llm_id ?? ""}
                    onChange={(event) => update("llm_id", event.target.value)}
                  />
                </details>
                {onCreateModel ? (
                  <button
                    className="crm-button"
                    type="button"
                    onClick={onCreateModel}
                  >
                    Crear instrucciones primero
                  </button>
                ) : null}
              </section>
            ) : null}
          </>
        ) : (
          <>
            {!record && !drafts.model_config?.enabled ? (
              <div className="voice-field">
                <label htmlFor={`${id}-model`}>Modelo de respuesta</label>
                <select
                  className="crm-input"
                  id={`${id}-model`}
                  name="model"
                  value={values.model ?? ""}
                  onChange={(event) => update("model", event.target.value)}
                >
                  <option value="">Selecciona un modelo</option>
                  {fields
                    .find((field) => field.key === "model")
                    ?.schema.enum?.filter(
                      (option): option is string => typeof option === "string",
                    )
                    .map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                </select>
              </div>
            ) : null}
            {(["general_prompt", "begin_message"] as const).map((key) => {
              const hydrated = state(key);
              const editable = !record || hydrated.editable;
              const blocked =
                hydrated.reasonCode === "blocked" ||
                hydrated.reasonCode === "invalid_snapshot";
              const explicit = drafts[key]?.enabled;
              const original =
                !blocked && typeof record?.[key] === "string"
                  ? String(record[key])
                  : "";
              const value = explicit
                ? drafts[key].null
                  ? ""
                  : (drafts[key].raw ?? "")
                : editable
                  ? (values[key] ?? "")
                  : original;
              return (
                <div
                  className="voice-field voice-prompt-field"
                  data-voice-field={key}
                  key={key}
                >
                  <label htmlFor={`${id}-${key}`}>
                    {key === "general_prompt"
                      ? "Prompt del agente"
                      : "Saludo inicial"}
                  </label>
                  <textarea
                    className="crm-input voice-textarea"
                    id={`${id}-${key}`}
                    name={key}
                    rows={key === "general_prompt" ? 14 : 4}
                    value={value}
                    readOnly={!editable}
                    aria-describedby={`${id}-${key}-hint`}
                    onChange={(event) => update(key, event.target.value)}
                  />
                  <p id={`${id}-${key}-hint`} className="voice-muted">
                    {!editable
                      ? hydrated.reason
                      : explicit && drafts[key].null
                        ? key === "begin_message"
                          ? "El agente generará un saludo dinámico."
                          : "Se guardará sin instrucciones."
                        : "Edita el texto completo. Solo se enviará si lo modificas."}
                  </p>
                  {editable ? (
                    <div className="voice-editor-actions">
                      {properties[key] &&
                      voiceSchemaNullable(properties[key]) ? (
                        <button
                          className="crm-button"
                          type="button"
                          onClick={() => explicitText(key, null)}
                        >
                          {key === "general_prompt"
                            ? "Dejar sin instrucciones"
                            : "Generar saludo dinámico"}
                        </button>
                      ) : null}
                      <button
                        className="crm-button"
                        type="button"
                        onClick={() => explicitText(key, "")}
                      >
                        {key === "general_prompt"
                          ? "Vaciar prompt"
                          : "Esperar a la persona"}
                      </button>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </>
        )}
      </fieldset>
      {schema ? (
        <VoiceSchemaEditor
          schema={schema}
          record={record}
          completeFields={completeFields}
          blockedFields={blockedFields}
          drafts={drafts}
          onChange={(next) => {
            setDrafts(next);
            setError("");
          }}
          exclude={
            kind === "agent"
              ? ["agent_name", "voice_id", ...(!record ? ["language"] : [])]
              : [
                  "general_prompt",
                  "begin_message",
                  ...(!record ? ["model"] : []),
                ]
          }
          disabled={disabled}
          voices={voices}
          models={models}
        />
      ) : null}
      {error ? (
        <p className="voice-error" role="alert">
          {error}
        </p>
      ) : null}
      <footer className="voice-editor-actions">
        <button
          className="crm-button"
          type="button"
          disabled={disabled}
          onClick={onCancel}
        >
          Cancelar
        </button>
        <button
          className="crm-button crm-button-primary"
          type="submit"
          disabled={disabled || !schema}
        >
          {kind === "agent" && !record
            ? "Revisar nuevo agente"
            : "Revisar cambios"}
        </button>
      </footer>
    </form>
  );
}
