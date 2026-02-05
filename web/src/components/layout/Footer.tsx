"use client";

import { useTranslations } from "@/i18n/client";

export function Footer() {
  const { t } = useTranslations("footer");

  return (
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
                {t("title")}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("version")}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-6 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--status-completed))]" />
              {t("langGraphPowered")}
            </span>
            <span>{t("byokModel")}</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
