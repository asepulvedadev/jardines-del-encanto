import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { publicOrigin } from "../lib/public-seo";

const manrope = localFont({
  src: "./fonts/Manrope-Variable.ttf",
  weight: "200 800",
  display: "swap",
  variable: "--font-manrope",
});

export const metadata: Metadata = {
  metadataBase: new URL(publicOrigin),
  title: "Jardines del Encanto | Lotes en Acacías, Meta",
  description:
    "Tu espacio para echar raíces. Lotes de 7 × 14 m desde $13 millones COP en Acacías, Meta. Financiación hasta 24 meses. Conoce el proyecto y agenda tu visita.",
  robots: { index: false, follow: false },
  openGraph: {
    title: "Jardines del Encanto",
    description: "Lotes en Acacías, Meta. Un espacio para lo que viene.",
    locale: "es_CO",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es-CO" className={manrope.variable}>
      <body>{children}</body>
    </html>
  );
}
