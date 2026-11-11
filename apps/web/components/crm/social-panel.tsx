"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "./icon";
import { ZernioMcp } from "./zernio-mcp";
import {
  socialPlatforms,
  type SocialCompletion,
  type SocialIntent,
  type SocialPlatform,
  type SocialSettings,
} from "./social-types";
import "../../app/crm/social.css";

const intentStorageKey = "jardines.social-intent.v1";
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const authorizationDomains = [
  "zernio.com",
  "facebook.com",
  "instagram.com",
  "tiktok.com",
];

function authorizationUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      (url.port === "" || url.port === "443") &&
      authorizationDomains.some(
        (domain) =>
          url.hostname === domain || url.hostname.endsWith(`.${domain}`),
      )
      ? url.href
      : null;
  } catch {
    return null;
  }
}
function dateLabel(value: string | null) {
  if (!value || Number.isNaN(Date.parse(value))) return "Sin registro";
  return new Date(value).toLocaleString("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Bogota",
  });
}
function statusLabel(value: string) {
  return (
    (
      {
        connected: "Conectado",
        active: "Activo",
        pending: "Pendiente",
        disconnected: "Desconectado",
        expired: "Vencido",
        rejected: "Rechazado",
        canceled: "Cancelado",
        cancelled: "Cancelado",
        error: "Requiere revisión",
        received: "Recibido",
        processed: "Procesado",
        ignored: "Omitido",
        recorded: "Registrado",
        failed: "No procesado",
      } as Record<string, string>
    )[value] ?? "Por verificar"
  );
}
function socialError(code: unknown): string {
  return (
    (
      {
        zernio_not_configured:
          "Primero verifica y guarda la configuración de Zernio.",
        zernio_configuration_unavailable:
          "La configuración segura de Zernio no está disponible en el servidor. Solicita su revisión al administrador.",
        zernio_replacement_confirmation_required:
          "Ya hay una credencial guardada. Usa Reemplazar credencial para cambiarla.",
        zernio_unavailable:
          "No pudimos verificar la información con Zernio. Intenta de nuevo más tarde.",
        zernio_profile_mismatch:
          "La credencial no tiene acceso al perfil indicado. Revisa el ID y los permisos del perfil de la marca.",
        zernio_invalid_profile:
          "No pudimos validar el perfil de la marca. Revisa el ID y vuelve a intentar.",
        zernio_invalid_accounts:
          "Zernio devolvió información de cuentas que no pudimos validar. Actualiza las conexiones de nuevo.",
        zernio_invalid_connection:
          "No pudimos validar la autorización de la plataforma. No se confirmó ninguna conexión.",
        zernio_intent_not_found:
          "No encontramos una autorización válida para esta sesión. Inicia una conexión nueva.",
        zernio_intent_expired:
          "La autorización venció. Inicia una conexión nueva.",
        unsupported_platform:
          "Esta plataforma aún no está disponible para conectar desde el CRM.",
        social_not_configured:
          "Primero verifica y guarda la configuración de Zernio.",
        not_configured: "Primero verifica y guarda la configuración de Zernio.",
        invalid_profile_id:
          "El perfil debe tener un identificador de 24 caracteres hexadecimales.",
        invalid_input: "Revisa la credencial y el identificador del perfil.",
        invalid_credentials:
          "Zernio no aceptó la credencial. Revisa sus permisos y vuelve a intentar.",
        invalid_csrf: "Tu sesión cambió. Recarga la página antes de continuar.",
        authentication_required: "Tu sesión finalizó. Vuelve a ingresar.",
        permission_denied:
          "La credencial no tiene los permisos necesarios para esta acción.",
        vendor_rejected:
          "El proveedor rechazó la solicitud. Revisa la cuenta y sus permisos.",
        intent_expired: "La autorización venció. Inicia una conexión nueva.",
        intent_not_found:
          "No encontramos una autorización válida para esta sesión.",
        intent_conflict:
          "Esta autorización no coincide con la configuración actual. Inicia de nuevo.",
        credentials_already_configured:
          "Ya hay una credencial guardada. Usa Reemplazar credencial para cambiarla.",
        conflict:
          "La configuración cambió. Actualiza las conexiones antes de continuar.",
        truncated:
          "El proveedor devolvió datos incompletos. Intenta actualizar de nuevo.",
        canceled:
          "La autorización fue cancelada. Puedes iniciar una conexión nueva.",
        rejected:
          "La autorización fue rechazada. Revisa los permisos antes de intentar de nuevo.",
        unsafe_authorization_url:
          "No pudimos validar el enlace de autorización. No se abrió ninguna página externa.",
      } as Record<string, string>
    )[typeof code === "string" ? code : ""] ??
    "No pudimos completar la solicitud. No se confirmó ningún cambio; intenta de nuevo."
  );
}
class SocialRequestError extends Error {
  constructor(readonly code: unknown) {
    super(socialError(code));
  }
}
function rememberIntent(
  intent: Pick<SocialIntent, "intent_id" | "platform"> | null,
) {
  try {
    if (intent)
      sessionStorage.setItem(
        intentStorageKey,
        JSON.stringify({
          intent_id: intent.intent_id,
          platform: intent.platform,
        }),
      );
    else sessionStorage.removeItem(intentStorageKey);
  } catch {
    /* Connection remains usable when browser storage is unavailable. */
  }
}

export function SocialPanel({ csrf }: { csrf: string }) {
  const router = useRouter();
  const [settings, setSettings] = useState<SocialSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [intent, setIntent] = useState<SocialIntent | null>(null);
  const [intentStatus, setIntentStatus] = useState("pending");
  const keyInput = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const mounted = useRef(false);
  const callbackHandled = useRef(false);

  const request = useCallback(
    async <T,>(
      path: string,
      method = "GET",
      payload?: unknown,
      signal?: AbortSignal,
    ): Promise<T> => {
      const response = await fetch(`/api/crm/social/${path}`, {
        method,
        cache: "no-store",
        credentials: "same-origin",
        signal,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: method === "GET" ? undefined : JSON.stringify(payload ?? {}),
      }).catch(() => {
        throw new Error(
          "No pudimos contactar al servidor. Revisa tu conexión e intenta de nuevo.",
        );
      });
      if (response.status === 401) {
        router.replace("/login");
        router.refresh();
        throw new Error(socialError("authentication_required"));
      }
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new SocialRequestError(result?.detail);
      if (!result) throw new Error(socialError("truncated"));
      return result as T;
    },
    [csrf, router],
  );

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    request<SocialSettings>("settings", "GET", undefined, controller.signal)
      .then((result) => {
        if (mounted.current && !controller.signal.aborted) setSettings(result);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : socialError(null));
      })
      .finally(() => {
        if (mounted.current && !controller.signal.aborted) setLoading(false);
      });
    return () => {
      mounted.current = false;
      controller.abort();
      if (keyInput.current) keyInput.current.value = "";
    };
  }, [request]);

  async function perform(action: () => Promise<void>) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (cause) {
      if (mounted.current)
        setError(cause instanceof Error ? cause.message : socialError(null));
    } finally {
      busy.current = false;
      if (mounted.current) setPending(false);
    }
  }

  const complete = useCallback(
    async (id: string) => {
      let result: SocialCompletion;
      try {
        result = await request<SocialCompletion>("complete", "POST", {
          intent_id: id,
        });
      } catch (cause) {
        if (mounted.current && cause instanceof SocialRequestError) {
          const status = (
            {
              zernio_intent_expired: "expired",
              intent_expired: "expired",
              expired: "expired",
              rejected: "rejected",
              canceled: "canceled",
              cancelled: "canceled",
            } as Record<string, string>
          )[String(cause.code)];
          if (status) setIntentStatus(status);
        }
        throw cause;
      }
      const nextSettings =
        result.settings ?? (await request<SocialSettings>("settings"));
      if (!mounted.current) return;
      setSettings(nextSettings);
      setIntentStatus(result.status);
      if (result.status === "connected") {
        setIntent(null);
        rememberIntent(null);
        setNotice("Conexión confirmada por el servidor.");
      } else
        setNotice(
          "La conexión sigue pendiente. Completa la autorización en la plataforma y comprueba de nuevo.",
        );
    },
    [request],
  );

  useEffect(() => {
    if (loading || !settings || callbackHandled.current) return;
    callbackHandled.current = true;
    const url = new URL(window.location.href);
    const callbackId = url.searchParams.get("social_intent");
    if (callbackId !== null) {
      url.searchParams.delete("social_intent");
      router.replace(`${url.pathname}${url.search}${url.hash}`, {
        scroll: false,
      });
    }
    let remembered: { intent_id: string; platform: SocialPlatform } | null =
      null;
    try {
      const raw = sessionStorage.getItem(intentStorageKey);
      const parsed = raw ? JSON.parse(raw) : null;
      if (
        parsed &&
        uuidPattern.test(parsed.intent_id) &&
        socialPlatforms.some(([key]) => key === parsed.platform)
      )
        remembered = parsed;
    } catch {
      /* Browser storage is optional and never contains credentials. */
    }
    if (remembered)
      setIntent({
        ...remembered,
        auth_url: null,
        code: null,
        expires_at: "",
        instructions: null,
      });
    if (callbackId !== null && !uuidPattern.test(callbackId)) {
      setError(
        "El identificador de autorización no es válido. Inicia una conexión nueva.",
      );
      return;
    }
    if (!callbackId) return;
    if (!remembered || remembered.intent_id !== callbackId) {
      setIntent({
        intent_id: callbackId,
        platform: null,
        auth_url: null,
        code: null,
        expires_at: "",
        instructions: null,
      });
    }
    // A return URL is not proof of a connection; only the authenticated server can confirm it.
    busy.current = true;
    setPending(true);
    complete(callbackId)
      .catch((cause) => {
        if (mounted.current)
          setError(cause instanceof Error ? cause.message : socialError(null));
      })
      .finally(() => {
        busy.current = false;
        if (mounted.current) setPending(false);
      });
  }, [complete, loading, router, settings]);

  async function saveSettings(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    const form = new FormData(event.currentTarget);
    const apiKey = String(form.get("api_key") ?? "").trim();
    const profileId = String(form.get("profile_id") ?? "").trim();
    await perform(async () => {
      try {
        const result = await request<SocialSettings>("settings", "POST", {
          api_key: apiKey,
          profile_id: profileId,
          ...(replacing ? { replace: true } : {}),
        });
        if (!mounted.current) return;
        setSettings(result);
        setReplacing(false);
        setIntent(null);
        rememberIntent(null);
        setNotice(
          "Credencial y perfil verificados. La credencial se guarda solo en el servidor.",
        );
      } finally {
        if (keyInput.current) keyInput.current.value = "";
      }
    });
  }
  async function connect(platform: SocialPlatform) {
    await perform(async () => {
      const result = await request<Omit<SocialIntent, "platform">>(
        `connect/${platform}`,
        "POST",
      );
      if (!uuidPattern.test(result.intent_id))
        throw new Error(socialError("truncated"));
      if (result.auth_url && !authorizationUrl(result.auth_url))
        throw new Error(socialError("unsafe_authorization_url"));
      if (!mounted.current) return;
      setIntent({ ...result, platform });
      setIntentStatus("pending");
      rememberIntent({ intent_id: result.intent_id, platform });
      setNotice("Autorización preparada. La cuenta todavía no está conectada.");
    });
  }
  function cancelIntent() {
    setIntent(null);
    setIntentStatus("canceled");
    rememberIntent(null);
    setNotice(
      "Autorización cerrada en este navegador. Si no la completaste, vencerá en el servidor.",
    );
  }

  const safeUrl = intent ? authorizationUrl(intent.auth_url) : null;
  const expired = Boolean(
    intent?.expires_at && Date.parse(intent.expires_at) <= Date.now(),
  );
  const intentPlatform =
    socialPlatforms.find(([key]) => key === intent?.platform)?.[1] ??
    "el canal";

  return (
    <div className="crm-social" aria-busy={pending || loading}>
      <ZernioMcp csrf={csrf} />
      <div className="social-overview">
        <div>
          <span className="social-section-label">CANALES DE LA MARCA</span>
          <p>
            Conecta tus cuentas sin salir del flujo de trabajo del CRM. Cada
            plataforma conserva su propia autorización.
          </p>
        </div>
        <button
          className="crm-button crm-secondary"
          disabled={pending || loading || !settings?.configured}
          onClick={() =>
            void perform(async () => {
              const result = await request<SocialSettings>("sync", "POST");
              if (mounted.current) {
                setSettings(result);
                setNotice("Estado de las conexiones actualizado.");
              }
            })
          }
        >
          Actualizar conexiones
        </button>
      </div>
      {error ? (
        <div className="crm-error" role="alert">
          {error}
        </div>
      ) : null}
      <p className="social-feedback" role="status">
        {pending ? "Verificando con el servidor…" : notice}
      </p>
      {loading ? (
        <p role="status">Consultando la configuración de los canales…</p>
      ) : null}
      {!loading && !settings ? (
        <button
          className="crm-button crm-secondary"
          disabled={pending}
          onClick={() =>
            void perform(async () => {
              const result = await request<SocialSettings>("settings");
              if (mounted.current) setSettings(result);
            })
          }
        >
          Volver a consultar
        </button>
      ) : null}
      {settings ? (
        <>
          <details>
            <summary>Conexión avanzada con API key (alternativa)</summary>
          <section
            className="crm-panel social-setup"
            aria-labelledby="social-setup-heading"
          >
            <div className="social-section-heading">
              <div>
                <h2 id="social-setup-heading">Perfil y conexión REST</h2>
                <p>
                  {settings.configured
                    ? "Credencial guardada en el servidor. Nunca se devuelve al navegador."
                    : "Necesitas una API key dedicada, con permisos limitados, y el perfil de la marca en Zernio."}
                </p>
              </div>
              <span
                className={`social-status ${settings.configured ? "social-status-good" : ""}`}
              >
                {settings.configured ? "Configurado" : "Sin configurar"}
              </span>
            </div>
            {settings.configured && !replacing ? (
              <div className="social-configured">
                <div>
                  <strong>{settings.profile?.name ?? "Perfil de marca"}</strong>
                  <span>ID: {settings.profile?.id ?? "No disponible"}</span>
                  <span>
                    Última sincronización: {dateLabel(settings.last_sync)} ·
                    hora de Colombia
                  </span>
                </div>
                <button
                  className="crm-button crm-secondary"
                  disabled={pending}
                  onClick={() => setReplacing(true)}
                >
                  Reemplazar credencial
                </button>
              </div>
            ) : (
              <form onSubmit={saveSettings} className="social-config-form">
                <div className="social-form-fields">
                  <label htmlFor="social-api-key">
                    API key de Zernio
                    <input
                      ref={keyInput}
                      id="social-api-key"
                      name="api_key"
                      type="password"
                      required
                      autoComplete="off"
                      spellCheck={false}
                      disabled={pending}
                      aria-describedby="social-key-hint"
                    />
                  </label>
                  <label htmlFor="social-profile-id">
                    ID del perfil de marca
                    <input
                      id="social-profile-id"
                      name="profile_id"
                      required
                      pattern="[a-fA-F0-9]{24}"
                      maxLength={24}
                      minLength={24}
                      defaultValue={settings.profile?.id ?? ""}
                      autoComplete="off"
                      spellCheck={false}
                      disabled={pending}
                      aria-describedby="social-profile-hint"
                    />
                  </label>
                </div>
                <p id="social-key-hint" className="social-help">
                  Usa una credencial exclusiva para este CRM, no una llave
                  general de tu cuenta. Solo se envía al pulsar Verificar y
                  guardar.
                </p>
                <p id="social-profile-hint" className="social-help">
                  El ID del perfil tiene 24 caracteres hexadecimales. No es el
                  nombre ni el ID de una red social.
                </p>
                {replacing ? (
                  <label className="social-check">
                    <input type="checkbox" required disabled={pending} />
                    Confirmo que quiero reemplazar la credencial y verificar de
                    nuevo el perfil de la marca.
                  </label>
                ) : null}
                <div className="social-actions">
                  <button className="crm-button" disabled={pending}>
                    Verificar y guardar
                  </button>
                  {replacing ? (
                    <button
                      type="button"
                      className="crm-button crm-secondary"
                      disabled={pending}
                      onClick={() => {
                        if (keyInput.current) keyInput.current.value = "";
                        setReplacing(false);
                      }}
                    >
                      Cancelar reemplazo
                    </button>
                  ) : null}
                </div>
              </form>
            )}
          </section>
          </details>
          {settings.sync_warning ? (
            <p className="social-warning" role="status">
              La última consulta no pudo verificar todos los canales. Actualiza
              las conexiones antes de confiar en su estado.
            </p>
          ) : null}
          {intent ? (
            <section
              className="social-authorization"
              aria-labelledby="social-authorization-heading"
            >
              <div className="social-section-heading">
                <h2 id="social-authorization-heading">
                  Autorizar {intentPlatform}
                </h2>
                <span className="social-status">
                  {expired ? "Vencido" : statusLabel(intentStatus)}
                </span>
              </div>
              <p>
                La autorización externa no confirma la conexión. Al regresar,
                comprobaremos el resultado con Zernio.
              </p>
              {intent.expires_at ? (
                <p className="social-help">
                  Vence: {dateLabel(intent.expires_at)} · hora de Colombia
                </p>
              ) : (
                <p className="social-help">
                  Se recuperó una autorización pendiente. Comprueba su estado o
                  inicia una nueva conexión si venció.
                </p>
              )}
              {intent.instructions ? (
                <p className="social-instructions">{intent.instructions}</p>
              ) : null}
              {intent.code && !expired ? (
                <p className="social-code">
                  Código temporal: <code>{intent.code}</code>
                </p>
              ) : null}
              <div className="social-actions">
                {safeUrl && !expired ? (
                  <a
                    className="crm-button"
                    href={safeUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Abrir autorización de {intentPlatform}
                    <Icon name="arrow" size={16} />
                    <span className="crm-sr-only"> en una pestaña nueva</span>
                  </a>
                ) : null}
                <button
                  className="crm-button crm-secondary"
                  disabled={pending || expired}
                  onClick={() => void perform(() => complete(intent.intent_id))}
                >
                  Comprobar conexión
                </button>
                <button
                  className="crm-inline-link"
                  disabled={pending}
                  onClick={cancelIntent}
                >
                  Cerrar autorización
                </button>
              </div>
            </section>
          ) : null}
          <section
            className="crm-panel social-channels"
            aria-labelledby="social-channels-heading"
          >
            <div className="social-section-heading">
              <div>
                <h2 id="social-channels-heading">Tus canales</h2>
                <p>
                  El estado corresponde a la última verificación, no a una
                  promesa de disponibilidad.
                </p>
              </div>
            </div>
            <ul>
              {socialPlatforms.map(([platform, name, mark, description]) => {
                const connections = settings.connections.filter(
                  (connection) => connection.platform === platform,
                );
                return (
                  <li className="social-channel" key={platform}>
                    <span className="social-channel-mark" aria-hidden="true">
                      {mark}
                    </span>
                    <div className="social-channel-info">
                      <h3>{name}</h3>
                      <p>{description}</p>
                      {connections.length ? (
                        <ul className="social-account-list">
                          {connections.map((connection) => (
                            <li key={connection.id}>
                              <span>
                                {connection.display_name ||
                                  connection.username ||
                                  "Cuenta sin nombre disponible"}
                              </span>
                              <span
                                className={`social-status ${connection.status === "connected" || connection.status === "active" ? "social-status-good" : ""}`}
                              >
                                {statusLabel(connection.status)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="social-status">
                          Sin conexión registrada
                        </span>
                      )}
                    </div>
                    <button
                      className="crm-button crm-secondary"
                      disabled={pending || !settings.configured}
                      onClick={() => void connect(platform)}
                      aria-label={`${connections.length ? "Volver a conectar" : "Conectar"} ${name}`}
                    >
                      {connections.length ? "Volver a conectar" : "Conectar"}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="social-channel-notes">
              <p>
                <strong>Telegram.</strong> La vinculación requiere un código
                temporal; solo se confirma después de verificarla.
              </p>
              <p>
                <strong>TikTok.</strong> Las capacidades dependen de los
                permisos y la aprobación de la plataforma.
              </p>
            </div>
          </section>
          <section
            className="crm-panel social-events"
            aria-labelledby="social-events-heading"
          >
            <div className="social-section-heading">
              <div>
                <h2 id="social-events-heading">Eventos recibidos</h2>
                <p>
                  {settings.webhook.configured
                    ? "Recepción de webhooks configurada. Verifica eventos reales para confirmar su funcionamiento."
                    : "La recepción de webhooks aún no está configurada en el servidor."}
                </p>
              </div>
              <span className="social-status">
                {settings.webhook.configured ? "Configurado" : "Pendiente"}
              </span>
            </div>
            {settings.events.length ? (
              <ul className="social-event-list">
                {settings.events.map((event) => (
                  <li key={event.id}>
                    <div>
                      <strong>{event.event}</strong>
                      <span>
                        {socialPlatforms.find(
                          ([key]) => key === event.platform,
                        )?.[1] ?? "Canal no identificado"}{" "}
                        · {statusLabel(event.status)}
                      </span>
                    </div>
                    <time dateTime={event.received_at}>
                      {dateLabel(event.received_at)}
                    </time>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="social-empty">
                <Icon name="message" size={22} />
                <h3>Aún no se han recibido eventos.</h3>
                <p>
                  Los eventos recibidos aparecerán aquí como un resumen. No se
                  importan conversaciones ni se crean clientes automáticamente.
                </p>
              </div>
            )}
          </section>
          <section
            className="social-readiness"
            aria-labelledby="social-readiness-heading"
          >
            <div>
              <h2 id="social-readiness-heading">Una base para lo que sigue</h2>
              <p>Hermes: manual, sin acceso a canales.</p>
            </div>
            <ul>
              {["Bandeja", "Contenido", "Ads", "Automatizaciones"].map(
                (module) => (
                  <li key={module}>
                    <span>{module}</span>
                    <span className="social-status">Pendiente</span>
                  </li>
                ),
              )}
            </ul>
            <p className="social-help">
              Conectar una cuenta no activa publicaciones, campañas, respuestas
              automáticas ni acciones de Hermes.
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}
