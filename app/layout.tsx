import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SimlabimAI",
  description: "Coleta colaborativa de amostras vocais.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-neutral-50 text-neutral-900 antialiased">
        {children}
      </body>
    </html>
  );
}
