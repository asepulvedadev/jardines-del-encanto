"use client";
import "./crm.css";
export default function CrmError({ reset }: { reset: () => void }) {
  return (
    <main className="crm-service-error">
      <h1>No podemos abrir el CRM ahora.</h1>
      <p>El servicio no está disponible. Tus datos no se han modificado.</p>
      <button className="crm-button" onClick={reset}>
        Volver a intentar
      </button>
      <a href="/login">Ir al acceso</a>
    </main>
  );
}
