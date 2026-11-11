"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type Connection = {
  available: boolean;
  authorized: boolean;
  needs_authorization: boolean;
  verified_at: number | null;
};

const messages: Record<string, string> = {
  zernio_mcp_disabled: "La conexión OAuth aún no está habilitada en este servidor.",
  zernio_mcp_denied: "Cancelaste la autorización. No se cambió la conexión anterior.",
  zernio_mcp_invalid_state: "Esta autorización venció o pertenece a otra sesión. Inicia de nuevo.",
  zernio_mcp_sign_in_required: "Zernio requiere que vuelvas a iniciar sesión.",
  zernio_mcp_throttled: "Espera un minuto antes de iniciar otra autorización.",
  zernio_replacement_confirmation_required: "Confirma el reemplazo de la autorización actual.",
};

export function ZernioMcp({ csrf }: { csrf: string }) {
  const router = useRouter();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [replace, setReplace] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const started = useRef(false);
  const busy = useRef(false);

  const request = useCallback(async <T,>(action: string, payload?: unknown): Promise<T> => {
    const result = await fetch(`/api/crm/social/mcp/${action}`, {
      method: action === "status" ? "GET" : "POST",
      cache: "no-store", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: action === "status" ? undefined : JSON.stringify(payload ?? {}),
      signal: AbortSignal.timeout(25000),
    }).catch(() => {
      throw new Error("No pudimos contactar al servidor. Revisa tu conexión e intenta de nuevo.");
    });
    if (result.status === 401) {
      router.replace("/login");
      throw new Error("Tu sesión venció. Vuelve a ingresar al CRM.");
    }
    const data = await result.json().catch(() => null);
    if (!result.ok || !data)
      throw new Error(messages[data?.detail] ?? "No pudimos verificar Zernio. No se confirmó la conexión; intenta de nuevo.");
    return data as T;
  }, [csrf, router]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const url = new URL(window.location.href);
    const callback = url.searchParams.has("zernio_callback");
    const values = Object.fromEntries(["state", "code", "iss", "error"].map((key) => [key, url.searchParams.get(key)]));
    const duplicate = ["state", "code", "iss", "error", "zernio_callback"].some((key) => url.searchParams.getAll(key).length > 1);
    if (callback) {
      for (const key of ["state", "code", "iss", "error", "error_description", "error_uri", "zernio_callback"])
        url.searchParams.delete(key);
      // Authorization codes and state never enter browser storage or subsequent referrers.
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
    void (async () => {
      try {
        if (callback) {
          if (duplicate || !values.state || (!values.code && !values.error))
            throw new Error("El retorno de autorización no es válido. Inicia una conexión nueva.");
          await request<Connection>("complete", {
            state: values.state, code: values.code, issuer: values.iss, error: values.error,
          });
          setNotice("Autorización guardada. Pulsa Verificar conexión para comprobar el acceso real.");
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "No se completó la autorización.");
      } finally {
        try { setConnection(await request<Connection>("status")); }
        catch (cause) { setError(cause instanceof Error ? cause.message : "No pudimos consultar la conexión."); }
        setPending(false);
      }
    })();
    // Run once per mount: replaying a callback would reuse a consumed authorization code.
  }, [request]);

  async function perform(action: () => Promise<void>) {
    if (busy.current || pending) return;
    busy.current = true;
    setPending(true); setError(""); setNotice("");
    try { await action(); }
    catch (cause) {
      setError(cause instanceof Error ? cause.message : "No pudimos contactar a Zernio.");
      try { setConnection(await request<Connection>("status")); } catch { /* Keep prior state. */ }
    } finally { busy.current = false; setPending(false); }
  }

  return (
    <section className="crm-panel social-setup" aria-labelledby="zernio-mcp-heading" aria-busy={pending}>
      <div className="social-section-heading">
        <div>
          <h2 id="zernio-mcp-heading">Conectar con Zernio</h2>
          <p>Inicia sesión en Zernio y autoriza este CRM mediante MCP y OAuth. No necesitas copiar una API key.</p>
        </div>
        <span className={`social-status ${connection?.verified_at ? "social-status-good" : ""}`}>
          {connection?.needs_authorization ? "Requiere autorización" : connection?.verified_at ? "Verificado" : connection?.authorized ? "Autorizado" : "Sin conectar"}
        </span>
      </div>
      {error && <p className="crm-error" role="alert">{error}</p>}
      <p className="social-feedback" role="status">{pending ? "Consultando la conexión…" : notice}</p>
      {connection && !connection.available && <p className="social-help">OAuth está preparado, pero requiere habilitación en el servidor antes de iniciar sesión.</p>}
      <p className="social-help">Permiso solicitado: consultar cuentas. Esta conexión todavía no vincula un perfil al CRM ni permite publicar, enviar mensajes o ejecutar acciones de Hermes.</p>
      {connection?.verified_at && <p className="social-help">Última comprobación: {new Date(connection.verified_at * 1000).toLocaleString("es-CO", { timeZone: "America/Bogota" })}. El estado se vuelve a consultar al pulsar Verificar conexión.</p>}
      {connection?.authorized && <label className="social-check">
        <input type="checkbox" checked={replace} disabled={pending} onChange={(event) => setReplace(event.target.checked)} />
        Confirmo que quiero reemplazar la autorización actual.
      </label>}
      <div className="social-actions">
        <button className="crm-button" disabled={pending || !connection?.available || (connection.authorized && !replace)} onClick={() => void perform(async () => {
          const result = await request<{ auth_url: string }>("start", { replace });
          const url = new URL(result.auth_url);
          if (url.origin !== "https://zernio.com" || url.pathname !== "/oauth/authorize" || url.username || url.password)
            throw new Error("El enlace de autorización no es seguro. No se abrió ninguna página externa.");
          window.location.assign(url.href);
        })}>{connection?.authorized ? "Volver a autorizar" : "Autorizar con Zernio"}</button>
        {connection?.authorized && <>
          <button className="crm-button crm-secondary" disabled={pending || !connection.available} onClick={() => void perform(async () => {
            setConnection(await request<Connection>("check"));
            setNotice("Acceso MCP comprobado con una consulta real de cuentas. No se modificó ninguna red social.");
          })}>Verificar conexión</button>
          <button className="crm-button crm-secondary" disabled={pending} onClick={() => setDisconnecting(!disconnecting)}>Desconectar</button>
        </>}
        {!connection && !pending && <button className="crm-button crm-secondary" onClick={() => void perform(async () => setConnection(await request<Connection>("status")))}>Volver a consultar</button>}
      </div>
      {disconnecting && <div className="social-actions">
        <p>Se eliminará la autorización guardada aquí. Revoca también el acceso de este cliente en Zernio.</p>
        <button className="crm-button crm-secondary" disabled={pending} onClick={() => void perform(async () => {
          setConnection(await request<Connection>("disconnect"));
          setDisconnecting(false); setReplace(false);
          setNotice("Autorización local eliminada. Las cuentas sociales no se desconectaron de Zernio.");
        })}>Confirmar desconexión local</button>
      </div>}
    </section>
  );
}
