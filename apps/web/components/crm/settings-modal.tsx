"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { SocialPanel } from "./social-panel";
import { HermesPanel } from "./hermes-panel";
import { Customizations } from "./customizations";
import { Icon } from "./icon";
import { IntegrationIcon, SettingsSwitch } from "./integration-icon";
import {
  settingsError,
  type Catalog,
  type ControlItem,
  type Connection,
  type SettingsRequest,
} from "./settings-types";
import "../../app/crm/settings.css";
const tabs = [
  ["social", "Redes sociales"],
  ["connections", "Conexiones"],
  ["customizations", "Customizaciones"],
] as const;
type Tab = (typeof tabs)[number][0];
const errors: Record<string, string> = {
  record_changed:
    "La configuración cambió en otra sesión. Actualiza el catálogo y revisa antes de guardar.",
  invalid_input: "Revisa la definición y los campos de la acción.",
  invalid_csrf: "Tu sesión cambió. Recarga la página antes de guardar.",
  permission_denied: "Esta sesión no tiene permiso para la acción.",
  hermes_unavailable:
    "Hermes no está disponible. Revisa su configuración y proveedor.",
  hermes_disabled: "Hermes está desactivado.",
  connection_disabled: "La conexión está pausada.",
  item_disabled: "La customización está desactivada.",
  proposal_expired: "La propuesta venció. Solicita una nueva.",
  proposal_changed:
    "La propuesta cambió o ya fue resuelta. Actualiza el catálogo.",
  invalid_definition:
    "La definición no es válida. Revisa las acciones y sus argumentos.",
};
export function SettingsModal({
  open,
  onClose,
  csrf,
  onWorkspaceChanged,
  initialSocial = false,
}: {
  open: boolean;
  onClose: () => void;
  csrf: string;
  onWorkspaceChanged: () => Promise<void>;
  initialSocial?: boolean;
}) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<Tab>("social");
  const [visited, setVisited] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [editingConnection, setEditingConnection] = useState<string | null>(
    null,
  );
  const request: SettingsRequest = useCallback(
    async <T,>(path: string, method = "GET", payload?: unknown): Promise<T> => {
      const body = method === "GET" ? undefined : JSON.stringify(payload ?? {});
      if (
        body &&
        new TextEncoder().encode(body).byteLength >
          (/^control\/items(?:\/[^/]+)?$/.test(path) ? 65536 : 16384)
      )
        throw new Error(
          "El contenido supera el tamaño permitido. Reduce la definición o los argumentos.",
        );
      const response = await fetch(`/api/crm/${path}`, {
        method,
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body,
        signal: AbortSignal.timeout(path === "hermes/chat" ? 90000 : 25000),
      }).catch(() => {
        throw new Error(
          "No pudimos contactar al servidor. No se confirmó ningún cambio.",
        );
      });
      if (response.status === 401) {
        router.replace("/login");
        throw new Error("Tu sesión finalizó. Vuelve a ingresar.");
      }
      const result = await response.json().catch(() => null);
      if (!response.ok || !result)
        throw new Error(
          errors[result?.detail] ??
            "No pudimos completar la solicitud. No se confirmó el cambio; actualiza y revisa el estado.",
        );
      if (
        (method === "POST" || method === "PATCH") &&
        /^control\/items(?:\/[^/]+)?$/.test(path)
      ) {
        const item = result as ControlItem;
        setCatalog((old) =>
          old
            ? {
                ...old,
                items: old.items.some((value) => value.id === item.id)
                  ? old.items.map((value) =>
                      value.id === item.id ? item : value,
                    )
                  : [...old.items, item],
              }
            : old,
        );
      }
      return result as T;
    },
    [csrf, router],
  );
  const load = useCallback(async () => {
    const value = await request<Catalog>("control/catalog");
    setCatalog(value);
    setRevision((value) => value + 1);
  }, [request]);
  const onChanged = useCallback(async () => {
    try {
      await Promise.all([load(), onWorkspaceChanged()]);
    } catch {
      setError(
        "El servidor ya respondió a la acción, pero no pudimos actualizar la vista. No repitas el cambio; actualiza el catálogo para revisar el estado.",
      );
    }
  }, [load, onWorkspaceChanged]);
  useEffect(() => {
    if (open) {
      setVisited(true);
      if (initialSocial) setTab("social");
      if (!dialog.current?.open) dialog.current?.showModal();
    } else if (dialog.current?.open) dialog.current.close();
  }, [open, initialSocial]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError("");
    load()
      .catch((cause) => {
        if (active) setError(settingsError(cause));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open, load]);
  useEffect(() => {
    if (editingConnection === "hermes") {
      const prompt =
        dialog.current?.querySelector<HTMLTextAreaElement>("#hermes-message");
      prompt?.scrollIntoView({ block: "nearest" });
      prompt?.focus();
    }
  }, [editingConnection]);
  async function toggle(connection: Connection) {
    if (lock.current) return;
    lock.current = true;
    setPending(true);
    setError("");
    try {
      const result = await request<Connection>(
        `control/connections/${connection.key}`,
        "PATCH",
        { version: connection.version, enabled: !connection.enabled },
      );
      setCatalog((old) =>
        old
          ? {
              ...old,
              connections: old.connections.map((item) =>
                item.key === result.key ? result : item,
              ),
            }
          : old,
      );
      setRevision((value) => value + 1);
    } catch (cause) {
      setError(settingsError(cause));
    } finally {
      lock.current = false;
      setPending(false);
    }
  }
  function connectionRow(connection: Connection) {
    return (
      <div className="settings-row" key={connection.key}>
        <IntegrationIcon name={connection.key} />
        <div className="settings-row-copy">
          <strong>{connection.name}</strong>
          <span>
            {!connection.enabled
              ? "Pausado"
              : connection.effective
                ? "Disponible"
                : connection.available
                  ? "Requiere configuración"
                  : "No disponible"}
          </span>
        </div>
        <div className="settings-row-actions">
          <button
            className="settings-edit"
            aria-expanded={editingConnection === connection.key}
            aria-controls={
              connection.key === "hermes"
                ? "hermes-connection-editor"
                : "zernio-mcp-heading"
            }
            onClick={() => {
              setEditingConnection((old) =>
                old === connection.key ? null : connection.key,
              );
              dialog.current
                ?.querySelector<HTMLElement>(
                  connection.key === "hermes"
                    ? "#hermes-message"
                    : "#zernio-mcp-heading",
                )
                ?.scrollIntoView({ block: "nearest" });
            }}
          >
            Editar<span className="crm-sr-only"> {connection.name}</span>
          </button>
          <SettingsSwitch
            name={`Activar ${connection.name}`}
            checked={connection.enabled}
            disabled={pending}
            onChange={() => void toggle(connection)}
          />
        </div>
      </div>
    );
  }
  return (
    <dialog
      ref={dialog}
      className="settings-modal"
      aria-labelledby="settings-title"
      onClose={onClose}
    >
      <div className="settings-modal-shell">
        <header className="settings-header">
          <div>
            <span className="settings-kicker">JARDINES DEL ENCANTO</span>
            <h2 id="settings-title">Configuraciones</h2>
          </div>
          <button
            type="button"
            className="settings-close"
            aria-label="Cerrar configuraciones"
            onClick={onClose}
          >
            <Icon name="close" size={22} />
          </button>
        </header>
        <div className="settings-layout">
          <div
            className="settings-tabs"
            role="tablist"
            aria-label="Configuraciones"
            aria-orientation="vertical"
            onKeyDown={(event) => {
              if (
                ![
                  "ArrowRight",
                  "ArrowLeft",
                  "ArrowDown",
                  "ArrowUp",
                  "Home",
                  "End",
                ].includes(event.key)
              )
                return;
              event.preventDefault();
              const index = tabs.findIndex(([key]) => key === tab);
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? tabs.length - 1
                    : (index +
                        (["ArrowRight", "ArrowDown"].includes(event.key)
                          ? 1
                          : tabs.length - 1)) %
                      tabs.length;
              setTab(tabs[next][0]);
              dialog.current
                ?.querySelector<HTMLButtonElement>(
                  `#settings-tab-${tabs[next][0]}`,
                )
                ?.focus();
            }}
          >
            {tabs.map(([key, label]) => (
              <button
                key={key}
                id={`settings-tab-${key}`}
                type="button"
                role="tab"
                aria-selected={tab === key}
                aria-controls={`settings-panel-${key}`}
                tabIndex={tab === key ? 0 : -1}
                onClick={() => setTab(key)}
              >
                <Icon
                  name={
                    key === "social"
                      ? "message"
                      : key === "connections"
                        ? "connections"
                        : "settings"
                  }
                />
                {label}
              </button>
            ))}
          </div>
          <div className="settings-body" aria-busy={loading || pending}>
            {error && (
              <p className="crm-error" role="alert">
                {error}
              </p>
            )}
            {loading && (
              <p role="status">Consultando el catálogo compartido…</p>
            )}
            {!loading && (
              <button
                type="button"
                className="settings-refresh"
                onClick={() => {
                  setLoading(true);
                  setError("");
                  void load()
                    .catch((cause) => setError(settingsError(cause)))
                    .finally(() => setLoading(false));
                }}
              >
                Actualizar catálogo
              </button>
            )}
            <section
              id="settings-panel-social"
              role="tabpanel"
              aria-labelledby="settings-tab-social"
              tabIndex={0}
              hidden={tab !== "social"}
            >
              {catalog?.connections
                .filter((item) => item.key === "zernio")
                .map(connectionRow)}
              {editingConnection === "zernio" && (
                <p className="settings-meta">
                  Pausar no revoca cuentas. Autoriza o revisa el acceso a
                  continuación.
                </p>
              )}
              {visited && (
                <SocialPanel
                  csrf={csrf}
                  connections={catalog?.connections ?? []}
                  connectionPending={pending}
                  onToggleConnection={toggle}
                  onStateChanged={load}
                />
              )}
            </section>
            <section
              id="settings-panel-connections"
              role="tabpanel"
              aria-labelledby="settings-tab-connections"
              tabIndex={0}
              hidden={tab !== "connections"}
            >
              {catalog?.connections
                .filter((item) => item.key === "hermes")
                .map(connectionRow)}
              <div
                id="hermes-connection-editor"
                hidden={editingConnection !== "hermes"}
              >
                {visited && (
                  <HermesPanel
                    request={request}
                    onChanged={onChanged}
                    revision={revision}
                  />
                )}
              </div>
              <details
                className="settings-adapters"
                open={editingConnection === "application"}
              >
                <summary>Conexiones de la aplicación</summary>
                {catalog && (
                  <Customizations
                    connectionsOnly
                    catalog={catalog}
                    request={request}
                    onChanged={onChanged}
                  />
                )}
              </details>
            </section>
            <section
              id="settings-panel-customizations"
              role="tabpanel"
              aria-labelledby="settings-tab-customizations"
              tabIndex={0}
              hidden={tab !== "customizations"}
            >
              {catalog && (
                <Customizations
                  catalog={catalog}
                  request={request}
                  onChanged={onChanged}
                />
              )}
            </section>
          </div>
        </div>
      </div>
    </dialog>
  );
}
