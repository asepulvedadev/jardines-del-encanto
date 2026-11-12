import type { SettingsRequest } from "./settings-types";
export function voiceRequest(
  csrf: string,
  onExpired: () => void,
  transport: typeof fetch = fetch,
): SettingsRequest {
  return async <T>(
    path: string,
    method = "GET",
    payload?: unknown,
  ): Promise<T> => {
    const body = method === "GET" ? undefined : JSON.stringify(payload ?? {});
    if (body && new TextEncoder().encode(body).byteLength > 16384)
      throw new Error("Los argumentos superan el tamaño permitido.");
    let response: Response;
    try {
      response = await transport(`/api/crm/${path}`, {
        method,
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body,
        signal: AbortSignal.timeout(95000),
      });
    } catch {
      throw new Error(
        "No se confirmó la respuesta. No repitas una acción enviada; consulta su estado.",
      );
    }
    if (response.status === 401) {
      onExpired();
      throw new Error("Tu sesión finalizó. Vuelve a ingresar.");
    }
    const result = await response.json().catch(() => null);
    if (!response.ok || !result) {
      const messages: Record<string, string> = {
        connection_disabled: "Retell está pausado. Actívalo en Conexiones.",
        retell_unavailable: "Retell no está disponible. Revisa Conexiones.",
        retell_provider_changed:
          "La conexión cambió. Actualiza y prepara otra propuesta.",
        retell_schema_changed: "La función cambió. Actualiza su esquema.",
        proposal_expired: "La propuesta venció. Prepara una nueva.",
        invalid_input: "Revisa los campos y los argumentos.",
        permission_denied: "No tienes permiso para esta acción.",
        invalid_csrf: "Tu sesión cambió. Recarga antes de continuar.",
        record_changed: "El registro cambió. Actualiza antes de guardar.",
      };
      throw new Error(
        messages[result?.detail] ??
          "No se confirmó la operación. Actualiza y revisa el estado antes de repetirla.",
      );
    }
    return result as T;
  };
}
