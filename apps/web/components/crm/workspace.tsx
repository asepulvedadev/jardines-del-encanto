"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "./icon";
import { SocialPanel } from "./social-panel";
import { Empty, StageSelect, TaskRow } from "./workspace-parts";
import {
  errorMessage,
  initials,
  labels,
  phoneLabel,
  shortDate,
  sourceLabel,
  sources,
  stages,
  today,
  type Activity,
  type Contact,
  type Deal,
  type Source,
  type Stage,
  type Task,
  type View,
  type WorkspaceData,
} from "./types";

const navigation = [
  ["overview", "home"],
  ["pipeline", "board"],
  ["contacts", "people"],
  ["tasks", "task"],
] as const;

export function Workspace({
  initialData,
  user,
  csrf,
}: {
  initialData: WorkspaceData;
  user: { username: string; role: string };
  csrf: string;
}) {
  const router = useRouter();
  const [data, setData] = useState(initialData);
  const [view, setView] = useState<View>("overview");
  const [query, setQuery] = useState("");
  const [list, setList] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selection, setSelection] = useState<string | null>(null);
  const [contactEditor, setContactEditor] = useState<Contact | "new" | null>(
    null,
  );
  const [taskContact, setTaskContact] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<Activity[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [dragStage, setDragStage] = useState<Stage | null>(null);
  const drawer = useRef<HTMLDialogElement>(null);
  const contactDialog = useRef<HTMLDialogElement>(null);
  const taskDialog = useRef<HTMLDialogElement>(null);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const busy = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const selected = data.contacts.find((contact) => contact.id === selection);
  const selectedDeal = data.deals.find((deal) => deal.contact_id === selection);
  const contactsById = useMemo(
    () => new Map(data.contacts.map((contact) => [contact.id, contact])),
    [data.contacts],
  );
  const matches = useCallback(
    (contact: Contact) => {
      const value = query.toLocaleLowerCase("es").trim();
      return (
        !value ||
        `${contact.name} ${contact.phone} ${sourceLabel(contact.source)}`
          .toLocaleLowerCase("es")
          .includes(value)
      );
    },
    [query],
  );
  const filteredContacts = data.contacts.filter(matches);
  const visibleDeals = data.deals.filter((deal) => {
    const contact = contactsById.get(deal.contact_id);
    return contact && matches(contact);
  });
  const day = today();

  const request = useCallback(
    async <T,>(path: string, method = "GET", payload?: unknown): Promise<T> => {
      const response = await fetch(`/api/crm/${path}`, {
        method,
        cache: "no-store",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: method === "GET" ? undefined : JSON.stringify(payload ?? {}),
      });
      const result = await response.json();
      if (response.status === 401) {
        router.replace("/login");
        router.refresh();
      }
      if (!response.ok) throw new Error(errorMessage(result.detail));
      return result as T;
    },
    [csrf, router],
  );

  async function refresh() {
    setData(await request<WorkspaceData>("workspace"));
  }
  async function mutate(
    action: () => Promise<unknown>,
    success: string,
    after?: () => void,
  ) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh();
      setNotice(success);
      after?.();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No pudimos guardar. Intenta de nuevo.",
      );
    } finally {
      busy.current = false;
      setPending(false);
    }
  }
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("social_intent") || params.has("zernio_callback"))
      setView("settings");
  }, []);

  useEffect(() => {
    if (!selectedDeal) return;
    let active = true;
    setTimelineLoading(true);
    request<Activity[]>(`deals/${selectedDeal.id}/activities`)
      .then((records) => {
        if (active) setTimeline(records);
      })
      .catch((cause) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setTimelineLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedDeal, data.activities, request]);

  function openContact(contact: Contact) {
    setSelection(contact.id);
    setError("");
    setTimeline([]);
    drawer.current?.showModal();
  }
  function editContact(contact: Contact | "new") {
    if (busy.current) return;
    setContactEditor(contact);
    setError("");
    contactDialog.current?.showModal();
  }
  function openTask(contactId = "") {
    if (busy.current) return;
    setTaskContact(contactId);
    setError("");
    taskDialog.current?.showModal();
  }
  function moveDeal(deal: Deal, stage: Stage) {
    if (deal.stage === stage) return;
    void mutate(
      () =>
        request(`deals/${deal.id}`, "PATCH", { stage, version: deal.version }),
      "Etapa actualizada.",
    );
  }
  function toggleTask(task: Task) {
    void mutate(
      () =>
        request(`tasks/${task.id}`, "PATCH", {
          completed: !task.completed,
          version: task.version,
        }),
      task.completed ? "Seguimiento reabierto." : "Seguimiento completado.",
    );
  }
  async function saveContact(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      name: form.get("name"),
      phone: form.get("phone"),
      source: form.get("source"),
    };
    const edit =
      contactEditor && contactEditor !== "new" ? contactEditor : null;
    await mutate(
      () =>
        request(
          edit ? `contacts/${edit.id}` : "contacts",
          edit ? "PATCH" : "POST",
          edit ? { ...payload, version: edit.version } : payload,
        ),
      edit ? "Cliente actualizado." : "Cliente creado en la etapa Nuevo.",
      () => contactDialog.current?.close(),
    );
  }
  async function saveTask(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await mutate(
      () =>
        request("tasks", "POST", {
          contact_id: form.get("contact_id"),
          title: form.get("title"),
          due_date: form.get("due_date"),
        }),
      "Seguimiento programado.",
      () => taskDialog.current?.close(),
    );
  }
  async function saveNote(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    if (!selectedDeal) return;
    await mutate(
      () =>
        request(`deals/${selectedDeal.id}/notes`, "POST", {
          body: form.get("body"),
        }),
      "Nota guardada.",
      () => formElement.reset(),
    );
  }
  function changeView(next: View) {
    setView(next);
    setQuery("");
    setError("");
    setMobileMenu(false);
    requestAnimationFrame(() => heading.current?.focus());
  }
  async function logout() {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    try {
      await request("auth/logout", "POST");
      router.replace("/login");
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "No pudimos cerrar la sesión.",
      );
    } finally {
      setPending(false);
      busy.current = false;
    }
  }
  const pendingTasks = data.tasks.filter((task) => !task.completed);
  return (
    <div className="crm-shell">
      <a href="#crm-content" className="skip-link">
        Saltar al contenido
      </a>
      <aside
        className={`crm-sidebar ${mobileMenu ? "is-open" : ""}`}
        aria-label="Menú del CRM"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setMobileMenu(false);
            menuTrigger.current?.focus();
          }
        }}
      >
        <a href="/crm" className="crm-brand">
          Jardines<span>del Encanto.</span>
        </a>
        <span className="crm-sidebar-label">ESPACIO COMERCIAL</span>
        <nav aria-label="Secciones del CRM">
          {navigation.map(([key, icon]) => (
            <button
              key={key}
              className={view === key ? "is-active" : ""}
              aria-current={view === key ? "page" : undefined}
              onClick={() => changeView(key)}
            >
              <Icon name={icon} />
              <span>{labels[key]}</span>
              {key === "tasks" && data.counts.pending > 0 && (
                <span className="crm-nav-count">{data.counts.pending}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="crm-sidebar-bottom">
          <button
            className={`crm-settings-link ${view === "settings" ? "is-active" : ""}`}
            aria-current={view === "settings" ? "page" : undefined}
            onClick={() => changeView("settings")}
          >
            <Icon name="settings" />
            <span>Configuraciones</span>
          </button>
          <div className="crm-profile">
            <span className="crm-avatar">{initials(user.username)}</span>
            <div>
              <strong>{user.username}</strong>
              <span>Administrador</span>
            </div>
            <button
              onClick={logout}
              disabled={pending}
              aria-label="Cerrar sesión"
              title="Cerrar sesión"
            >
              <Icon name="logout" />
            </button>
          </div>
        </div>
      </aside>
      <div className="crm-main">
        <header className="crm-topbar">
          <button
            ref={menuTrigger}
            className="crm-mobile-toggle"
            aria-label={mobileMenu ? "Cerrar menú" : "Abrir menú"}
            aria-expanded={mobileMenu}
            onClick={() => setMobileMenu(!mobileMenu)}
          >
            <Icon name={mobileMenu ? "close" : "menu"} />
          </button>
          <div>
            <span>Jardines del Encanto</span>
            <Icon name="chevron" size={13} />
            <strong>{labels[view]}</strong>
          </div>
          <span className="crm-private-label">Espacio privado</span>
        </header>
        <main id="crm-content" className="crm-content">
          <div className="crm-page-heading">
            <div>
              <p className="crm-eyebrow">GESTIÓN COMERCIAL</p>
              <h1 ref={heading} tabIndex={-1}>
                {view === "overview" ? "Tu día, en orden." : labels[view]}
              </h1>
              <p>
                {view === "overview"
                  ? "Las conversaciones y próximos pasos de tu equipo, en un solo lugar."
                  : view === "pipeline"
                    ? "Una vista clara de cada conversación y su siguiente paso."
                    : view === "contacts"
                      ? "Solo lo importante: nombre, celular y de dónde llega cada cliente."
                      : view === "settings"
                        ? "Administra las conexiones y los canales de tu equipo."
                        : "Que ninguna conversación se quede sin un siguiente paso."}
              </p>
            </div>
            <div className="crm-heading-actions">
              {view === "tasks" && (
                <button
                  className="crm-button crm-secondary"
                  disabled={!data.contacts.length}
                  onClick={() => openTask()}
                >
                  <Icon name="calendar" />
                  Nueva tarea
                </button>
              )}
              {view !== "settings" && (
                <button
                  className="crm-button"
                  onClick={() => editContact("new")}
                >
                  <Icon name="plus" />
                  Nuevo cliente
                </button>
              )}
            </div>
          </div>
          {error && (
            <div className="crm-error crm-message" role="alert">
              {error}
              <button aria-label="Cerrar aviso" onClick={() => setError("")}>
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          <p className="crm-save-status" role="status">
            {pending ? "Guardando cambios…" : notice}
          </p>
          {data.limited && view !== "settings" && (
            <p className="crm-limit-note">
              Esta vista muestra hasta 500 registros por sección. Los totales
              incluyen todos los registros. Se requiere paginación antes de
              superar este volumen.
            </p>
          )}
          {view === "settings" ? (
            <section aria-labelledby="crm-connections-heading">
              <div className="crm-settings-heading">
                <Icon name="connections" />
                <h2 id="crm-connections-heading">Conexiones</h2>
              </div>
              <SocialPanel csrf={csrf} />
            </section>
          ) : view === "overview" ? (
            <>
              <div className="crm-stat-strip">
                <div>
                  <span>Clientes registrados</span>
                  <strong>{data.counts.contacts}</strong>
                </div>
                <div>
                  <span>Negociaciones en curso</span>
                  <strong>{data.counts.active}</strong>
                </div>
                <div>
                  <span>Seguimientos vencidos</span>
                  <strong
                    className={data.counts.overdue ? "crm-warning-text" : ""}
                  >
                    {data.counts.overdue}
                  </strong>
                </div>
              </div>
              <div className="crm-overview-grid">
                <section className="crm-panel">
                  <div className="crm-panel-heading">
                    <h2>Lo que sigue</h2>
                    <button
                      className="crm-inline-link"
                      onClick={() => changeView("tasks")}
                    >
                      Ver seguimientos <Icon name="chevron" size={14} />
                    </button>
                  </div>
                  {pendingTasks.length ? (
                    <div>
                      {pendingTasks.slice(0, 6).map((task) => (
                        <TaskRow
                          contact={contactsById.get(task.contact_id)}
                          day={day}
                          pending={pending}
                          onToggle={toggleTask}
                          onOpen={openContact}
                          key={task.id}
                          task={task}
                        />
                      ))}
                    </div>
                  ) : (
                    <Empty
                      onCreate={() => editContact("new")}
                      title={
                        data.contacts.length
                          ? "Todo al día."
                          : "Empecemos con una conversación."
                      }
                      action={!data.contacts.length}
                    >
                      {data.contacts.length
                        ? "No tienes seguimientos pendientes. Programa el próximo desde la ficha de un cliente."
                        : "Registra tu primer cliente. Su negociación aparecerá automáticamente en el pipeline."}
                    </Empty>
                  )}
                </section>
                <section className="crm-panel crm-pipeline-summary">
                  <div className="crm-panel-heading">
                    <h2>Tu pipeline</h2>
                    <button
                      aria-label="Abrir pipeline"
                      className="crm-icon-button"
                      onClick={() => changeView("pipeline")}
                    >
                      <Icon name="arrow" size={16} />
                    </button>
                  </div>
                  {stages.map(([key, label]) => {
                    const count = data.deals.filter(
                      (deal) => deal.stage === key,
                    ).length;
                    return (
                      <div className="crm-stage-summary" key={key}>
                        <span className={`crm-stage-dot stage-${key}`} />
                        <span>{label}</span>
                        <div className="crm-stage-track">
                          <span
                            style={{
                              width: data.deals.length
                                ? `${(100 * count) / data.deals.length}%`
                                : "0%",
                            }}
                          />
                        </div>
                        <strong>{count}</strong>
                      </div>
                    );
                  })}
                  <p className="crm-subtle">
                    Ganado y descartado son estados comerciales; no registran
                    ventas ni reservas de lotes.
                  </p>
                </section>
              </div>
              <section className="crm-panel crm-recent">
                <div className="crm-panel-heading">
                  <h2>Actividad reciente</h2>
                  <span className="crm-subtle">Actualizaciones del equipo</span>
                </div>
                {data.activities.length ? (
                  <ol className="crm-activity-feed">
                    {data.activities.slice(0, 6).map((item) => (
                      <li key={item.id}>
                        <span className="crm-activity-mark" />
                        <div>
                          <p>{item.body}</p>
                          <time dateTime={item.created_at}>
                            {new Date(item.created_at).toLocaleString("es-CO", {
                              dateStyle: "medium",
                              timeStyle: "short",
                              timeZone: "America/Bogota",
                            })}
                          </time>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="crm-quiet-empty">
                    Las acciones de tus clientes y negociaciones aparecerán
                    aquí.
                  </p>
                )}
              </section>
            </>
          ) : (
            <>
              <div className="crm-toolbar">
                <label className="crm-search">
                  <Icon name="search" />
                  <span className="crm-sr-only">
                    Buscar por nombre, celular u origen
                  </span>
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Buscar nombre, celular u origen…"
                    type="search"
                  />
                </label>
                <div className="crm-toolbar-right">
                  {view === "pipeline" && (
                    <div
                      className="crm-view-switch"
                      aria-label="Vista del pipeline"
                    >
                      <button
                        aria-pressed={!list}
                        onClick={() => setList(false)}
                      >
                        <Icon name="board" size={16} />
                        Kanban
                      </button>
                      <button aria-pressed={list} onClick={() => setList(true)}>
                        <Icon name="list" size={16} />
                        Lista
                      </button>
                    </div>
                  )}
                  {view === "contacts" && (
                    <span className="crm-subtle">
                      {filteredContacts.length} clientes
                    </span>
                  )}
                  {view === "tasks" && (
                    <div className="crm-view-switch">
                      <button
                        aria-pressed={!completed}
                        onClick={() => setCompleted(false)}
                      >
                        Pendientes
                      </button>
                      <button
                        aria-pressed={completed}
                        onClick={() => setCompleted(true)}
                      >
                        Completadas
                      </button>
                    </div>
                  )}
                </div>
              </div>
              {view === "pipeline" && !list ? (
                <>
                  <p className="crm-board-hint">
                    Arrastra para mover. También puedes cambiar la etapa desde
                    cada tarjeta. Desliza el tablero para ver todas las etapas.
                  </p>
                  <div
                    className="crm-board"
                    role="region"
                    aria-label="Pipeline de negociaciones, desplazamiento horizontal"
                    tabIndex={0}
                  >
                    {stages.map(([key, label]) => {
                      const deals = visibleDeals.filter(
                        (deal) => deal.stage === key,
                      );
                      return (
                        <section
                          key={key}
                          className={`crm-column ${dragStage === key ? "is-drag-target" : ""}`}
                          aria-label={`Etapa ${label}`}
                          onDragOver={(event) => {
                            event.preventDefault();
                            setDragStage(key);
                          }}
                          onDragLeave={(event) => {
                            if (
                              !event.currentTarget.contains(
                                event.relatedTarget as Node,
                              )
                            )
                              setDragStage(null);
                          }}
                          onDrop={(event) => {
                            event.preventDefault();
                            setDragStage(null);
                            const id = event.dataTransfer.getData(
                              "application/x-crm-deal",
                            );
                            const deal = data.deals.find(
                              (item) => item.id === id,
                            );
                            if (deal) moveDeal(deal, key);
                          }}
                        >
                          <div className="crm-column-heading">
                            <span className={`crm-stage-dot stage-${key}`} />
                            <h2>{label}</h2>
                            <span>{deals.length}</span>
                            {key === "new" && (
                              <button
                                aria-label="Crear cliente en Nuevo"
                                onClick={() => editContact("new")}
                              >
                                <Icon name="plus" size={16} />
                              </button>
                            )}
                          </div>
                          <div className="crm-column-cards">
                            {deals.length ? (
                              deals.map((deal) => {
                                const contact = contactsById.get(
                                  deal.contact_id,
                                )!;
                                const next = data.tasks.find(
                                  (task) =>
                                    task.contact_id === contact.id &&
                                    !task.completed,
                                );
                                return (
                                  <article
                                    className="crm-deal-card"
                                    key={deal.id}
                                    draggable={!pending}
                                    onDragStart={(event) =>
                                      event.dataTransfer.setData(
                                        "application/x-crm-deal",
                                        deal.id,
                                      )
                                    }
                                    onDragEnd={() => setDragStage(null)}
                                  >
                                    <button
                                      className="crm-card-open"
                                      aria-label={`Abrir cliente ${contact.name}`}
                                      onClick={() => openContact(contact)}
                                    >
                                      <span className="crm-card-person">
                                        <span className="crm-avatar">
                                          {initials(contact.name)}
                                        </span>
                                        <strong>{contact.name}</strong>
                                      </span>
                                      <span className="crm-card-phone">
                                        {phoneLabel(contact.phone)}
                                      </span>
                                      <span className="crm-source-tag">
                                        {sourceLabel(contact.source)}
                                      </span>
                                    </button>
                                    <div className="crm-card-bottom">
                                      <span
                                        className={
                                          next && next.due_date < day
                                            ? "crm-warning-text"
                                            : ""
                                        }
                                      >
                                        <Icon name="calendar" size={13} />
                                        {next
                                          ? shortDate(next.due_date)
                                          : "Sin seguimiento"}
                                      </span>
                                      <StageSelect
                                        pending={pending}
                                        onMove={moveDeal}
                                        deal={deal}
                                        name={contact.name}
                                      />
                                    </div>
                                  </article>
                                );
                              })
                            ) : (
                              <div className="crm-column-empty">
                                {query
                                  ? "Sin coincidencias"
                                  : "Sin oportunidades"}
                              </div>
                            )}
                          </div>
                        </section>
                      );
                    })}
                  </div>
                </>
              ) : view === "pipeline" || view === "contacts" ? (
                <section className="crm-table-panel">
                  {filteredContacts.length ? (
                    <div
                      className="crm-table-scroll"
                      role="region"
                      aria-label="Listado de clientes, desplazamiento horizontal"
                      tabIndex={0}
                    >
                      <table className="crm-table">
                        <thead>
                          <tr>
                            <th>Nombre</th>
                            <th>Celular</th>
                            <th>Medio de origen</th>
                            <th>Etapa</th>
                            <th>
                              <span className="crm-sr-only">Abrir ficha</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredContacts.map((contact) => {
                            const deal = data.deals.find(
                              (item) => item.contact_id === contact.id,
                            );
                            return (
                              <tr key={contact.id}>
                                <td>
                                  <button
                                    className="crm-table-name"
                                    onClick={() => openContact(contact)}
                                  >
                                    <span className="crm-avatar">
                                      {initials(contact.name)}
                                    </span>
                                    {contact.name}
                                  </button>
                                </td>
                                <td>
                                  <a href={`tel:${contact.phone}`}>
                                    {phoneLabel(contact.phone)}
                                  </a>
                                </td>
                                <td>
                                  <span className="crm-source-tag">
                                    {sourceLabel(contact.source)}
                                  </span>
                                </td>
                                <td>
                                  {deal && (
                                    <StageSelect
                                      pending={pending}
                                      onMove={moveDeal}
                                      deal={deal}
                                      name={contact.name}
                                    />
                                  )}
                                </td>
                                <td>
                                  <button
                                    className="crm-icon-button"
                                    aria-label={`Abrir cliente ${contact.name}`}
                                    onClick={() => openContact(contact)}
                                  >
                                    <Icon name="chevron" />
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <Empty
                      onCreate={() => editContact("new")}
                      title={
                        query
                          ? "No encontramos coincidencias."
                          : "Tu lista empieza aquí."
                      }
                      action={!query}
                    >
                      {query
                        ? "Prueba con otro nombre, celular o medio de origen."
                        : "Solo necesitas nombre, celular y medio de origen para registrar un cliente."}
                    </Empty>
                  )}
                </section>
              ) : (
                <section className="crm-panel">
                  {data.tasks
                    .filter(
                      (task) =>
                        task.completed === completed &&
                        !!contactsById.get(task.contact_id) &&
                        matches(contactsById.get(task.contact_id)!),
                    )
                    .map((task) => (
                      <TaskRow
                        contact={contactsById.get(task.contact_id)}
                        day={day}
                        pending={pending}
                        onToggle={toggleTask}
                        onOpen={openContact}
                        key={task.id}
                        task={task}
                      />
                    ))}
                  {!data.tasks.some(
                    (task) =>
                      task.completed === completed &&
                      !!contactsById.get(task.contact_id) &&
                      matches(contactsById.get(task.contact_id)!),
                  ) && (
                    <Empty
                      onCreate={() => editContact("new")}
                      title={
                        query
                          ? "Sin coincidencias."
                          : completed
                            ? "Aún no hay tareas completadas."
                            : "Todo al día."
                      }
                      action={false}
                    >
                      {query
                        ? "Prueba una búsqueda diferente."
                        : "Programa una llamada, una visita o el siguiente paso desde la ficha de un cliente."}
                    </Empty>
                  )}
                </section>
              )}
            </>
          )}
          <footer className="crm-workspace-footer">
            <span>Jardines del Encanto · CRM</span>
            <span>Los cambios se confirman al guardarse en PostgreSQL.</span>
          </footer>
        </main>
      </div>
      <dialog
        ref={contactDialog}
        className="crm-modal"
        onCancel={(event) => {
          if (pending) event.preventDefault();
        }}
        aria-labelledby="contact-form-title"
        onClose={() => {
          setContactEditor(null);
          setError("");
        }}
      >
        <div className="crm-modal-header">
          <div>
            <span className="crm-eyebrow">CLIENTES</span>
            <h2 id="contact-form-title">
              {contactEditor === "new"
                ? "Un nuevo contacto."
                : "Editar cliente"}
            </h2>
          </div>
          <button
            className="crm-icon-button"
            aria-label="Cerrar formulario de cliente"
            onClick={() => contactDialog.current?.close()}
            disabled={pending}
          >
            <Icon name="close" />
          </button>
        </div>
        {contactEditor && (
          <form
            key={
              contactEditor === "new"
                ? "new"
                : `${contactEditor.id}-${contactEditor.version}`
            }
            onSubmit={saveContact}
            className="crm-form"
          >
            <p>Solo lo esencial para empezar la conversación.</p>
            <label htmlFor="contact-name">Nombre</label>
            <input
              id="contact-name"
              disabled={pending}
              name="name"
              autoComplete="name"
              required
              maxLength={120}
              autoFocus
              defaultValue={contactEditor === "new" ? "" : contactEditor.name}
            />
            <label htmlFor="contact-phone">Celular</label>
            <input
              id="contact-phone"
              disabled={pending}
              name="phone"
              type="tel"
              autoComplete="tel"
              required
              maxLength={32}
              placeholder="300 123 4567"
              defaultValue={contactEditor === "new" ? "" : contactEditor.phone}
            />
            <label htmlFor="contact-source">Medio de origen</label>
            <select
              id="contact-source"
              disabled={pending}
              name="source"
              required
              defaultValue={contactEditor === "new" ? "" : contactEditor.source}
            >
              <option value="" disabled>
                Selecciona cómo llegó
              </option>
              {sources.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            {error && (
              <p className="crm-error" role="alert">
                {error}
              </p>
            )}
            <div className="crm-form-actions">
              <button
                type="button"
                className="crm-button crm-secondary"
                disabled={pending}
                onClick={() => contactDialog.current?.close()}
              >
                Cancelar
              </button>
              <button className="crm-button" type="submit" disabled={pending}>
                {contactEditor === "new" ? "Crear cliente" : "Guardar cambios"}
              </button>
            </div>
            <span className="crm-form-status" role="status">
              {pending ? "Guardando…" : ""}
            </span>
          </form>
        )}
      </dialog>
      <dialog
        ref={taskDialog}
        className="crm-modal"
        onCancel={(event) => {
          if (pending) event.preventDefault();
        }}
        aria-labelledby="task-form-title"
        onClose={() => {
          setTaskContact(null);
          setError("");
        }}
      >
        <div className="crm-modal-header">
          <div>
            <span className="crm-eyebrow">SEGUIMIENTOS</span>
            <h2 id="task-form-title">El siguiente paso.</h2>
          </div>
          <button
            className="crm-icon-button"
            aria-label="Cerrar formulario de tarea"
            disabled={pending}
            onClick={() => taskDialog.current?.close()}
          >
            <Icon name="close" />
          </button>
        </div>
        {taskContact !== null && (
          <form key={taskContact} onSubmit={saveTask} className="crm-form">
            <label htmlFor="task-contact">Cliente</label>
            <select
              id="task-contact"
              disabled={pending}
              name="contact_id"
              required
              defaultValue={taskContact}
            >
              <option value="" disabled>
                Selecciona un cliente
              </option>
              {data.contacts.map((contact) => (
                <option value={contact.id} key={contact.id}>
                  {contact.name}
                </option>
              ))}
            </select>
            <label htmlFor="task-title">¿Qué sigue?</label>
            <input
              id="task-title"
              disabled={pending}
              name="title"
              autoFocus
              required
              maxLength={160}
              placeholder="Por ejemplo, confirmar la visita"
            />
            <label htmlFor="task-date">Fecha</label>
            <input
              id="task-date"
              disabled={pending}
              name="due_date"
              type="date"
              required
              defaultValue={day}
            />
            {error && (
              <p className="crm-error" role="alert">
                {error}
              </p>
            )}
            <div className="crm-form-actions">
              <button
                type="button"
                className="crm-button crm-secondary"
                disabled={pending}
                onClick={() => taskDialog.current?.close()}
              >
                Cancelar
              </button>
              <button className="crm-button" type="submit" disabled={pending}>
                Guardar tarea
              </button>
            </div>
            <span className="crm-form-status" role="status">
              {pending ? "Guardando…" : ""}
            </span>
          </form>
        )}
      </dialog>
      <dialog
        ref={drawer}
        className="crm-drawer"
        aria-labelledby="client-detail-title"
        onClose={() => {
          setSelection(null);
          setError("");
        }}
      >
        <div className="crm-drawer-heading">
          <span className="crm-eyebrow">FICHA DEL CLIENTE</span>
          <button
            className="crm-icon-button"
            aria-label="Cerrar ficha del cliente"
            onClick={() => drawer.current?.close()}
          >
            <Icon name="close" />
          </button>
        </div>
        {selected && (
          <div className="crm-drawer-body">
            <span className="crm-avatar crm-avatar-large">
              {initials(selected.name)}
            </span>
            <h2 id="client-detail-title">{selected.name}</h2>
            {selected.registration_code && (
              <p>
                Cupo de la página web:{" "}
                <strong>{selected.registration_code}</strong>
              </p>
            )}
            <a href={`tel:${selected.phone}`} className="crm-detail-phone">
              {phoneLabel(selected.phone)}
            </a>
            <div className="crm-detail-actions">
              <a
                className="crm-button crm-secondary"
                href={`https://wa.me/${selected.phone.slice(1)}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Icon name="message" size={16} />
                WhatsApp<span className="crm-sr-only"> en otra pestaña</span>
              </a>
              <button
                className="crm-button crm-secondary"
                onClick={() => editContact(selected)}
              >
                Editar cliente
              </button>
            </div>
            <dl className="crm-detail-facts">
              <div>
                <dt>Medio de origen</dt>
                <dd>{sourceLabel(selected.source)}</dd>
              </div>
              <div>
                <dt>Etapa</dt>
                <dd>
                  {selectedDeal && (
                    <StageSelect
                      pending={pending}
                      onMove={moveDeal}
                      deal={selectedDeal}
                      name={selected.name}
                    />
                  )}
                </dd>
              </div>
            </dl>
            {error && (
              <p className="crm-error" role="alert">
                {error}
              </p>
            )}
            <section className="crm-detail-section">
              <div className="crm-panel-heading">
                <h3>Próximos pasos</h3>
                <button
                  className="crm-inline-link"
                  onClick={() => openTask(selected.id)}
                >
                  <Icon name="plus" size={15} />
                  Agregar
                </button>
              </div>
              {data.tasks
                .filter((task) => task.contact_id === selected.id)
                .map((task) => (
                  <TaskRow
                    contact={contactsById.get(task.contact_id)}
                    day={day}
                    pending={pending}
                    onToggle={toggleTask}
                    onOpen={openContact}
                    key={task.id}
                    task={task}
                  />
                ))}
              {!data.tasks.some((task) => task.contact_id === selected.id) && (
                <p className="crm-subtle">
                  Aún no hay seguimientos para este cliente.
                </p>
              )}
            </section>
            <section className="crm-detail-section">
              <h3>Notas de la conversación</h3>
              <form onSubmit={saveNote} className="crm-note-form">
                <label htmlFor="client-note" className="crm-sr-only">
                  Nueva nota
                </label>
                <textarea
                  id="client-note"
                  disabled={pending}
                  name="body"
                  required
                  maxLength={2000}
                  rows={3}
                  placeholder="Lo que necesitas recordar…"
                />
                <button
                  className="crm-button crm-secondary"
                  type="submit"
                  disabled={pending}
                >
                  Guardar nota
                </button>
              </form>
            </section>
            <section className="crm-detail-section">
              <h3>Actividad</h3>
              {timelineLoading ? (
                <p role="status" className="crm-subtle">
                  Cargando actividad…
                </p>
              ) : (
                <ol className="crm-activity-feed">
                  {timeline.map((item) => (
                    <li key={item.id}>
                      <span className="crm-activity-mark" />
                      <div>
                        <p>{item.body}</p>
                        <time dateTime={item.created_at}>
                          {new Date(item.created_at).toLocaleString("es-CO", {
                            dateStyle: "medium",
                            timeStyle: "short",
                            timeZone: "America/Bogota",
                          })}
                        </time>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </dialog>
    </div>
  );
}
