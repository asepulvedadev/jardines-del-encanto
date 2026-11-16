"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import "./analytics-panel.css";

type Period = 1 | 7 | 30;
type DailyMetric = { date: string; pageviews: number | null; sessions: number | null; registrations: number };
type CountMetric = { name: string; count: number };
export type AnalyticsData = {
  status: "ready" | "not_configured" | "unavailable";
  timezone: "America/Bogota";
  days: Period;
  updated_at: string | null;
  totals: { visitors: number | null; sessions: number | null; pageviews: number | null; clicks: number | null; registrations: number };
  daily: DailyMetric[];
  events: CountMetric[];
  sources: CountMetric[];
};

const count = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const nullableCount = (value: unknown) => value === null || count(value);
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const validDate = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

export function parseAnalyticsSummary(value: unknown, days: Period): AnalyticsData {
  if (!record(value) || !["ready", "not_configured", "unavailable"].includes(String(value.status)) || value.timezone !== "America/Bogota" || value.days !== days || !(value.updated_at === null || (typeof value.updated_at === "string" && Number.isFinite(Date.parse(value.updated_at)))) || !record(value.totals)) throw new Error("Invalid analytics summary");
  const totals = value.totals;
  if (![totals.visitors, totals.sessions, totals.pageviews, totals.clicks].every(nullableCount) || !count(totals.registrations)) throw new Error("Invalid analytics totals");
  if (!Array.isArray(value.daily) || value.daily.length > days || value.daily.some((day) => !record(day) || !validDate(day.date) || !nullableCount(day.pageviews) || !nullableCount(day.sessions) || !count(day.registrations))) throw new Error("Invalid daily analytics");
  const dates = value.daily.map((day) => day.date as string);
  if (new Set(dates).size !== dates.length || dates.some((date, index) => index > 0 && date <= dates[index - 1])) throw new Error("Invalid analytics date order");
  for (const entries of [value.events, value.sources]) {
    if (!Array.isArray(entries) || entries.length > 100 || entries.some((entry) => !record(entry) || typeof entry.name !== "string" || !entry.name.trim() || entry.name.length > 180 || !count(entry.count))) throw new Error("Invalid analytics breakdown");
  }
  return value as AnalyticsData;
}

const number = (value: number) => new Intl.NumberFormat("es-CO").format(value);
const dateLabel = (date: string) => new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short", timeZone: "America/Bogota" }).format(new Date(`${date}T12:00:00Z`));
const eventNames: Record<string, string> = {
  whatsapp_click: "WhatsApp", whatsapp: "WhatsApp", group_click: "Grupo de WhatsApp", whatsapp_group_click: "Grupo de WhatsApp", visit_click: "Agendar visita", plan_click: "Explorar plano", plan_open: "Explorar plano", registration_open: "Abrir registro", masterplan_click: "Explorar plano", registration: "Registro completado", registration_success: "Registro completado", landing_registration: "Registro completado",
};
const sourceNames: Record<string, string> = { facebook: "Facebook", instagram: "Instagram", tiktok: "TikTok", google: "Google", whatsapp: "WhatsApp", other: "Otros", direct: "Directo", "(direct)": "Directo" };

export function analyticsChartBars(daily: { date: string; pageviews: number | null }[]) {
  const maximum = Math.max(1, ...daily.map((day) => day.pageviews ?? 0));
  return daily.map((day) => ({ ...day, height: day.pageviews === null ? null : (day.pageviews / maximum) * 118 }));
}

function DailyChart({ daily }: { daily: DailyMetric[] }) {
  const bars = analyticsChartBars(daily);
  const hasMeasurements = bars.some((bar) => bar.pageviews !== null);
  const maximum = Math.max(1, ...daily.map((day) => day.pageviews ?? 0));
  const step = 460 / Math.max(1, daily.length);
  return (
    <div className="crm-analytics-chart">
      <div className="crm-analytics-section-heading"><h3>Vistas por día</h3><span>Hora de Colombia</span></div>
      {hasMeasurements ? <div className="crm-analytics-plot" tabIndex={0} role="region" aria-label="Gráfico desplazable de vistas por día"><svg viewBox="0 0 520 176" role="img" aria-label={`Vistas de página por día. Máximo: ${number(maximum)}. Los valores completos están en la tabla de datos.`}>
        <line x1="42" y1="140" x2="506" y2="140" className="crm-analytics-axis" />
        <line x1="42" y1="22" x2="506" y2="22" className="crm-analytics-gridline" />
        <text x="34" y="26" textAnchor="end">{number(maximum)}</text><text x="34" y="144" textAnchor="end">0</text>
        {bars.map((bar, index) => {
          const center = 46 + step * (index + 0.5);
          return <g key={bar.date}>
            {bar.height !== null && bar.height > 0 && <rect x={center - Math.min(12, step * 0.3)} y={140 - bar.height} width={Math.min(24, step * 0.6)} height={bar.height} rx="2"><title>{`${dateLabel(bar.date)}: ${number(bar.pageviews!)} vistas`}</title></rect>}
            {(daily.length <= 7 || index % 5 === 0 || index === daily.length - 1) && <text x={center} y="164" textAnchor="middle">{dateLabel(bar.date)}</text>}
          </g>;
        })}
      </svg></div> : <p className="crm-analytics-unavailable">Vistas por día no disponibles.</p>}
      {hasMeasurements && daily.every((day) => day.pageviews === 0) && <p className="crm-analytics-unavailable">Aún no hay actividad registrada.</p>}
      <details className="crm-analytics-details"><summary>Ver datos por día</summary>
        <div className="crm-analytics-table-wrap" tabIndex={0} role="region" aria-label="Métricas diarias, tabla desplazable"><table>
          <caption className="sr-only">Métricas de la landing por día, hora de Colombia</caption>
          <thead><tr><th scope="col">Fecha</th><th scope="col">Vistas</th><th scope="col">Sesiones</th><th scope="col">Leads web</th></tr></thead>
          <tbody>{daily.map((day) => <tr key={day.date}><th scope="row">{dateLabel(day.date)}</th><td>{day.pageviews === null ? "No disponible" : number(day.pageviews)}</td><td>{day.sessions === null ? "No disponible" : number(day.sessions)}</td><td>{number(day.registrations)}</td></tr>)}</tbody>
        </table></div>
      </details>
    </div>
  );
}

function Breakdown({ title, entries, names, empty }: { title: string; entries: CountMetric[]; names: Record<string, string>; empty: string }) {
  const ranked = [...entries].sort((a, b) => b.count - a.count).slice(0, 5);
  const maximum = Math.max(1, ...ranked.map((entry) => entry.count));
  return <div className="crm-analytics-breakdown"><h3>{title}</h3>{ranked.length ? <ul>{ranked.map((entry) => <li key={entry.name}><div><span>{names[entry.name.toLowerCase()] ?? entry.name}</span><strong>{number(entry.count)}</strong></div><span className="crm-analytics-track" aria-hidden="true"><span style={{ width: `${entry.count / maximum * 100}%` }} /></span></li>)}</ul> : <p className="crm-analytics-unavailable">{empty}</p>}</div>;
}

export function AnalyticsSummary({ data, loading, error, days, onDaysChange, onRetry }: { data: AnalyticsData | null; loading: boolean; error: string; days: Period; onDaysChange: (days: Period) => void; onRetry: () => void }) {
  const metrics = [
    ["Visitantes", data?.totals.visitors], ["Vistas de página", data?.totals.pageviews], ["Clics", data?.totals.clicks], ["Leads web", data?.totals.registrations],
  ] as const;
  return <section className="crm-panel crm-analytics" aria-labelledby="crm-analytics-title" aria-busy={loading}>
    <div className="crm-analytics-heading"><h2 id="crm-analytics-title">Rendimiento de la landing</h2><div className="crm-analytics-period" role="group" aria-label="Período de las métricas">{([1, 7, 30] as const).map((period) => <button key={period} type="button" aria-pressed={days === period} onClick={() => onDaysChange(period)}>{period === 1 ? "Hoy" : `${period} días`}</button>)}</div></div>
    {loading && <p className="crm-analytics-status" role="status">Cargando métricas…</p>}
    {error && <div className="crm-analytics-error" role="alert"><span>{error}</span><button type="button" onClick={onRetry}>Reintentar</button></div>}
    {data && <>
      {data.status !== "ready" && <div className="crm-analytics-status"><span>{data.status === "not_configured" ? "Medición de visitas pendiente." : "Medición temporalmente no disponible."}</span>{data.status === "unavailable" && <button type="button" onClick={onRetry}>Reintentar</button>}</div>}
      <div className="crm-analytics-kpis">{metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value == null ? <span aria-label="No disponible">—</span> : number(value)}</strong></div>)}</div>
      <DailyChart daily={data.daily} />
      {data.status === "ready" && <div className="crm-analytics-breakdowns"><Breakdown title="Origen de las visitas" entries={data.sources} names={sourceNames} empty="Sin orígenes registrados." /><Breakdown title="Acciones en la landing" entries={data.events} names={eventNames} empty="Sin acciones registradas." /></div>}
      <div className="crm-analytics-footer"><span>Leads web: registros de la landing, no clics.</span>{data.updated_at && <time dateTime={data.updated_at}>Actualizado {new Date(data.updated_at).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", timeZone: data.timezone })}</time>}</div>
    </>}
  </section>;
}

export function AnalyticsPanel() {
  const router = useRouter();
  const [days, setDays] = useState<Period>(7);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    const run = ++generation.current;
    let controller: AbortController | null = null;
    let busy = false;
    const load = async () => {
      if (busy || document.visibilityState === "hidden") return;
      busy = true;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 25_000);
      setLoading(true);
      setError("");
      try {
        const response = await fetch(`/api/crm/analytics/summary?days=${days}`, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
        if (run !== generation.current) return;
        if (response.status === 401) { router.replace("/login"); return; }
        if (!response.ok) throw new Error("Analytics request failed");
        const summary = parseAnalyticsSummary(await response.json(), days);
        if (run === generation.current) setData(summary);
      } catch {
        if (run === generation.current) setError("No se pudieron cargar las métricas.");
      } finally {
        window.clearTimeout(timeout);
        busy = false;
        if (run === generation.current) setLoading(false);
      }
    };
    setData(null);
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { generation.current++; controller?.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [days, attempt, router]);
  return <AnalyticsSummary data={data} loading={loading} error={error} days={days} onDaysChange={setDays} onRetry={() => setAttempt((value) => value + 1)} />;
}
