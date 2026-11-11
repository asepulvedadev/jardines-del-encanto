import { landingFont } from "../../lib/landing-font";
import { project } from "../../lib/project";
import {
  buyerGuidePath,
  guideDescription,
  guideTitle,
  publicGraph,
  publicMetadata,
  serializeGraph,
} from "../../lib/public-seo";
import "../landing.css";
import "../buyer-guide.css";

export const metadata = publicMetadata(
  guideTitle,
  guideDescription,
  buyerGuidePath,
);

export default function BuyerGuide() {
  return (
    <div className={`landing buyer-guide ${landingFont.variable}`}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: serializeGraph(
            publicGraph(guideTitle, guideDescription, buyerGuidePath),
          ),
        }}
      />
      <a href="#guia" className="skip-link">
        Saltar a la guía
      </a>
      <header className="site-header">
        <nav
          className="container header-inner"
          aria-label="Navegación de la guía"
        >
          <a className="wordmark" href="/">
            Jardines
            <br />
            del Encanto.
          </a>
          <a className="button button-outline" href="/#inicio">
            Ver el proyecto <span aria-hidden="true">↗</span>
          </a>
        </nav>
      </header>
      <main id="guia" className="container guide-main">
        <nav className="guide-breadcrumb" aria-label="Ruta de navegación">
          <a href="/">Inicio</a>
          <span aria-hidden="true">/</span>
          <span>Guía para compradores</span>
        </nav>
        <section className="guide-heading" aria-labelledby="guide-title">
          <p className="eyebrow">BOGOTÁ Y SOACHA · UNA MIRADA AL LLANO</p>
          <h1 id="guide-title">
            Lotes en Acacías para quienes viven en Bogotá y Soacha.
          </h1>
          <p className="guide-lead">
            Jardines del Encanto es un proyecto ubicado en{" "}
            <strong>Acacías, Meta</strong>. Si vives en Bogotá o Soacha, aquí
            puedes conocer su oferta informada, revisar el plano y preparar las
            preguntas para una visita. Los lotes no están ubicados en Bogotá ni
            en Soacha.
          </p>
          <p className="content-note">
            Información comercial suministrada por el proyecto. Confirma
            condiciones y disponibilidad con el asesor.
          </p>
        </section>
        <figure className="guide-photo">
          <picture>
            <source
              type="image/webp"
              srcSet="/media/aerial-960.webp 960w, /media/aerial-1920.webp 1920w"
              sizes="(max-width: 900px) 100vw, 1100px"
            />
            <img
              src="/media/aerial-1920.webp"
              alt="Fotografía aérea real de Jardines del Encanto en Acacías, Meta, con lotes, vías internas y portería."
              width={1920}
              height={1080}
              fetchPriority="high"
            />
          </picture>
          <figcaption>
            Una fotografía del proyecto, no una certificación del estado actual
            de entrega.
          </figcaption>
        </figure>
        <section className="guide-section" aria-labelledby="guide-facts">
          <h2 id="guide-facts">La propuesta, sin confundir la ubicación.</h2>
          <dl className="guide-facts">
            <div>
              <dt>Ubicación del proyecto</dt>
              <dd>Acacías, Meta, Colombia</dd>
            </div>
            <div>
              <dt>Precio informado</dt>
              <dd>Desde $13.000.000 COP</dd>
            </div>
            <div>
              <dt>Opción de lote</dt>
              <dd>7 × 14 m · 98 m²</dd>
            </div>
            <div>
              <dt>Financiación informada</dt>
              <dd>Hasta 24 meses</dd>
            </div>
          </dl>
          <p>
            No publicamos una cuota inicial, tasa de interés ni cuota mensual
            porque esas condiciones deben confirmarse con el equipo comercial.
            El plano es una referencia de distribución y medidas, no un
            inventario de disponibilidad.
          </p>
          <a className="text-link" href="/#plano">
            Revisar el plano y sus medidas <span aria-hidden="true">↗</span>
          </a>
        </section>
        <section className="guide-section" aria-labelledby="guide-steps">
          <h2 id="guide-steps">
            Cómo preparar tu visita desde Bogotá o Soacha.
          </h2>
          <ol className="guide-steps">
            <li>
              <h3>Primero, conoce qué estás comparando.</h3>
              <p>
                Revisa el plano, las fotografías reales y el recorrido
                arquitectónico. Las imágenes del recorrido son ilustrativas: no
                representan el estado actual de obra.
              </p>
            </li>
            <li>
              <h3>Pide la ubicación antes de organizar el viaje.</h3>
              <p>
                Solicita al asesor el punto exacto, las indicaciones de llegada
                y la coordinación de la visita. No damos un tiempo fijo de
                viaje: revisa tu ruta y las condiciones de tránsito para el día
                elegido.
              </p>
            </li>
            <li>
              <h3>Confirma el lote y sus condiciones.</h3>
              <p>
                Pregunta por identificación, medidas, disponibilidad, precio
                total, pagos y financiación. Solicita por escrito los costos y
                condiciones aplicables a tu caso, sin suponer que una cifra
                publicada cubre todos los conceptos.
              </p>
            </li>
            <li>
              <h3>Contrasta la información antes de comprometerte.</h3>
              <p>
                Consulta la documentación aplicable al lote y revísala con un
                profesional independiente. Durante la visita confirma el avance,
                las condiciones de entrega de servicios y zonas comunes, y su
                correspondencia con la información comercial.
              </p>
            </li>
          </ol>
        </section>
        <section className="guide-section" aria-labelledby="guide-questions">
          <h2 id="guide-questions">Respuestas para empezar con claridad.</h2>
          <div className="guide-answers">
            <div>
              <h3>¿Puedo iniciar la consulta si vivo en Bogotá o Soacha?</h3>
              <p>
                Sí. Puedes revisar la información pública, consultar el plano,
                registrar tu interés y coordinar una visita a Acacías con el
                asesor. Esto no equivale a comprar ni a reservar un lote en
                línea.
              </p>
            </div>
            <div>
              <h3>¿El cupo asegura un lote o congela el precio?</h3>
              <p>
                No. El código de cupo identifica tu registro de interés: no es
                una reserva, no implica un pago y no confirma disponibilidad ni
                congela un precio.
              </p>
            </div>
            <div>
              <h3>¿Las zonas comunes ya están terminadas?</h3>
              <p>
                Las zonas comunes corresponden a información del proyecto.
                Consulta el avance y las condiciones de entrega de cada espacio;
                ni el render ni una fotografía sustituyen esa confirmación.
              </p>
            </div>
            <div>
              <h3>¿Hay oficinas o lotes del proyecto en Bogotá o Soacha?</h3>
              <p>
                Esta página no anuncia oficinas ni lotes de Jardines del Encanto
                en esas ciudades. La ubicación informada del proyecto es
                Acacías, Meta.
              </p>
            </div>
          </div>
        </section>
        <section className="guide-action" aria-labelledby="guide-action-title">
          <h2 id="guide-action-title">
            El siguiente paso es conocer el lugar.
          </h2>
          <p>
            Vuelve al proyecto para explorar la maqueta, elegir una referencia
            en el plano y abrir el formulario de interés. Sin pagos ni reservas
            automáticas.
          </p>
          <a className="button button-primary" href="/#inicio">
            Conocer los lotes y registrar mi interés{" "}
            <span aria-hidden="true">↗</span>
          </a>
        </section>
      </main>
      <footer className="site-footer">
        <div className="container guide-footer">
          <a href="/">Jardines del Encanto</a>
          <span>Acacías, Meta, Colombia</span>
          <a href={`tel:+${project.whatsapp}`}>{project.phone}</a>
        </div>
      </footer>
    </div>
  );
}
