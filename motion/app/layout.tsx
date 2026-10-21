import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dúo Motion · Panel editorial",
  description: "Sistema audiovisual de Dúo Noticias: plantillas, previsualización y exportación.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
