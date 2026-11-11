"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "./icon";
import { errorMessage } from "./types";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [visible, setVisible] = useState(false);
  const busy = useRef(false);
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/crm/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(errorMessage(body.detail));
      router.replace("/crm");
      router.refresh();
    } catch (error) {
      setError(
        error instanceof Error && !(error instanceof TypeError)
          ? error.message
          : "No pudimos conectar. Intenta de nuevo.",
      );
    } finally {
      setPending(false);
      busy.current = false;
    }
  }
  return (
    <div className="crm-login-form">
      <span className="crm-eyebrow">ACCESO PRIVADO</span>
      <h2>Bienvenido de nuevo.</h2>
      <p>Ingresa para continuar con tu gestión comercial.</p>
      <form onSubmit={submit}>
        <label htmlFor="username">Usuario</label>
        <input
          id="username"
          name="username"
          autoComplete="username"
          required
          maxLength={80}
          autoCapitalize="none"
          spellCheck={false}
          placeholder="Tu usuario"
          disabled={pending}
        />
        <label htmlFor="password">Contraseña</label>
        <div className="crm-password">
          <input
            id="password"
            name="password"
            type={visible ? "text" : "password"}
            autoComplete="current-password"
            required
            maxLength={256}
            disabled={pending}
          />
          <button
            type="button"
            aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
            aria-pressed={visible}
            onClick={() => setVisible(!visible)}
          >
            <Icon name="eye" />
          </button>
        </div>
        {error && (
          <p className="crm-error" role="alert">
            {error}
          </p>
        )}
        <button
          className="crm-button crm-login-submit"
          type="submit"
          disabled={pending}
        >
          Ingresar <Icon name="chevron" />
        </button>
        <span className="crm-form-status" role="status">
          {pending ? "Validando acceso…" : ""}
        </span>
      </form>
      <p className="crm-login-help">
        Acceso exclusivo para el equipo de Jardines del Encanto.
      </p>
    </div>
  );
}
