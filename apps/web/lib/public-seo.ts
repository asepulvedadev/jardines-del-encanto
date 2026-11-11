import type { Metadata } from "next";
import { project } from "./project";

export const publicOrigin = "https://jardinesdelencanto.site";
export const buyerGuidePath = "/lotes-acacias-desde-bogota-soacha";
export const homeTitle =
  "Lotes en Acacías desde $13 millones | Jardines del Encanto";
export const homeDescription =
  "Conoce lotes de 7 × 14 m en Acacías, Meta, desde $13 millones COP. Información para compradores de Bogotá y Soacha, plano y visitas al proyecto.";
export const guideTitle =
  "Lotes en Acacías desde Bogotá y Soacha | Jardines del Encanto";
export const guideDescription =
  "¿Vives en Bogotá o Soacha? Revisa precios informados, plano, financiación y preguntas para preparar una visita a Jardines del Encanto en Acacías, Meta.";

export function publicMetadata(
  title: string,
  description: string,
  path: string,
): Metadata {
  const url = `${publicOrigin}${path}`;
  const image = {
    url: `${publicOrigin}/media/aerial-1920.webp`,
    width: 1920,
    height: 1080,
    alt: "Fotografía aérea real de Jardines del Encanto en Acacías, Meta",
  };
  return {
    title,
    description,
    alternates: { canonical: url },
    robots: {
      index: true,
      follow: true,
      googleBot: {
        index: true,
        follow: true,
        "max-image-preview": "large",
        "max-snippet": -1,
        "max-video-preview": -1,
      },
    },
    openGraph: {
      type: "website",
      locale: "es_CO",
      siteName: project.name,
      title,
      description,
      url,
      images: [image],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image.url],
    },
  };
}

// The physical project is in Acacías; buyer locations are not office addresses.
export function publicGraph(title: string, description: string, path: string) {
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${publicOrigin}/#organization`,
        name: project.name,
        url: `${publicOrigin}/`,
        telephone: project.phone,
      },
      {
        "@type": "WebSite",
        "@id": `${publicOrigin}/#website`,
        name: project.name,
        url: `${publicOrigin}/`,
        inLanguage: "es-CO",
        publisher: { "@id": `${publicOrigin}/#organization` },
      },
      {
        "@type": "Place",
        "@id": `${publicOrigin}/#project`,
        name: project.name,
        address: {
          "@type": "PostalAddress",
          addressLocality: "Acacías",
          addressRegion: "Meta",
          addressCountry: "CO",
        },
      },
      {
        "@type": "WebPage",
        "@id": `${publicOrigin}${path}#webpage`,
        url: `${publicOrigin}${path}`,
        name: title,
        description,
        inLanguage: "es-CO",
        isPartOf: { "@id": `${publicOrigin}/#website` },
        about: { "@id": `${publicOrigin}/#project` },
        publisher: { "@id": `${publicOrigin}/#organization` },
      },
    ],
  };
}

export function serializeGraph(value: ReturnType<typeof publicGraph>) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
