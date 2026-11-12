"use client";

import { useId, useState } from "react";
import {
  voiceAnySchemas,
  voiceEmptyDraft,
  voicePrivateUrl,
  voiceSchemaComplex,
  voiceSchemaHint,
  voiceSchemaInventory,
  voiceSchemaLabel,
  voiceSchemaOptionLabel,
  voiceSchemaNullable,
  voiceSchemaProperties,
  voiceSchemaResolve,
  voiceSchemaType,
  voiceSchemaVariants,
  voiceSensitivePath,
  type VoiceSchema,
  type VoiceSchemaDraft,
  type VoiceSchemaDrafts,
} from "./voice-schema-model";

export type VoiceSchemaEditorProps = {
  schema: VoiceSchema;
  record?: Record<string, unknown>;
  drafts: VoiceSchemaDrafts;
  onChange: (drafts: VoiceSchemaDrafts) => void;
  exclude?: string[];
  disabled?: boolean;
  voices?: Record<string, unknown>[];
  models?: Record<string, unknown>[];
};
type ControlProps = {
  schema: VoiceSchema;
  path: string;
  id: string;
  draft?: VoiceSchemaDraft;
  onChange: (draft: VoiceSchemaDraft) => void;
  required?: boolean;
  current?: unknown;
  depth?: number;
  voices?: Record<string, unknown>[];
  models?: Record<string, unknown>[];
};
function variantLabel(schema: VoiceSchema, index: number): string {
  const properties = voiceSchemaProperties(schema);
  const discriminator = voiceSchemaResolve(properties.type ?? {}).enum;
  const engineLabels: Record<string, string> = {
    "retell-llm": "Instrucciones Retell LLM",
    "conversation-flow": "Flujo de conversación",
    "custom-llm": "Modelo personalizado",
    cascading: "Modelo de texto con voz separada",
    s2s: "Modelo de voz a voz",
    duplex: "Voz dúplex con modelo de apoyo",
  };
  return (
    schema.title ??
    (discriminator?.length === 1
      ? (engineLabels[String(discriminator[0])] ?? String(discriminator[0]))
      : ({
          object: "Configuración",
          array: "Lista",
          string: "Texto",
          number: "Número",
          boolean: "Sí o no",
          null: "Sin valor",
        }[voiceSchemaType(schema)] ?? `Opción ${index + 1}`))
  );
}
function VoiceSnapshot({
  value,
  path,
  depth = 0,
}: {
  value: unknown;
  path: string;
  depth?: number;
}) {
  if (voiceSensitivePath(path))
    return <span>Contenido privado oculto. Adminístralo en Retell.</span>;
  if (depth > 4)
    return <span>Contenido adicional no mostrado (lectura parcial).</span>;
  if (Array.isArray(value))
    return (
      <ul>
        {value.slice(0, 6).map((entry, index) => (
          <li key={index}>
            <VoiceSnapshot
              value={entry}
              path={`${path}.${index}`}
              depth={depth + 1}
            />
          </li>
        ))}
        {value.length > 6 ? <li>Más elementos no mostrados.</li> : null}
      </ul>
    );
  if (value && typeof value === "object")
    return (
      <dl>
        {Object.entries(value)
          .slice(0, 10)
          .map(([key, entry]) => (
            <div key={key}>
              <dt>{voiceSchemaLabel(key)}</dt>
              <dd>
                <VoiceSnapshot
                  value={entry}
                  path={`${path}.${key}`}
                  depth={depth + 1}
                />
              </dd>
            </div>
          ))}
      </dl>
    );
  if (typeof value === "string" && voicePrivateUrl(value))
    return (
      <span>
        Dirección privada oculta. Adminístrala directamente en Retell.
      </span>
    );
  return (
    <span>
      {value === undefined
        ? "No disponible en la lectura parcial."
        : value === null
          ? "Sin valor"
          : typeof value === "boolean"
            ? value
              ? "Activo"
              : "Inactivo"
            : String(value).slice(0, 500)}
    </span>
  );
}
function VoiceControl({
  schema: input,
  path,
  id,
  draft,
  onChange,
  required,
  current,
  depth = 0,
  voices,
  models,
}: ControlProps) {
  const schema = voiceSchemaResolve(input);
  const key = path.split(".").at(-1) ?? path;
  const label = /^\d+$/.test(key)
    ? `${voiceSchemaLabel(path.split(".").at(-2) ?? "value")}: elemento ${Number(key) + 1}`
    : voiceSchemaLabel(key);
  if (voiceSensitivePath(path) || schema.readOnly)
    return (
      <p className="voice-schema-blocked">
        {label}: no se recopila aquí. Administra credenciales, autenticación y
        encabezados privados directamente en Retell.
      </p>
    );
  if (depth > 24)
    return (
      <p className="voice-schema-blocked">
        Esta configuración supera la profundidad admitida. Adminístrala
        directamente en Retell.
      </p>
    );
  const base = draft ?? { enabled: false };
  const update = (next: Partial<VoiceSchemaDraft>) =>
    onChange({ ...base, ...next, enabled: true });
  const changeScalar = (raw: string) =>
    voicePrivateUrl(raw)
      ? onChange({ enabled: true, blocked: true })
      : update({ raw, blocked: false });
  const type = voiceSchemaType(schema);
  const variants = voiceSchemaVariants(schema);
  const choices = variants.length
    ? variants
    : type === "any"
      ? voiceAnySchemas
      : [];
  const options = (schema.enum ?? []).filter((entry) => entry !== null);
  const hint = voiceSchemaHint(schema);
  const raw =
    base.raw ??
    (typeof current === "string" ||
    typeof current === "number" ||
    typeof current === "boolean"
      ? String(current)
      : "");
  const childProps = { voices, models, depth: depth + 1 };
  let control;
  if (base.null)
    control = <p className="voice-muted">Se enviará sin valor (null).</p>;
  else if (choices.length) {
    const selected =
      base.branch === undefined ? undefined : choices[base.branch];
    const nested = selected ? { ...base, branch: undefined } : undefined;
    control = (
      <>
        <label htmlFor={`${id}-variant`}>
          {label}: tipo de configuración{required ? " *" : ""}
        </label>
        <select
          className="crm-input"
          id={`${id}-variant`}
          name={`${path}.__variant`}
          value={base.branch === undefined ? "" : String(base.branch)}
          onChange={(event) => {
            const branch = Number(event.target.value);
            onChange(
              event.target.value === "" || !choices[branch]
                ? { enabled: true }
                : { ...voiceEmptyDraft(choices[branch]), branch },
            );
          }}
        >
          <option value="">Selecciona el tipo</option>
          {choices.map((choice, index) => (
            <option key={index} value={index}>
              {variantLabel(choice, index)}
            </option>
          ))}
        </select>
        {selected ? (
          <VoiceControl
            {...childProps}
            schema={selected}
            path={path}
            id={`${id}-choice`}
            draft={nested}
            onChange={(value) => onChange({ ...value, branch: base.branch })}
            required={required}
          />
        ) : null}
      </>
    );
  } else if (type === "object") {
    const properties = voiceSchemaProperties(schema);
    const entries = base.entries ?? [];
    const dynamic =
      schema.additionalProperties !== false &&
      (schema.additionalProperties !== undefined ||
        !Object.keys(properties).length);
    control = (
      <div className="voice-schema-object">
        {Object.entries(properties).map(([name, property]) => {
          const child = base.children?.[name];
          const complex = voiceSchemaComplex(property, name);
          const childRequired = schema.required?.includes(name);
          const childPath = `${path}.${name}`;
          if (voiceSensitivePath(childPath))
            return (
              <p className="voice-schema-blocked" key={name}>
                {voiceSchemaLabel(name)}: contenido privado, solo en Retell.
              </p>
            );
          return (
            <div className="voice-schema-child" key={name}>
              {complex ? (
                <label className="voice-checkbox">
                  <input
                    type="checkbox"
                    name={`configure_${childPath}`}
                    checked={!!child?.enabled}
                    onChange={(event) =>
                      update({
                        children: {
                          ...base.children,
                          [name]: event.target.checked
                            ? voiceEmptyDraft(property)
                            : { enabled: false },
                        },
                      })
                    }
                  />
                  {voiceSchemaLabel(name)}
                  {childRequired ? " *" : ""}
                </label>
              ) : null}
              {!complex || child?.enabled ? (
                <VoiceControl
                  {...childProps}
                  schema={property}
                  path={childPath}
                  id={`${id}-${name}`}
                  draft={child}
                  required={childRequired}
                  onChange={(value) =>
                    update({ children: { ...base.children, [name]: value } })
                  }
                />
              ) : null}
            </div>
          );
        })}
        {dynamic ? (
          <div className="voice-schema-map">
            <p className="voice-muted">
              Propiedades con nombre. No incluyas claves privadas ni
              credenciales.
            </p>
            {entries.map((entry, index) => (
              <div className="voice-schema-entry" key={index}>
                <label htmlFor={`${id}-key-${index}`}>
                  Nombre de propiedad {index + 1}
                </label>
                <input
                  className="crm-input"
                  id={`${id}-key-${index}`}
                  name={`${path}.__key.${index}`}
                  value={entry.key}
                  onChange={(event) =>
                    update({
                      entries: entries.map((item, i) =>
                        i === index
                          ? { ...item, key: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
                {voiceSensitivePath(entry.key) ? (
                  <p className="voice-schema-blocked">
                    Esta propiedad es privada y no puede configurarse aquí.
                  </p>
                ) : (
                  <VoiceControl
                    {...childProps}
                    schema={
                      typeof schema.additionalProperties === "object"
                        ? schema.additionalProperties
                        : {}
                    }
                    path={`${path}.${entry.key || index}`}
                    id={`${id}-entry-${index}`}
                    draft={entry.draft}
                    onChange={(value) =>
                      update({
                        entries: entries.map((item, i) =>
                          i === index ? { ...item, draft: value } : item,
                        ),
                      })
                    }
                    required
                  />
                )}
                <button
                  className="crm-button"
                  type="button"
                  name={`remove_${path}.${index}`}
                  onClick={() =>
                    update({ entries: entries.filter((_, i) => i !== index) })
                  }
                >
                  Quitar propiedad {index + 1}
                </button>
              </div>
            ))}
            <button
              className="crm-button"
              type="button"
              name={`add_${path}`}
              onClick={() =>
                update({
                  entries: [
                    ...entries,
                    {
                      key: "",
                      draft: voiceEmptyDraft(
                        typeof schema.additionalProperties === "object"
                          ? schema.additionalProperties
                          : {},
                      ),
                    },
                  ],
                })
              }
            >
              Agregar propiedad
            </button>
          </div>
        ) : null}
      </div>
    );
  } else if (type === "array") {
    const items = base.items ?? [];
    control = (
      <div className="voice-schema-array">
        {!items.length ? (
          <p className="voice-muted">
            Lista vacía. Agrega los elementos completos que deseas guardar.
          </p>
        ) : null}
        {items.map((item, index) => (
          <fieldset className="voice-schema-item" key={index}>
            <legend>
              {label}: elemento {index + 1}
            </legend>
            <VoiceControl
              {...childProps}
              schema={schema.items ?? {}}
              path={`${path}.${index}`}
              id={`${id}-${index}`}
              draft={item}
              onChange={(value) =>
                update({
                  items: items.map((previous, i) =>
                    i === index ? value : previous,
                  ),
                })
              }
              required
            />
            <button
              className="crm-button"
              type="button"
              name={`remove_${path}.${index}`}
              onClick={() =>
                update({ items: items.filter((_, i) => i !== index) })
              }
            >
              Quitar elemento {index + 1}
            </button>
          </fieldset>
        ))}
        <button
          className="crm-button"
          type="button"
          name={`add_${path}`}
          disabled={
            schema.maxItems !== undefined && items.length >= schema.maxItems
          }
          onClick={() =>
            update({ items: [...items, voiceEmptyDraft(schema.items ?? {})] })
          }
        >
          Agregar elemento
        </button>
      </div>
    );
  } else if (type === "null")
    control = <p className="voice-muted">Sin valor (null).</p>;
  else {
    const catalogKey =
      /voice_id$/.test(key) || path.startsWith("fallback_voice_ids.")
        ? "voice_id"
        : /llm_id$/.test(key)
          ? "llm_id"
          : "";
    const catalog = catalogKey === "voice_id" ? voices : models;
    const choices = (catalog ?? []).filter(
      (item) =>
        item &&
        typeof item === "object" &&
        typeof item[catalogKey] === "string",
    );
    control = (
      <>
        <label htmlFor={id}>
          {label}
          {required ? " *" : ""}
        </label>
        {options.length || type === "boolean" ? (
          <select
            className="crm-input"
            id={id}
            name={path}
            value={raw}
            onChange={(event) =>
              event.target.value === ""
                ? onChange({ enabled: false })
                : update({ raw: event.target.value })
            }
          >
            <option value="">Sin configurar / mantener actual</option>
            {(type === "boolean" ? [true, false] : options).map((option) => (
              <option key={String(option)} value={String(option)}>
                {voiceSchemaOptionLabel(option)}
              </option>
            ))}
          </select>
        ) : /prompt|message|description|content|^code$/.test(key) ||
          (schema.maxLength !== undefined && schema.maxLength > 300) ? (
          <textarea
            className="crm-input voice-textarea"
            id={id}
            name={path}
            rows={4}
            value={raw}
            minLength={schema.minLength}
            maxLength={schema.maxLength}
            onChange={(event) => changeScalar(event.target.value)}
          />
        ) : (
          <input
            className="crm-input"
            id={id}
            name={path}
            type={["integer", "number"].includes(type) ? "number" : "text"}
            step={type === "integer" ? 1 : "any"}
            min={schema.minimum}
            max={schema.maximum}
            minLength={schema.minLength}
            maxLength={schema.maxLength}
            list={catalogKey ? `${id}-catalog` : undefined}
            value={raw}
            onChange={(event) => changeScalar(event.target.value)}
          />
        )}
        {catalogKey ? (
          <datalist id={`${id}-catalog`}>
            {choices.map((item, index) => (
              <option key={index} value={String(item[catalogKey])}>
                {typeof item.voice_name === "string"
                  ? item.voice_name
                  : typeof item.agent_name === "string"
                    ? item.agent_name
                    : "Recurso consultado"}
              </option>
            ))}
          </datalist>
        ) : null}
      </>
    );
  }
  return (
    <div className="voice-schema-control">
      {voiceSchemaNullable(schema) ? (
        <label className="voice-checkbox">
          <input
            type="checkbox"
            name={`${path}.__null`}
            checked={!!base.null}
            onChange={(event) =>
              event.target.checked
                ? onChange({ enabled: true, null: true })
                : onChange(voiceEmptyDraft(schema))
            }
          />
          {key === "begin_message"
            ? "Generar un mensaje inicial dinámico (null)"
            : `${label}: sin valor (null)`}
        </label>
      ) : null}
      {control}
      {base.blocked ? (
        <p role="alert" className="voice-schema-blocked">
          No se guardó la dirección: contenía credenciales o un formato no
          permitido. Administra los datos privados en Retell.
        </p>
      ) : null}
      {hint ? <p className="voice-muted">{hint}</p> : null}
      {schema.description ? (
        <details className="voice-schema-reference">
          <summary>Referencia del proveedor</summary>
          <p>{schema.description}</p>
        </details>
      ) : null}
    </div>
  );
}
export function VoiceSchemaEditor({
  schema,
  record,
  drafts,
  onChange,
  exclude = [],
  disabled,
  voices,
  models,
}: VoiceSchemaEditorProps) {
  const id = useId();
  const [search, setSearch] = useState("");
  const inventory = voiceSchemaInventory(schema).filter(
    (entry) => !exclude.includes(entry.key),
  );
  const query = search.trim().toLocaleLowerCase("es-CO");
  const filtered = inventory.filter(
    (entry) =>
      !query ||
      `${entry.label} ${entry.key} ${entry.section} ${JSON.stringify(entry.schema)}`
        .toLocaleLowerCase("es-CO")
        .includes(query),
  );
  const sections = [...new Set(filtered.map((entry) => entry.section))];
  return (
    <section className="voice-schema-editor" aria-labelledby={`${id}-heading`}>
      <header>
        <h4 id={`${id}-heading`}>Todas las opciones del proveedor</h4>
        <p className="voice-muted">
          Organizadas por función, según el esquema de API revisado. Cada cambio
          requiere revisión. Los datos privados se administran en Retell.
        </p>
      </header>
      <label htmlFor={`${id}-search`}>Buscar un ajuste</label>
      <input
        className="crm-input"
        type="search"
        id={`${id}-search`}
        name="voice_schema_search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Voz, funciones, memoria, webhook…"
      />
      {!filtered.length ? (
        <p role="status">No hay ajustes que coincidan con la búsqueda.</p>
      ) : null}
      <fieldset disabled={disabled} className="voice-schema-sections">
        <legend className="sr-only">Ajustes adicionales de Retell</legend>
        {sections.map((section) => (
          <details
            className="voice-schema-section"
            key={section}
            open={query ? true : undefined}
          >
            <summary>
              {section}
              <span>
                {filtered.filter((entry) => entry.section === section).length}{" "}
                ajustes
              </span>
            </summary>
            <div className="voice-schema-section-content">
              {filtered
                .filter((entry) => entry.section === section)
                .map((entry) => {
                  const draft = drafts[entry.key];
                  const complex = voiceSchemaComplex(entry.schema, entry.key);
                  const legacyBlocked =
                    (record?.model_config || drafts.model_config?.enabled) &&
                    [
                      "model",
                      "backup_model",
                      "model_high_priority",
                      "model_temperature",
                      "model_ultrafast",
                      "s2s_model",
                    ].includes(entry.key);
                  const update = (value: VoiceSchemaDraft) =>
                    onChange({ ...drafts, [entry.key]: value });
                  return (
                    <article
                      className="voice-schema-field"
                      key={entry.key}
                      data-voice-field={entry.key}
                    >
                      <header>
                        <h5>{entry.label}</h5>
                      </header>
                      {entry.support === "blocked" || legacyBlocked ? (
                        <p className="voice-schema-blocked">
                          {legacyBlocked
                            ? "Retell omite este ajuste heredado cuando existe model_config. Usa la configuración completa del modelo."
                            : entry.reason}
                        </p>
                      ) : (
                        <>
                          {complex ? (
                            <>
                              {record ? (
                                <details className="voice-schema-preview">
                                  <summary>Ver lectura parcial actual</summary>
                                  <VoiceSnapshot
                                    value={record[entry.key]}
                                    path={entry.key}
                                  />
                                  <p className="voice-muted">
                                    Esta lectura puede estar recortada. Nunca se
                                    reutiliza como borrador.
                                  </p>
                                </details>
                              ) : null}
                              <label className="voice-checkbox">
                                <input
                                  type="checkbox"
                                  name={`configure_${entry.key}`}
                                  checked={!!draft?.enabled}
                                  onChange={(event) =>
                                    update(
                                      event.target.checked
                                        ? voiceEmptyDraft(entry.schema)
                                        : { enabled: false },
                                    )
                                  }
                                />
                                {record
                                  ? "Reemplazar configuración completa"
                                  : "Configurar"}
                                : {entry.label.toLowerCase()}
                              </label>
                              {draft?.enabled && record ? (
                                <p className="voice-schema-warning">
                                  Escribe la configuración completa desde cero.
                                  El reemplazo puede eliminar elementos o
                                  ajustes que no incluyas.
                                </p>
                              ) : null}
                            </>
                          ) : null}
                          {!complex || draft?.enabled ? (
                            <VoiceControl
                              schema={entry.schema}
                              path={entry.key}
                              id={`${id}-${entry.key}`}
                              draft={draft}
                              onChange={update}
                              current={
                                complex ? undefined : record?.[entry.key]
                              }
                              voices={voices}
                              models={models}
                            />
                          ) : null}
                          {draft?.enabled ? (
                            <button
                              className="crm-button voice-schema-reset"
                              type="button"
                              name={`reset_${entry.key}`}
                              onClick={() => update({ enabled: false })}
                            >
                              Descartar cambio de {entry.label.toLowerCase()}
                            </button>
                          ) : null}
                        </>
                      )}
                    </article>
                  );
                })}
            </div>
          </details>
        ))}
      </fieldset>
    </section>
  );
}
