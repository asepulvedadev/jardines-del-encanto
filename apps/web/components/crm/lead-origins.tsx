import {
  leadOriginLabels,
  sourceLabel,
  sources,
  type LeadOrigin,
  type LeadOriginsData,
} from "./types";
import "./lead-origins.css";

const groups: { key: LeadOrigin; description: string }[] = [
  { key: "campaign", description: "Origen registrado como campaña de redes." },
  {
    key: "template",
    description: "Clientes que respondieron a un envío de WhatsApp verificado.",
  },
  {
    key: "imported",
    description: "Clientes importados, aún sin respuesta verificada a templates.",
  },
  { key: "other", description: "WhatsApp, página web, presenciales y referidos." },
];
const number = new Intl.NumberFormat("es-CO");
const percent = new Intl.NumberFormat("es-CO", {
  style: "percent",
  maximumFractionDigits: 1,
});

function reconciles(total: number, data?: LeadOriginsData): data is LeadOriginsData {
  const count = (value: unknown): value is number =>
    Number.isSafeInteger(value) && Number(value) >= 0;
  return (
    !!data && count(total) && groups.every(({ key }) => count(data[key])) &&
    groups.reduce((sum, { key }) => sum + data[key], 0) === total &&
    Array.isArray(data.other_sources) &&
    data.other_sources.every((row) =>
      row && sources.some(([key]) => key === row.source) && count(row.count)
    ) &&
    data.other_sources.reduce((sum, row) => sum + row.count, 0) === data.other
  );
}

export function LeadOrigins({
  total,
  origins,
  pending,
  onSelect,
}: {
  total: number;
  origins?: LeadOriginsData;
  pending: boolean;
  onSelect: (origin: LeadOrigin) => void;
}) {
  const ready = reconciles(total, origins);
  return (
    <section className="crm-origin-section" aria-labelledby="crm-origin-title">
      <header className="crm-origin-heading">
        <div>
          <h2 id="crm-origin-title">De dónde vienen tus clientes</h2>
          <p>Cada cliente aparece en un solo grupo.</p>
        </div>
        <span>
          <strong>{number.format(total)}</strong> clientes únicos
        </span>
      </header>
      {!ready ? (
        <p role="status">
          Desglose no disponible. Actualiza el dashboard para consultar la clasificación.
        </p>
      ) : <>
        {total === 0 && <p>Aún no hay clientes registrados.</p>}
        <div className="crm-origin-bar" aria-hidden="true">
          {groups.map(({ key }) => (
            <span
              key={key}
              className={`origin-${key}`}
              style={{ width: `${total ? origins[key] / total * 100 : 0}%` }}
            />
          ))}
        </div>
        <ul className="crm-origin-cards">
          {groups.map(({ key, description }) => (
            <li key={key}>
              <button
                disabled={pending}
                onClick={() => onSelect(key)}
                aria-label={`${leadOriginLabels[key]}: ${number.format(origins[key])} clientes. Ver clientes.`}
              >
                <span className="crm-origin-label">
                  <i className={`origin-${key}`} aria-hidden="true" />
                  {leadOriginLabels[key]}
                </span>
                <span className="crm-origin-value">
                  <strong>{number.format(origins[key])}</strong>
                  <small>{percent.format(total ? origins[key] / total : 0)} del total</small>
                </span>
                <span className="crm-origin-description">{description}</span>
                <span className="crm-origin-action" aria-hidden="true">
                  Ver clientes <span>↗</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {origins.other_sources.length > 0 && (
          <div className="crm-origin-breakdown">
            <span>Dentro de otros orígenes</span>
            <ul>
              {origins.other_sources.map((row) => (
                <li key={row.source}>
                  {sourceLabel(row.source)} <strong>{number.format(row.count)}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
        <details className="crm-origin-help">
          <summary>Cómo se clasifican</summary>
          <p><strong>Campañas y redes:</strong> usa el origen registrado en el CRM. No confirma atribución a un anuncio pagado.</p>
          <p><strong>Templates:</strong> requiere evidencia del envío y una respuesta posterior del mismo cliente. No incluye destinatarios que no respondieron.</p>
          <p>La respuesta verificada a un template tiene prioridad sobre los demás grupos. La base importada se cuenta aparte de campañas y redes. Se conserva el origen original en la ficha del cliente.</p>
        </details>
      </>}
    </section>
  );
}
