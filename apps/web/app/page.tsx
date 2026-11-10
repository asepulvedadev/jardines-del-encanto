import Image from "next/image";
import {
  ArchitecturalFilm,
  MobileNavigation,
  PhotoGallery,
} from "../components/landing-interactions";
import { ProjectPhoto } from "../components/project-photo";
import {
  amenityGroups,
  project,
  questions,
  whatsappLink,
} from "../lib/project";

function ContactLink({
  children = "Agendar una visita",
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
    <>
      <a href="#contenido" className="skip-link">
        Saltar al contenido
      </a>
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
          <ContactLink className="header-contact">Hablemos</ContactLink>
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
            <p className="eyebrow">ACACÍAS, META · VENTA DE LOTES</p>
            <h1 id="hero-title">
              Un lugar para
              <br />
              echar <span>raíces.</span>
            </h1>
            <p className="hero-description">
              Dale espacio a lo que viene. Tu lote en Jardines del Encanto, con
              naturaleza, zonas para compartir y una nueva historia por empezar.
            </p>
            <div className="hero-offer">
              <span>Lotes desde</span>
              <strong>
                $13 millones<span> COP</span>
              </strong>
            </div>
            <div className="hero-actions">
              <ContactLink />
              <a href="#proyecto" className="text-link">
                Conoce el proyecto <span aria-hidden="true">↓</span>
              </a>
            </div>
            <p className="hero-footnote">
              7 × 14 m · Financiación hasta 24 meses
            </p>
          </div>
          <figure className="hero-visual">
            <ProjectPhoto
              name="aerial"
              eager
              className="hero-image"
              sizes="(max-width: 767px) 100vw, (max-width: 1279px) 58vw, 740px"
              alt="Fotografía aérea real de Jardines del Encanto: lotes verdes, vías internas, portería y cancha multifuncional."
            />
            <figcaption>
              <span>El lugar donde todo comienza.</span>
              <span>Fotografía real del proyecto</span>
            </figcaption>
          </figure>
        </section>
        <section
          className="facts-section"
          aria-label="Información principal de los lotes"
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
        >
          <div className="section-heading">
            <p className="eyebrow">JARDINES DEL ENCANTO</p>
            <h2 id="overview-title">
              Tu próximo capítulo,
              <br />
              con más espacio.
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
            <ContactLink className="text-link">
              Quiero conocerlo en persona
            </ContactLink>
          </div>
        </section>
        <section
          id="espacios"
          className="amenities-section"
          aria-labelledby="amenities-title"
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
          </div>
        </section>
        <section className="film-section" aria-labelledby="film-section-title">
          <div className="container film-grid">
            <div className="film-copy">
              <p className="eyebrow">UNA MIRADA A LO QUE VIENE</p>
              <h2 id="film-section-title">
                Imagínalo.
                <br />
                Luego, ven a conocerlo.
              </h2>
              <p>
                Explora la propuesta de los espacios en este recorrido
                arquitectónico.
              </p>
              <p className="film-label">Visualización arquitectónica</p>
              <p className="film-note">
                Video ilustrativo. No representa el estado actual de obra.
              </p>
            </div>
            <ArchitecturalFilm />
          </div>
        </section>
        <section
          id="plano"
          className="section container plan-section"
          aria-labelledby="plan-title"
        >
          <div className="plan-copy">
            <p className="eyebrow">CONOCE LA DISTRIBUCIÓN</p>
            <h2 id="plan-title">
              Encuentra tu lugar
              <br />
              en el proyecto.
            </h2>
            <p>
              Revisa el plano general, ubica sus vías y espacios comunes, y
              conversa con un asesor sobre el lote que te interesa.
            </p>
            <a
              className="button button-outline"
              href="/media/plano-jardines-del-encanto.pdf"
              target="_blank"
              rel="noopener noreferrer"
            >
              Abrir plano completo <span aria-hidden="true">↗</span>
              <span className="sr-only"> (PDF en otra pestaña)</span>
            </a>
            <a
              className="download-link"
              href="/media/plano-jardines-del-encanto.pdf"
              download
            >
              Descargar plano PDF · 3,7 MB
            </a>
            <p className="content-note">
              Plano de referencia: no refleja disponibilidad en tiempo real. Las
              medidas y condiciones del lote se confirman con el equipo
              comercial.
            </p>
          </div>
          <a
            className="plan-preview"
            href="/media/plano-jardines-del-encanto.pdf"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Abrir el plano general en PDF, en otra pestaña"
          >
            <Image
              src="/media/masterplan.webp"
              unoptimized
              width={1500}
              height={1059}
              alt="Vista del plano general del proyecto, con sus manzanas, vías y zonas comunes. Abre el PDF para ver los detalles."
            />
            <span>
              Una vista general de tu próximo comienzo{" "}
              <span aria-hidden="true">↗</span>
            </span>
          </a>
        </section>
        <section
          className="location-section container"
          aria-labelledby="location-title"
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
            className="button button-outline"
            message="Hola, quiero la ubicación exacta de Jardines del Encanto en Acacías y las indicaciones para visitarlo."
          >
            Pedir ubicación
          </ContactLink>
        </section>
        <section
          id="preguntas"
          className="section container faq-section"
          aria-labelledby="faq-title"
        >
          <div className="faq-heading">
            <h2 id="faq-title">
              Antes de dar
              <br />
              el primer paso.
            </h2>
            <p>Respuestas claras para empezar a conversar.</p>
            <ContactLink
              className="text-link"
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
        >
          <div className="container contact-inner">
            <p className="eyebrow">TU HISTORIA PUEDE EMPEZAR AQUÍ</p>
            <h2 id="contact-title">
              Lo mejor es
              <br />
              venir a conocerlo.
            </h2>
            <p>
              Hablemos de tu lote, la financiación y tu próxima visita a
              Jardines del Encanto.
            </p>
            <ContactLink className="button button-light">
              Hablemos por WhatsApp
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
                Puedes explorar esta página sin registrar tus datos. No hay
                formularios de captación ni herramientas de analítica en esta
                versión. Si eliges escribirnos, abrirás WhatsApp, un servicio
                externo con sus propias políticas de privacidad.
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
    </>
  );
}
