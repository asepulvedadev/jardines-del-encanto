import type { Metadata } from "next";
import { project } from "./project";

export const publicOrigin = "https://jardinesdelencanto.site";
export const buyerGuidePath = "/lotes-acacias-desde-bogota-soacha";
export const homeTitle =
  "Lotes en Acacías, Meta desde $13 millones | Jardines del Encanto";
export const homeDescription =
  "Lotes de 7 × 14 m (98 m²) en Acacías, Meta, desde $13 millones COP. Financiación hasta 24 meses. Fotos reales, plano y visitas desde Bogotá y Soacha.";
export const guideTitle =
  "Lotes en Acacías desde Bogotá y Soacha | Jardines del Encanto";
export const guideDescription =
  "¿Vives en Bogotá o Soacha? Revisa precios informados, plano, financiación y preguntas para preparar una visita a Jardines del Encanto en Acacías, Meta.";

export const socialImage = {
  url: `${publicOrigin}/media/jardines-del-encanto-social-20261116.png`,
  width: 1200,
  height: 630,
  type: "image/png",
  alt: "Jardines del Encanto en Acacías, Meta: foto real de la portería, lotes desde $13 millones COP, 7 × 14 m y financiación hasta 24 meses.",
};

// Keep icons under the already-public media path; private routes stay noindex.
export const brandIcons: Metadata["icons"] = {
  icon: [
    { url: "/media/brand/favicon.ico", type: "image/x-icon", sizes: "32x32 48x48 96x96" },
    { url: "/media/brand/icon-96.png", type: "image/png", sizes: "96x96" },
    { url: "/media/brand/icon-192.png", type: "image/png", sizes: "192x192" },
  ],
  apple: [{ url: "/media/brand/apple-touch-icon.png", type: "image/png", sizes: "180x180" }],
};

export function publicMetadata(
  title: string,
  description: string,
  path: string,
): Metadata {
  const url = `${publicOrigin}${path}`;
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
      images: [{ ...socialImage, secureUrl: socialImage.url }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [{ url: socialImage.url, alt: socialImage.alt }],
    },
  };
}

// The physical project is in Acacías; buyer locations are not office addresses.
export function publicGraph(title: string, description: string, path: string) {
  const url = `${publicOrigin}${path}`;
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${publicOrigin}/#organization`,
        name: project.name,
        url: `${publicOrigin}/`,
        telephone: project.phone,
        logo: {
          "@type": "ImageObject",
          url: `${publicOrigin}/media/brand/logo-512.png`,
          contentUrl: `${publicOrigin}/media/brand/logo-512.png`,
          width: 512,
          height: 512,
          caption: project.name,
        },
        contactPoint: {
          "@type": "ContactPoint",
          contactType: "sales",
          telephone: project.phone,
          availableLanguage: "es-CO",
          url: `https://wa.me/${project.whatsapp}`,
        },
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
        description: "Proyecto de venta de lotes en Acacías, Meta, Colombia.",
        address: {
          "@type": "PostalAddress",
          addressLocality: "Acacías",
          addressRegion: "Meta",
          addressCountry: "CO",
        },
        photo: {
          "@type": "ImageObject",
          contentUrl: `${publicOrigin}/media/porteria-actual-1280.webp`,
          width: 1280,
          height: 720,
          caption: "Fotografía real de la portería y su entorno en Jardines del Encanto.",
        },
      },
      {
        "@type": "ImageObject",
        "@id": `${publicOrigin}/#social-image`,
        url: socialImage.url,
        contentUrl: socialImage.url,
        width: socialImage.width,
        height: socialImage.height,
        caption: "Tarjeta informativa de Jardines del Encanto con fotografía real de la portería.",
        inLanguage: "es-CO",
      },
      ...(path === buyerGuidePath ? [{
        "@type": "BreadcrumbList",
        "@id": `${url}#breadcrumb`,
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Inicio", item: `${publicOrigin}/` },
          { "@type": "ListItem", position: 2, name: "Guía para compradores", item: url },
        ],
      }] : []),
      {
        "@type": "WebPage",
        "@id": `${url}#webpage`,
        url,
        name: title,
        description,
        inLanguage: "es-CO",
        isPartOf: { "@id": `${publicOrigin}/#website` },
        about: { "@id": `${publicOrigin}/#project` },
        publisher: { "@id": `${publicOrigin}/#organization` },
        primaryImageOfPage: { "@id": `${publicOrigin}/#social-image` },
        ...(path === buyerGuidePath ? { breadcrumb: { "@id": `${url}#breadcrumb` } } : {}),
      },
    ],
  };
}

export function serializeGraph(value: ReturnType<typeof publicGraph>) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
