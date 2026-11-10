import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jardines del Encanto",
  description: "Project workspace — Acacías, Meta, Colombia.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
