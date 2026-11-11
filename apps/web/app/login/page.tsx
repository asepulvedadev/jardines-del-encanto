import { redirect } from "next/navigation";
import { crmSession } from "../../lib/crm-server";
import { LoginForm } from "../../components/crm/login-form";
import "../crm/crm.css";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Ingresar | Jardines del Encanto",
  robots: { index: false, follow: false },
};

export default async function LoginPage() {
  const session = await crmSession();
  if (session) redirect("/crm");
  return (
    <main className="crm-login">
      <section className="crm-login-brand" aria-label="Jardines del Encanto">
        <a href="/" className="crm-brand">
          Jardines<span>del Encanto.</span>
        </a>
        <div>
          <span className="crm-eyebrow">ESPACIO COMERCIAL</span>
          <h1>
            Cada conversación.
            <br />
            Un nuevo comienzo.
          </h1>
          <p>
            Un lugar tranquilo para organizar tus clientes y dar el siguiente
            paso.
          </p>
        </div>
        <span className="crm-login-location">
          Acacías, Meta · Gestión comercial
        </span>
      </section>
      <section className="crm-login-content">
        <LoginForm />
      </section>
    </main>
  );
}
