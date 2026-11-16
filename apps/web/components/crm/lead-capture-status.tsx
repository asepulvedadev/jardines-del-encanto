"use client";

import { useEffect, useState } from "react";

type CaptureStatus = {
  enabled: boolean;
  worker_alive: boolean;
  pending: number;
  failed: number;
  last_error: string | null;
  scans: { last_error: string | null }[];
};

export function LeadCaptureStatus({
  request,
  active,
}: {
  request: <T>(
    path: string,
    payload?: unknown,
    signal?: AbortSignal,
  ) => Promise<T>;
  active: boolean;
}) {
  const [status, setStatus] = useState<CaptureStatus | null>(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const result = await request<CaptureStatus>(
          "lead-capture",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) setStatus(result);
      } catch {
        if (!controller.signal.aborted) setStatus(null);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [request, active]);

  const healthy =
    status?.enabled &&
    status.worker_alive &&
    !status.last_error &&
    !status.failed &&
    !status.scans.some((scan) => scan.last_error);
  return (
    <>
      <p className="inbox-muted" role="status">
        {healthy
          ? `Captura automática activa · respaldo cada minuto · ${status.pending} conversaciones por completar.`
          : status && !status.enabled
            ? "Captura automática desactivada."
            : "Captura automática pendiente de verificación. Revisa los chats para completar los datos faltantes."}
      </p>
      <details className="inbox-raw">
        <summary>Estado de la captura automática</summary>
        <pre>
          {JSON.stringify(status ?? { status: "unavailable" }, null, 2)}
        </pre>
      </details>
    </>
  );
}
