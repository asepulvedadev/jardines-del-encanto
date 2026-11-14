import type { SaraProgress } from "./sara-types";

export function SaraWorking({
  progress,
  unavailable,
}: {
  progress?: SaraProgress;
  unavailable: boolean;
}) {
  const heading = !progress
    ? "Enviando tu mensaje…"
    : progress.phase === "issued"
      ? "Mensaje recibido · Esperando a Sara"
      : progress.phase === "finished"
        ? "Respuesta generada; confirmando el envío…"
        : progress.phase === "failed"
          ? "Comprobando el resultado del envío…"
          : "Sara está trabajando…";
  return (
    <section
      className="sara-working-card"
      aria-label="Actividad en curso de Sara"
    >
      <div className="sara-working" role="status">
        <span className="sara-working-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <strong>{heading}</strong>
      </div>
      {progress && (
        <p className="sara-working-caption">
          {progress.activities.length
            ? "Actividad confirmada"
            : "Esperando respuesta de Hermes…"}
        </p>
      )}
      {!!progress?.activities.length && (
        <ul
          aria-label="Operaciones confirmadas de Sara"
          aria-live="polite"
          aria-relevant="additions"
        >
          {progress.activities.map((activity) => (
            <li key={activity.id} data-outcome={activity.outcome}>
              <span aria-hidden="true">
                {activity.outcome === "failed"
                  ? "!"
                  : activity.outcome === "proposal"
                    ? "○"
                    : "✓"}
              </span>
              <div>
                <strong>{activity.label}</strong>
                <small>
                  {activity.outcome === "proposal"
                    ? "Propuesta preparada · Requiere aprobación"
                    : activity.outcome === "failed"
                      ? "No se pudo completar"
                      : "Operación completada"}
                </small>
              </div>
            </li>
          ))}
        </ul>
      )}
      {unavailable && (
        <p className="sara-working-caption" role="status">
          No pudimos actualizar la actividad. El envío continúa; no lo repitas.
        </p>
      )}
    </section>
  );
}
