import localFont from "next/font/local";
import {
  MobileNavigation,
  PhotoGallery,
} from "../components/landing-interactions";
import {
  HeroFilm,
  LandingMotion,
  LaunchBanner,
} from "../components/landing-experience";
import { MasterplanExplorer } from "../components/masterplan-explorer";
import { LeadCapture } from "../components/lead-capture";
import {
  amenityGroups,
  project,
  questions,
  whatsappLink,
} from "../lib/project";
import "./landing.css";

const jakarta = localFont({
  src: "./fonts/PlusJakartaSans-Variable.ttf",
  weight: "200 800",
  display: "swap",
  variable: "--font-landing",
});

function ContactLink({
  children = "Quiero mi cupo",
  className = "button button-primary",
  message,
}: {
  children?: React.ReactNode;
  className?: string;
  message?: string;
}) {
  return (
    <a
      href={whatsappLink(message)}
      className={className}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <span className="button-arrow" aria-hidden="true">
        ↗
      </span>
      <span className="sr-only"> (abre WhatsApp en otra pestaña)</span>
    </a>
  );
}

export default function Home() {
  return (
    <div id="jardines-landing" className={`landing ${jakarta.variable}`}>
      <LandingMotion />
      <a href="#contenido" className="skip-link">
        Saltar al contenido
      </a>
      <LaunchBanner />
      <header className="site-header">
        <div className="container header-inner">
          <a
            href="#inicio"
            className="wordmark"
            aria-label="Jardines del Encanto, inicio"
          >
            <span>Jardines</span>
            <span>
              del Encanto<span className="wordmark-period">.</span>
            </span>
          </a>
          <nav className="desktop-nav" aria-label="Navegación principal">
            <a href="#proyecto">El proyecto</a>
            <a href="#espacios">Espacios</a>
            <a href="#plano">Plano</a>
            <a href="#preguntas">Preguntas</a>
          </nav>
          <ContactLink className="button button-primary header-contact">
            Agendar visita
          </ContactLink>
          <MobileNavigation />
        </div>
      </header>
      <main id="contenido">
        <section
          className="hero container"
          id="inicio"
          aria-labelledby="hero-title"
        >
          <div className="hero-copy">
            <h1 id="hero-title">
              Más tierra.
              <br />
              Más vida.
              <br />
              <span>Tu comienzo.</span>
            </h1>
            <p className="hero-description">
              Tu próximo proyecto tiene lugar en el Llano. Conoce Jardines del
              Encanto: naturaleza, espacios para compartir y un lote para lo que
              viene.
            </p>
            <div className="hero-offer">
              <span>PRECIO DE LANZAMIENTO · LOTES DESDE</span>
              <strong>
                $13 millones<span> COP</span>
              </strong>
            </div>
            <div className="hero-actions">
              <ContactLink />
              <a href="#plano" className="button button-outline">
                Explorar el plano <span aria-hidden="true">↓</span>
              </a>
            </div>
            <p className="hero-footnote">
              Opción de 7 × 14 m · 98 m² · Financiación hasta 24 meses
            </p>
            <p className="hero-contact-note">
              Habla con un asesor. Sin pagos ni reservas automáticas.
            </p>
          </div>
          <HeroFilm />
        </section>
        <section
          className="facts-section"
          aria-label="Información principal de los lotes"
          data-reveal
        >
          <dl className="container facts-grid">
            <div>
              <dt>ESPACIO PARA TU PROYECTO</dt>
              <dd>
                98 <span>m²</span>
                <p>Lotes de 7 × 14 metros</p>
              </dd>
            </div>
            <div>
              <dt>UNA FORMA DE EMPEZAR</dt>
              <dd>
                24 <span>meses</span>
                <p>Plazo máximo de financiación</p>
              </dd>
            </div>
            <div>
              <dt>CONEXIÓN Y ACCESO</dt>
              <dd>
                Agua <span>y</span> luz
                <p>Servicios contemplados en el proyecto</p>
              </dd>
            </div>
          </dl>
        </section>
        <section
          id="proyecto"
          className="section container overview"
          aria-labelledby="overview-title"
          data-reveal
        >
          <div className="section-heading">
            <p className="eyebrow">JARDINES DEL ENCANTO</p>
            <h2 id="overview-title">
              No lo imagines solamente.
              <br />
              Mira el lugar.
            </h2>
            <p>
              No se trata solo de elegir un lote. Se trata de conocer el lugar
              donde quieres construir tu proyecto de vida. Recorre sus vías,
              mira el entorno y descubre sus espacios.
            </p>
          </div>
          <PhotoGallery />
          <div className="gallery-note">
            <p>Conoce el proyecto a través de sus fotografías reales.</p>
            <ContactLink className="button button-primary">
              Quiero conocerlo en persona
            </ContactLink>
          </div>
        </section>
        <section
          id="espacios"
          className="amenities-section"
          aria-labelledby="amenities-title"
          data-reveal
        >
          <div className="container">
            <div className="section-heading">
              <h2 id="amenities-title">
                El espacio es tuyo.
                <br />
                Los buenos momentos, de todos.
              </h2>
              <p>
                Zonas del proyecto para compartir, moverte o simplemente hacer
                una pausa.
              </p>
            </div>
            <div className="amenity-groups">
              {amenityGroups.map((group, index) => (
                <article className="amenity-group" key={group.title}>
                  <span className="group-number" aria-hidden="true">
                    0{index + 1}
                  </span>
                  <h3>{group.title}</h3>
                  <p>{group.text}</p>
                  <ul>
                    {group.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
            <div className="arrival-strip">
              <strong>Bienvenido desde el primer momento.</strong>
              <p>Portería de lujo y oficina de administración.</p>
            </div>
            <p className="content-note">
              Espacios informados por el proyecto. Consulta durante tu visita el
              estado de avance y las condiciones de entrega de cada zona.
            </p>
            <LeadCapture />
          </div>
        </section>
        <section
          id="plano"
          className="section container plan-section"
          aria-labelledby="plan-title"
          data-reveal
        >
          <div className="plan-copy">
            <p className="eyebrow">CONOCE LA DISTRIBUCIÓN</p>
            <h2 id="plan-title">
              Encuentra tu lugar
              <br />
              en el proyecto.
            </h2>
            <p>
              Explora las manzanas, elige un lote y revisa sus medidas
              directamente en el plano. Luego, consulta sus condiciones con un
              asesor.
            </p>
            <p className="content-note">
              Plano de referencia: no refleja disponibilidad en tiempo real. Las
              medidas y condiciones del lote se confirman con el equipo
              comercial.
            </p>
          </div>
          <MasterplanExplorer />
        </section>
        <section
          className="location-section container"
          aria-labelledby="location-title"
          data-reveal
        >
          <div>
            <span className="location-tag">ACACÍAS · META</span>
            <h2 id="location-title">Nos vemos en el Llano.</h2>
            <p>
              El siguiente paso es conocerlo. Coordina tu visita y recibe la
              ubicación exacta e indicaciones de llegada por WhatsApp.
            </p>
          </div>
          <ContactLink
            className="button button-primary"
            message="Hola, quiero la ubicación exacta de Jardines del Encanto en Acacías y las indicaciones para visitarlo."
          >
            Pedir ubicación
          </ContactLink>
        </section>
        <section
          id="preguntas"
          className="section container faq-section"
          aria-labelledby="faq-title"
          data-reveal
        >
          <div className="faq-heading">
            <h2 id="faq-title">
              Antes de dar
              <br />
              el primer paso.
            </h2>
            <p>Respuestas claras para empezar a conversar.</p>
            <ContactLink
              className="button button-outline"
              message="Hola, tengo una pregunta sobre los lotes de Jardines del Encanto."
            >
              Tengo otra pregunta
            </ContactLink>
          </div>
          <div className="faq-list">
            {questions.map((item) => (
              <details key={item.question}>
                <summary>
                  {item.question}
                  <span aria-hidden="true">+</span>
                </summary>
                <p>{item.answer}</p>
              </details>
            ))}
          </div>
        </section>
        <section
          id="contacto"
          className="contact-section"
          aria-labelledby="contact-title"
          data-reveal
        >
          <div className="container contact-inner">
            <p className="eyebrow">TU HISTORIA PUEDE EMPEZAR AQUÍ</p>
            <h2 id="contact-title">
              Tu próximo comienzo.
              <br />
              Vamos a conocerlo.
            </h2>
            <p>
              Hablemos de tu lote, la financiación y tu próxima visita a
              Jardines del Encanto.
            </p>
            <ContactLink className="button button-lime contact-main-action">
              Quiero mi cupo
            </ContactLink>
            <a className="contact-phone" href={`tel:+${project.whatsapp}`}>
              {project.phone}
            </a>
            <p className="contact-note">
              Desde $13.000.000 COP · Lotes de 7 × 14 m · Hasta 24 meses de
              financiación
            </p>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <div className="container">
          <div className="footer-top">
            <a href="#inicio" className="footer-brand">
              Jardines del Encanto
            </a>
            <p>
              Un espacio para lo que viene.
              <br />
              Acacías, Meta, Colombia.
            </p>
            <a href="#inicio" className="text-link">
              Volver arriba ↑
            </a>
          </div>
          <div className="footer-bottom">
            <p>© {new Date().getFullYear()} Jardines del Encanto</p>
            <details className="privacy-note">
              <summary>Privacidad de esta página</summary>
              <p>
                Puedes explorar esta página sin registrar tus datos. Si envías
                el formulario de cupo, guardamos tu nombre, celular y
                autorización de contacto en el CRM del proyecto. El código
                identifica tu registro de interés, no una reserva. No usamos
                herramientas de analítica. Si eliges escribirnos, abrirás
                WhatsApp, un servicio externo con sus propias políticas de
                privacidad.
              </p>
            </details>
          </div>
          <p className="legal-note">
            Información comercial suministrada por el proyecto. Confirma
            precios, disponibilidad, documentación y condiciones de financiación
            con el asesor. Las fotografías y el plano no certifican el estado de
            entrega de las zonas comunes.
          </p>
        </div>
      </footer>
      <div className="mobile-contact-bar">
        <span>
          Tu lote desde<strong>$13 millones COP</strong>
        </span>
        <ContactLink className="button button-primary">
          Quiero mi cupo
        </ContactLink>
      </div>
    </div>
  );
}
