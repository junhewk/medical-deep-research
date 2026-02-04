import type { Metadata } from "next";
import { Source_Serif_4, Source_Sans_3 } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Navigation } from "@/components/layout/Navigation";

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-serif",
  display: "swap",
});

const sourceSans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Medical Deep Research",
  description: "Evidence-Based Medical Research Assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${sourceSerif.variable} ${sourceSans.variable} font-sans`}>
        <Providers>
          <div className="min-h-screen flex flex-col">
            <Navigation />
            <main className="flex-1 container py-6 md:py-8">
              {children}
            </main>
            <footer className="border-t border-border/50 py-4">
              <div className="container text-center text-sm text-muted-foreground">
                Medical Deep Research v2.0 — Evidence-based research assistant
              </div>
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
