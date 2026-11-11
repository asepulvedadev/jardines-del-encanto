"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { whatsappLink } from "../lib/project";
import "../app/lead-capture.css";

const SEEN = "jardines-capture-seen-v1";
const RECEIPT = "jardines-capture-code-v1";
function remember(key: string, value: string) {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* The form works without browser storage. */
  }
}

const LeadCaptureContext = createContext<{
  show: () => void;
  registered: boolean;
} | null>(null);

export function LeadCaptureButton({
  className = "button button-primary",
  id,
}: {
  className?: string;
  id?: string;
}) {
  const capture = useContext(LeadCaptureContext);
  if (!capture) throw new Error("LeadCaptureButton requires LeadCaptureProvider");
  return (
    <button
      id={id}
      type="button"
      className={className}
      data-lead-capture-trigger
      aria-haspopup="dialog"
      aria-controls="lead-capture-dialog"
      onClick={capture.show}
    >
      {capture.registered ? "Ver mi cupo" : "Quiero mi cupo"}{" "}
      <span className="button-arrow" aria-hidden="true">
        ↗
      </span>
    </button>
  );
}

export function LeadCaptureProvider({ children }: { children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const attempted = useRef(false);
  const submitting = useRef(false);
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  function show() {
    attempted.current = true;
    previousFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    remember(SEEN, "1");
    setOpen(true);
  }

  useEffect(() => {
    let seen = false;
    try {
      seen = sessionStorage.getItem(SEEN) === "1";
      const receipt = sessionStorage.getItem(RECEIPT) || "";
      if (/^JDE-[A-F0-9]{12}$/.test(receipt)) setCode(receipt);
    } catch {
      /* Session storage is optional. */
    }
    const heading = document.getElementById("amenities-title");
    if (seen || !heading || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (
          !entry.isIntersecting ||
          attempted.current ||
          document.querySelector("dialog[open]")
        )
          return;
        attempted.current = true;
        show();
        observer.disconnect();
      },
      { threshold: 0.3, rootMargin: "-110px 0px -15% 0px" },
    );
    observer.observe(heading);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = dialog.current;
    if (!open || !element) return;
    element.showModal();
    const overflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = "hidden";
    return () => {
      element.close();
      document.documentElement.style.overflow = overflow;
    };
  }, [open]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    submitting.current = true;
    setPending(true);
    setError("");
    try {
      const response = await fetch("/api/landing/registrations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "omit",
        body: JSON.stringify({
          name: data.get("name"),
          phone: data.get("phone"),
          consent: data.get("consent") === "on",
          website: data.get("website") || "",
        }),
        signal: AbortSignal.timeout(12000),
      });
      if (!response.ok) {
        setError(
          response.status === 429
            ? "Recibimos varios intentos. Espera 10 minutos antes de volver a intentar."
            : response.status === 422
              ? "Revisa tu nombre, celular y autorización antes de continuar."
              : "No pudimos confirmar el registro. Conservamos tus datos en el formulario; puedes volver a intentar.",
        );
        return;
      }
      const result = await response.json();
      if (
        typeof result.code !== "string" ||
        !/^JDE-[A-F0-9]{12}$/.test(result.code)
      )
        throw new Error("Invalid receipt");
      remember(RECEIPT, result.code);
      setCode(result.code);
      form.reset();
    } catch {
      setError(
        "No pudimos confirmar el registro. Revisa tu conexión y vuelve a intentar; no se duplicará tu cupo.",
      );
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return (
    <LeadCaptureContext.Provider value={{ show, registered: Boolean(code) }}>
      {children}
      <dialog
        id="lead-capture-dialog"
        className="lead-capture"
        ref={dialog}
        aria-labelledby="lead-capture-title"
        aria-describedby="lead-capture-description"
        onCancel={(event) => {
          if (pending) event.preventDefault();
        }}
        onClose={() => {
          setOpen(false);
          const target = previousFocus.current;
          if (target && target !== document.body && target.isConnected)
            target.focus({ preventScroll: true });
          else
            document
              .getElementById("lead-capture-amenities")
              ?.focus({ preventScroll: true });
        }}
      >
        <button
          className="lead-capture-close"
          type="button"
          aria-label="Cerrar registro de cupo"
          disabled={pending}
          onClick={() => dialog.current?.close()}
        >
          ×
        </button>
        <p className="lead-capture-eyebrow">JARDINES DEL ENCANTO</p>
        <h2 id="lead-capture-title">
          {code
            ? "Tu cupo está registrado."
            : "Tu próximo comienzo, más cerca."}
        </h2>
        <p id="lead-capture-description">
          {code
            ? "Guarda tu código y compártelo con nuestro asesor."
            : "Déjanos tu nombre y celular para registrar tu interés y recibir tu código de cupo."}
        </p>
        {code ? (
          <div className="lead-capture-success" role="status">
            <span>Tu código de cupo</span>
            <strong className="lead-capture-code">{code}</strong>
            <p>
              Este código confirma tu registro de interés. No reserva un lote ni
              garantiza precio o disponibilidad.
            </p>
            <a
              className="button button-primary"
              href={whatsappLink(
                `Hola, registré mi interés en Jardines del Encanto. Mi código de cupo es ${code}. Quiero conocer el proyecto.`,
              )}
              target="_blank"
              rel="noopener noreferrer"
            >
              Hablar con un asesor ↗
              <span className="sr-only"> (abre WhatsApp en otra pestaña)</span>
            </a>
          </div>
        ) : (
          <form
            onSubmit={submit}
            className="lead-capture-form"
            aria-busy={pending}
          >
            <label htmlFor="lead-full-name">Nombre completo</label>
            <input
              id="lead-full-name"
              name="name"
              autoComplete="name"
              minLength={3}
              maxLength={120}
              required
              disabled={pending}
              autoFocus
            />
            <label htmlFor="lead-phone">Número de celular</label>
            <input
              id="lead-phone"
              name="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              placeholder="300 123 4567"
              minLength={7}
              maxLength={32}
              required
              disabled={pending}
              aria-describedby="lead-phone-hint"
            />
            <span id="lead-phone-hint" className="lead-capture-hint">
              Si estás fuera de Colombia, incluye el código de tu país.
            </span>
            <div className="lead-capture-trap" aria-hidden="true">
              <label>
                Deja este campo vacío
                <input name="website" tabIndex={-1} autoComplete="off" />
              </label>
            </div>
            <label className="lead-capture-consent">
              <input
                name="consent"
                type="checkbox"
                required
                disabled={pending}
              />
              <span>
                Autorizo a Jardines del Encanto a usar mi nombre y celular para
                contactarme sobre el proyecto. Mi registro se guardará en su
                CRM.
              </span>
            </label>
            {error && (
              <p className="lead-capture-error" role="alert">
                {error}
              </p>
            )}
            <button
              className="button button-primary"
              type="submit"
              disabled={pending}
            >
              Registrar mi cupo <span aria-hidden="true">↗</span>
            </button>
            <span className="lead-capture-hint" role="status">
              {pending
                ? "Registrando tu cupo…"
                : "Sin pagos ni reservas automáticas. Puedes cerrar y seguir explorando."}
            </span>
          </form>
        )}
      </dialog>
    </LeadCaptureContext.Provider>
  );
}
