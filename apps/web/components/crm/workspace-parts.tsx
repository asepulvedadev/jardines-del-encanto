import type { ReactNode } from "react";
import { Icon } from "./icon";
import {
  shortDate,
  stages,
  type Contact,
  type Deal,
  type Stage,
  type Task,
} from "./types";

export function StageSelect({
  deal,
  name,
  pending,
  onMove,
}: {
  deal: Deal;
  name: string;
  pending: boolean;
  onMove: (deal: Deal, stage: Stage) => void;
}) {
  return (
    <select
      className={`crm-stage-select stage-${deal.stage}`}
      aria-label={`Etapa de ${name}`}
      value={deal.stage}
      disabled={pending}
      onChange={(event) => onMove(deal, event.target.value as Stage)}
    >
      {stages.map(([key, label]) => (
        <option key={key} value={key}>
          {label}
        </option>
      ))}
    </select>
  );
}

export function Empty({
  title,
  children,
  action = true,
  onCreate,
}: {
  title: string;
  children: ReactNode;
  action?: boolean;
  onCreate: () => void;
}) {
  return (
    <div className="crm-empty">
      <span className="crm-empty-icon">
        <Icon name="leaf" size={26} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action && (
        <button className="crm-button crm-secondary" onClick={onCreate}>
          <Icon name="plus" />
          Crear primer cliente
        </button>
      )}
    </div>
  );
}

export function TaskRow({
  task,
  contact,
  day,
  pending,
  onToggle,
  onOpen,
}: {
  task: Task;
  contact?: Contact;
  day: string;
  pending: boolean;
  onToggle: (task: Task) => void;
  onOpen: (contact: Contact) => void;
}) {
  const overdue = !task.completed && task.due_date < day;
  return (
    <div className={`crm-task-row ${task.completed ? "is-completed" : ""}`}>
      <label className="crm-task-check">
        <input
          type="checkbox"
          checked={task.completed}
          disabled={pending}
          aria-label={`${task.completed ? "Reabrir" : "Completar"}: ${task.title}`}
          onChange={() => onToggle(task)}
        />
      </label>
      <div>
        <strong>{task.title}</strong>
        {contact && (
          <button className="crm-inline-link" onClick={() => onOpen(contact)}>
            {contact.name}
          </button>
        )}
      </div>
      <span className={overdue ? "crm-due is-overdue" : "crm-due"}>
        <Icon name="calendar" size={14} />
        {shortDate(task.due_date)}
        {overdue && <span className="crm-sr-only">, vencido</span>}
      </span>
    </div>
  );
}
