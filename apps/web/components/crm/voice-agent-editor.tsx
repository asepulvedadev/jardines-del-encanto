"use client";

import { useId, useRef, useState } from "react";
import type { RetellSchema } from "./retell-schema";
import { VoiceSchemaEditor } from "./voice-schema-editor";
import type { VoiceSchemaDrafts } from "./voice-schema-model";
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
  onSubmit: (
    endpoint: string,
    arguments_: Record<string, unknown>,
  ) => Promise<void>;
  onCancel: () => void;
  onCreateModel?: () => void;
};

// The workspace keys this form by resource identity/version to isolate drafts.
export function VoiceAgentEditor({
  kind,
  record,
  schemas,
  voices,
  models,
  busy,
  onSubmit,
  onCancel,
  onCreateModel,
}: VoiceAgentEditorProps) {
  const id = useId();
  const [values, setValues] = useState(() => voiceInitialValues(kind, record));
  const [replacements, setReplacements] = useState<VoiceReplacements>({});
  const [advancedDrafts, setAdvancedDrafts] = useState<VoiceSchemaDrafts>({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pending = useRef(false);
  const endpoint = `${record ? "update" : "create"}${kind === "agent" ? "Agent" : "RetellLLM"}`;
  const schema = schemas[endpoint];
  const fields = schema ? voiceEditorFields(kind, schema, record) : [];
  const disabled = busy || submitting;
  const voiceOptions = voiceCatalogOptions(voices, "voice_id", "voice_name");
  const modelOptions = voiceCatalogOptions(models, "llm_id", "agent_name");
  const engine = record?.response_engine;
  const engineType =
    engine &&
    typeof engine === "object" &&
    !Array.isArray(engine) &&
    "type" in engine &&
    typeof engine.type === "string"
      ? engine.type
      : "No disponible";
  const title =
    kind === "agent"
      ? record
        ? "Editar agente"
        : "Nuevo agente"
      : record
        ? "Editar instrucciones"
        : "Nuevas instrucciones";
  function update(key: string, value: string) {
    setValues((previous) => ({ ...previous, [key]: value }));
    setError("");
  }
  function replace(key: keyof VoiceReplacements, checked: boolean) {
    setReplacements((previous) => ({ ...previous, [key]: checked }));
    // Replacement is always a fresh, explicit full draft, never a cached fragment.
    update(key === "response_engine" ? "llm_id" : key, "");
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
        advancedDrafts,
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
    } catch {
      setError(
        "No se pudo preparar la revisión. Conservamos tu borrador; vuelve a intentarlo.",
      );
    } finally {
      pending.current = false;
      setSubmitting(false);
    }
  }
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
          Los cambios se enviarán a revisión antes de aplicarse en Retell.
        </p>
      </header>
      {!schema || !fields.length ? (
        <p role="alert">
          El esquema aprobado no está disponible para este formulario. Usa el
          catálogo de operaciones cuando esté disponible.
        </p>
      ) : null}
      {record ? (
        <p className="voice-muted">
          Lectura parcial. Solo se enviarán los campos modificados; el resto se
          conserva en Retell.
        </p>
      ) : null}
      <fieldset className="voice-editor-fields" disabled={disabled || !schema}>
        <legend className="sr-only">
          Configuración {kind === "agent" ? "del agente" : "de instrucciones"}
        </legend>
        {fields
          .filter(
            (field) =>
              !advancedDrafts[field.key]?.enabled &&
              !(
                kind === "instructions" &&
                advancedDrafts.model_config?.enabled &&
                ["model", "temperature"].includes(field.key)
              ),
          )
          .map((field) => {
            const fullText =
              field.key === "general_prompt" || field.key === "begin_message";
            const replacementKey = field.key as keyof VoiceReplacements;
            const current = record?.[field.key];
            const currentText =
              typeof current === "string"
                ? current
                : "No disponible en esta lectura parcial.";
            const options = (field.schema.enum ?? []).filter(
              (value): value is string => typeof value === "string",
            );
            const value = values[field.key] ?? "";
            const controlId = `${id}-${field.key}`;
            return (
              <div key={field.key} className="voice-field">
                {record && fullText ? (
                  <>
                    <label htmlFor={`${controlId}-preview`}>
                      {field.key === "general_prompt"
                        ? "Instrucciones actuales (lectura parcial)"
                        : "Mensaje inicial actual (lectura parcial)"}
                    </label>
                    <textarea
                      className="crm-input voice-textarea voice-preview"
                      id={`${controlId}-preview`}
                      readOnly
                      rows={3}
                      value={currentText}
                    />
                    <p className="voice-muted" id={`${controlId}-hint`}>
                      La lectura puede estar recortada. Para cambiarla, escribe
                      el texto completo desde cero. El fragmento no se
                      reenviará.
                    </p>
                    <label className="voice-checkbox">
                      <input
                        type="checkbox"
                        name={`replace_${field.key}`}
                        checked={!!replacements[replacementKey]}
                        onChange={(event) =>
                          replace(replacementKey, event.target.checked)
                        }
                      />
                      {field.key === "general_prompt"
                        ? "Reemplazar instrucciones"
                        : "Reemplazar mensaje inicial"}
                    </label>
                  </>
                ) : null}
                {!record || !fullText || replacements[replacementKey] ? (
                  <>
                    <label htmlFor={controlId}>{field.label}</label>
                    {field.multiline ? (
                      <textarea
                        className="crm-input voice-textarea"
                        id={controlId}
                        name={field.key}
                        rows={field.key === "general_prompt" ? 8 : 3}
                        value={value}
                        aria-describedby={
                          record ? `${controlId}-hint` : undefined
                        }
                        minLength={field.schema.minLength}
                        maxLength={field.schema.maxLength}
                        onChange={(event) =>
                          update(field.key, event.target.value)
                        }
                      />
                    ) : field.key === "voice_id" ? (
                      <>
                        <select
                          className="crm-input"
                          id={controlId}
                          name="voice_id"
                          value={value}
                          onChange={(event) =>
                            update("voice_id", event.target.value)
                          }
                        >
                          <option value="">Selecciona una voz</option>
                          {value &&
                          !voiceOptions.some(
                            (option) => option.value === value,
                          ) ? (
                            <option value={value}>Voz actual</option>
                          ) : null}
                          {voiceOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                        <details className="voice-resource-id">
                          <summary>Usar un identificador de voz</summary>
                          <label htmlFor={`${controlId}-manual`}>
                            Identificador exacto
                          </label>
                          <input
                            className="crm-input"
                            id={`${controlId}-manual`}
                            name="voice_id_manual"
                            value={value}
                            onChange={(event) =>
                              update("voice_id", event.target.value)
                            }
                          />
                        </details>
                      </>
                    ) : options.length ? (
                      <select
                        className="crm-input"
                        id={controlId}
                        name={field.key}
                        value={value}
                        onChange={(event) =>
                          update(field.key, event.target.value)
                        }
                      >
                        <option value="">
                          {record
                            ? "Mantener valor actual"
                            : "Selecciona un valor"}
                        </option>
                        {value && !options.includes(value) ? (
                          <option value={value} disabled>
                            Actual: {value}
                          </option>
                        ) : null}
                        {options.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="crm-input"
                        id={controlId}
                        name={field.key}
                        type={
                          ["integer", "number"].includes(
                            String(field.schema.type),
                          )
                            ? "number"
                            : "text"
                        }
                        step={field.schema.type === "integer" ? 1 : "any"}
                        min={field.schema.minimum}
                        max={field.schema.maximum}
                        minLength={field.schema.minLength}
                        maxLength={field.schema.maxLength}
                        value={value}
                        onChange={(event) =>
                          update(field.key, event.target.value)
                        }
                      />
                    )}
                    {field.key === "begin_message" ? (
                      <p className="voice-muted">
                        Un reemplazo vacío hará que el agente espere a que la
                        persona hable primero.
                      </p>
                    ) : null}
                  </>
                ) : null}
              </div>
            );
          })}
        {kind === "agent" && !advancedDrafts.response_engine?.enabled ? (
          <section
            className="voice-engine"
            aria-labelledby={`${id}-engine-title`}
          >
            <h4 id={`${id}-engine-title`}>Instrucciones vinculadas</h4>
            {record ? (
              <>
                <p className="voice-muted">
                  Motor actual: {engineType}. No cambia al editar otros campos.
                </p>
                <label className="voice-checkbox">
                  <input
                    type="checkbox"
                    name="replace_response_engine"
                    checked={!!replacements.response_engine}
                    onChange={(event) =>
                      replace("response_engine", event.target.checked)
                    }
                  />
                  Cambiar motor de respuesta a Retell LLM
                </label>
                {replacements.response_engine ? (
                  <p className="voice-muted">
                    Esta acción reemplaza el motor actual por las instrucciones
                    cuyo ID indiques.
                  </p>
                ) : null}
              </>
            ) : null}
            {!record || replacements.response_engine ? (
              <div className="voice-field">
                <label htmlFor={`${id}-llm-id`}>
                  Instrucciones Retell LLM (ID)
                </label>
                <input
                  className="crm-input"
                  id={`${id}-llm-id`}
                  name="llm_id"
                  list={`${id}-models`}
                  value={values.llm_id ?? ""}
                  onChange={(event) => update("llm_id", event.target.value)}
                />
                <datalist id={`${id}-models`}>
                  {modelOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </datalist>
                <p className="voice-muted">
                  {modelOptions.length
                    ? "Selecciona unas instrucciones consultadas o escribe un ID exacto."
                    : "No hay instrucciones cargadas. Escribe un ID existente o crea las instrucciones primero."}
                </p>
                {!record && onCreateModel ? (
                  <button
                    className="crm-button"
                    type="button"
                    onClick={onCreateModel}
                  >
                    Crear instrucciones primero
                  </button>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}
        {kind === "instructions" &&
        !fields.some((field) => field.key === "model") ? (
          <p className="voice-muted">
            El tipo de modelo actual no está disponible en el editor guiado. Se
            conservará sin cambios; usa el catálogo para configuraciones
            avanzadas.
          </p>
        ) : null}
      </fieldset>
      {schema ? (
        <VoiceSchemaEditor
          schema={schema}
          record={record}
          drafts={advancedDrafts}
          onChange={(next) => {
            setAdvancedDrafts(next);
            setError("");
          }}
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
          disabled={disabled || !schema || !fields.length}
        >
          {kind === "agent" && !record
            ? "Revisar nuevo agente"
            : "Revisar cambios"}
        </button>
      </footer>
    </form>
  );
}
