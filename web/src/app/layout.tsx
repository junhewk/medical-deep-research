import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Navigation } from "@/components/layout/Navigation";

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
              <footer className="relative border-t border-border/40 bg-background/60 backdrop-blur-sm">
                <div className="container py-6">
                  <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                        <svg
                          className="w-4 h-4 text-primary"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                        >
                          <circle cx="12" cy="12" r="10" />
                          <path d="M12 6v6l4 2" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          Medical Deep Research
                        </p>
                        <p className="text-xs text-muted-foreground">
                          v2.0 — Evidence-based research assistant
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-6 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--status-completed))]" />
                        LangGraph Powered
                      </span>
                      <span>BYOK Model</span>
                    </div>
                  </div>
                </div>
              </footer>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
