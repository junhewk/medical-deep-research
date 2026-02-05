import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Navigation } from "@/components/layout/Navigation";
import { Footer } from "@/components/layout/Footer";

export const metadata: Metadata = {
  title: "Medical Deep Research",
  description: "Evidence-Based Medical Research Assistant",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background antialiased">
        <Providers>
          <div className="relative min-h-screen flex flex-col">
            {/* Subtle background pattern */}
            <div className="fixed inset-0 pattern-dots opacity-40 pointer-events-none" />
            <div className="fixed inset-0 mesh-gradient pointer-events-none" />

            {/* Main content */}
            <div className="relative z-10 flex flex-col min-h-screen">
              <Navigation />
              <main className="flex-1 container py-8 md:py-12">
                {children}
              </main>
              <Footer />
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
