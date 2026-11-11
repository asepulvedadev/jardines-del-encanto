"use client";
import { useRef, useState } from "react";
import { IntegrationIcon, SettingsSwitch } from "./integration-icon";
import { ActionOutput } from "./hermes-panel";
import {
  itemLabels,
  settingsError,
  type ActionResult,
  type Catalog,
  type ControlItem,
  type ItemKind,
  type SettingsRequest,
} from "./settings-types";
const categories = [
  ["skill", "Skills"],
  ["tool", "Tools"],
  ["plugin", "Plugins"],
  ["script", "Scripts"],
] as const;
export function Customizations({
  catalog,
  request,
  onChanged,
  connectionsOnly = false,
}: {
  catalog: Catalog;
  request: SettingsRequest;
  onChanged: () => Promise<void>;
  connectionsOnly?: boolean;
}) {
  const [kind, setKind] = useState<ItemKind>(
    connectionsOnly ? "connection" : "skill",
  );
  const [editor, setEditor] = useState<ControlItem | "new" | null>(null);
  const [pending, setPending] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [output, setOutput] = useState<ActionResult | null>(null);
  const [runItem, setRunItem] = useState<ControlItem | null>(null);
  const [runArguments, setRunArguments] = useState("{}");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [action, setAction] = useState("");
  const [defaults, setDefaults] = useState("{}");
  const [actions, setActions] = useState<string[]>([]);
  const [steps, setSteps] = useState(
    '[\n  {"action": "crm.workspace", "arguments": {}}\n]',
  );
  const available = catalog.capabilities.filter(
    (cap) => !cap.key.startsWith("custom."),
  );
  function edit(item: ControlItem | "new") {
    setEditor(item);
    setError("");
    setNotice("");
    const value = item === "new" ? null : item;
    setKind(value?.kind ?? kind);
    setName(value?.name ?? "");
    setDescription(value?.description ?? "");
    setContent(
      String(value?.definition.content ?? value?.definition.instructions ?? ""),
    );
    setAction(String(value?.definition.action ?? available[0]?.key ?? ""));
    setDefaults(JSON.stringify(value?.definition.defaults ?? {}, null, 2));
    setActions((value?.definition.actions as string[]) ?? []);
    setSteps(
      JSON.stringify(
        value?.definition.steps ?? [{ action: "crm.workspace", arguments: {} }],
        null,
        2,
      ),
    );
  }
  async function perform(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      lock.current = false;
      setPending(false);
    }
  }
  function object(value: string): Record<string, unknown> {
    let parsed: unknown;
    try {
      parsed = JSON.parse(value);
    } catch {
      throw new Error("El JSON no es válido. Revisa comillas, comas y llaves.");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      throw new Error("Los argumentos deben ser un objeto JSON.");
    return parsed as Record<string, unknown>;
  }
  async function save(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    await perform(async () => {
      let definition: Record<string, unknown>;
      if (kind === "skill") {
        if (!content.trim()) throw new Error("Escribe instrucciones Markdown.");
        definition = { content };
      } else if (kind === "tool") {
        if (!available.some((cap) => cap.key === action))
          throw new Error("Selecciona una acción de la aplicación.");
        definition = { action, defaults: object(defaults) };
      } else if (kind === "script") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(steps);
        } catch {
          throw new Error("Los pasos no contienen JSON válido.");
        }
        if (
          !Array.isArray(parsed) ||
          parsed.length < 1 ||
          parsed.length > 8 ||
          parsed.some(
            (step) =>
              !step ||
              typeof step !== "object" ||
              !available.some((cap) => cap.key === step.action) ||
              Object.keys(step).some(
                (key) => key !== "action" && key !== "arguments",
              ) ||
              (step.arguments !== undefined &&
                (!step.arguments ||
                  typeof step.arguments !== "object" ||
                  Array.isArray(step.arguments))),
          )
        )
          throw new Error(
            "Usa entre 1 y 8 pasos con action y arguments válidos.",
          );
        definition = { steps: parsed };
      } else {
        if (!actions.length) throw new Error("Selecciona al menos una acción.");
        definition =
          kind === "connection"
            ? { adapter: "application", actions }
            : { actions, instructions: content };
      }
      const payload = {
        name: name.trim(),
        description: description.trim(),
        definition,
      };
      if (!payload.name) throw new Error("Escribe un nombre.");
      if (editor && editor !== "new")
        await request(`control/items/${editor.id}`, "PATCH", {
          ...payload,
          version: editor.version,
        });
      else
        await request("control/items", "POST", {
          ...payload,
          kind,
          enabled: false,
        });
      setEditor(null);
      await onChanged();
      setNotice("Guardado en la aplicación y en el catálogo de Hermes.");
    });
  }
  return (
    <section
      className="settings-customizations"
      aria-label={
        connectionsOnly ? "Adaptadores de la aplicación" : "Customizaciones"
      }
    >
      {!connectionsOnly && (
        <div className="settings-filters" aria-label="Categorías">
          {categories.map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={kind === key}
              onClick={() => {
                setKind(key);
                setEditor(null);
                setRunItem(null);
                setOutput(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <div className="settings-section-heading">
        <h3>
          {connectionsOnly
            ? "Adaptadores de la aplicación"
            : categories.find(([key]) => key === kind)?.[1]}
        </h3>
        <button
          className="crm-button crm-secondary"
          disabled={pending}
          onClick={() => edit("new")}
        >
          Crear {itemLabels[kind]}
        </button>
      </div>
      {error && (
        <p className="crm-error" role="alert">
          {error}
        </p>
      )}
      <p role="status" className="settings-feedback">
        {pending ? "Procesando…" : notice}
      </p>
      {catalog.items.filter((item) => item.kind === kind).length === 0 && (
        <p className="settings-empty">
          Aún no hay{" "}
          {connectionsOnly
            ? "adaptadores"
            : categories.find(([key]) => key === kind)?.[1].toLowerCase()}
          . Crea uno para compartirlo con Hermes.
        </p>
      )}
      <ul className="settings-rows">
        {catalog.items
          .filter((item) => item.kind === kind)
          .map((item) => (
            <li className="settings-row" key={item.id}>
              <IntegrationIcon name={item.kind} />
              <div className="settings-row-copy">
                <strong>{item.name}</strong>
                <span>
                  {item.effective
                    ? "Disponible para Hermes"
                    : item.enabled
                      ? "Activado · no disponible"
                      : "Desactivado"}
                </span>
              </div>
              <div className="settings-row-actions">
                <button
                  className="settings-edit"
                  disabled={pending}
                  onClick={() => edit(item)}
                >
                  Editar<span className="crm-sr-only"> {item.name}</span>
                </button>
                {item.kind !== "skill" && (
                  <button
                    className="settings-edit"
                    disabled={pending || !item.effective}
                    onClick={() => {
                      setRunItem(item);
                      setRunArguments("{}");
                      setOutput(null);
                    }}
                  >
                    Ejecutar<span className="crm-sr-only"> {item.name}</span>
                  </button>
                )}
                <SettingsSwitch
                  name={`Activar ${item.name}`}
                  checked={item.enabled}
                  disabled={pending}
                  onChange={() =>
                    void perform(async () => {
                      await request(`control/items/${item.id}`, "PATCH", {
                        version: item.version,
                        enabled: !item.enabled,
                      });
                      await onChanged();
                    })
                  }
                />
              </div>
            </li>
          ))}
      </ul>
      {editor && (
        <form onSubmit={save} className="settings-editor">
          <h4>
            {editor === "new" ? "Crear" : "Editar"} {itemLabels[kind]}
          </h4>
          <label htmlFor={`item-name-${kind}`}>
            Nombre
            <input
              id={`item-name-${kind}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              required
              disabled={pending}
            />
          </label>
          <label htmlFor={`item-description-${kind}`}>
            Descripción breve
            <input
              id={`item-description-${kind}`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              disabled={pending}
            />
          </label>
          {(kind === "skill" || kind === "plugin") && (
            <label htmlFor={`item-content-${kind}`}>
              {kind === "skill"
                ? "Instrucciones Markdown (sin código ejecutable)"
                : "Instrucciones del plugin"}
              <textarea
                id={`item-content-${kind}`}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                maxLength={16000}
                required={kind === "skill"}
                disabled={pending}
              />
            </label>
          )}
          {kind === "tool" && (
            <>
              <label htmlFor="item-action">
                Acción de la aplicación
                <select
                  id="item-action"
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                  disabled={pending}
                >
                  {available.map((cap) => (
                    <option key={cap.key} value={cap.key}>
                      {cap.name} · {cap.key}
                    </option>
                  ))}
                </select>
              </label>
              <label htmlFor="item-defaults">
                Argumentos predeterminados (objeto JSON)
                <textarea
                  id="item-defaults"
                  value={defaults}
                  onChange={(e) => setDefaults(e.target.value)}
                  maxLength={12000}
                  disabled={pending}
                />
              </label>
              {available.find((cap) => cap.key === action) && (
                <details>
                  <summary>Campos y permisos de la acción</summary>
                  <p>
                    {available.find((cap) => cap.key === action)?.mutating
                      ? "Requiere aprobación antes de cambiar datos."
                      : "Acción de consulta."}
                  </p>
                  <pre className="settings-result">
                    {JSON.stringify(
                      available.find((cap) => cap.key === action)?.input_schema,
                      null,
                      2,
                    )}
                  </pre>
                </details>
              )}
            </>
          )}
          {(kind === "plugin" || kind === "connection") && (
            <fieldset disabled={pending}>
              <legend>
                {kind === "connection"
                  ? "Adaptador local · Acciones compartidas"
                  : "Acciones del plugin"}
              </legend>
              {available.map((cap) => (
                <label className="settings-action-choice" key={cap.key}>
                  <input
                    type="checkbox"
                    checked={actions.includes(cap.key)}
                    onChange={(e) =>
                      setActions((old) =>
                        e.target.checked
                          ? [...old, cap.key]
                          : old.filter((key) => key !== cap.key),
                      )
                    }
                  />
                  <span>
                    {cap.name}
                    <small>
                      {cap.key}
                      {cap.mutating ? " · requiere aprobación" : ""}
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          {kind === "script" && (
            <>
              <label htmlFor="item-steps">
                Pasos de aplicación (JSON, máximo 8; no Python ni shell)
                <textarea
                  id="item-steps"
                  value={steps}
                  onChange={(e) => setSteps(e.target.value)}
                  maxLength={14000}
                  required
                  disabled={pending}
                />
              </label>
              <details>
                <summary>Acciones y campos disponibles</summary>
                {available.map((cap) => (
                  <div key={cap.key}>
                    <strong>{cap.key}</strong>
                    <pre className="settings-result">
                      {JSON.stringify(cap.input_schema, null, 2)}
                    </pre>
                  </div>
                ))}
              </details>
            </>
          )}
          {editor === "new" && (
            <p className="settings-meta">
              Se creará desactivado. Actívalo después de revisar su definición.
            </p>
          )}
          <div className="social-actions">
            <button className="crm-button" disabled={pending}>
              Guardar {itemLabels[kind]}
            </button>
            <button
              className="crm-button crm-secondary"
              type="button"
              disabled={pending}
              onClick={() => setEditor(null)}
            >
              Cancelar
            </button>
          </div>
        </form>
      )}
      {runItem && (
        <form
          className="settings-editor"
          onSubmit={(event) => {
            event.preventDefault();
            void perform(async () => {
              setOutput(
                await request<ActionResult>(
                  `control/items/${runItem.id}/run`,
                  "POST",
                  { arguments: object(runArguments) },
                ),
              );
              await onChanged();
            });
          }}
        >
          <h4>Ejecutar {runItem.name}</h4>
          <label htmlFor="run-arguments">
            Argumentos de entrada (objeto JSON)
            <textarea
              id="run-arguments"
              value={runArguments}
              maxLength={12000}
              onChange={(e) => setRunArguments(e.target.value)}
              disabled={pending}
            />
          </label>
          <p className="settings-meta">
            Las consultas devuelven resultados; los cambios requieren aprobación
            exacta.
          </p>
          <div className="social-actions">
            <button className="crm-button" disabled={pending}>
              Preparar ejecución
            </button>
            <button
              className="crm-button crm-secondary"
              type="button"
              disabled={pending}
              onClick={() => {
                setRunItem(null);
                setOutput(null);
              }}
            >
              Cerrar ejecución
            </button>
          </div>
        </form>
      )}
      {output && (
        <ActionOutput value={output} request={request} onChanged={onChanged} />
      )}
    </section>
  );
}
