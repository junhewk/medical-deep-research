"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { type Locale, defaultLocale, locales } from "./config";

interface LocaleContextType {
  locale: Locale;
  setLocale: (locale: Locale) => Promise<void>;
  messages: Record<string, unknown>;
  t: (key: string, params?: Record<string, string>) => string;
  isLoading: boolean;
}

const LocaleContext = createContext<LocaleContextType | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(defaultLocale);
  const [messages, setMessages] = useState<Record<string, unknown>>({});
  const [isLoading, setIsLoading] = useState(true);

  // Load messages for current locale
  const loadMessages = useCallback(async (loc: Locale) => {
    try {
      const msgs = await import(`../../messages/${loc}.json`);
      setMessages(msgs.default || msgs);
    } catch (error) {
      console.error(`Failed to load messages for locale ${loc}:`, error);
      // Fallback to English
      if (loc !== "en") {
        const msgs = await import(`../../messages/en.json`);
        setMessages(msgs.default || msgs);
      }
    }
  }, []);

  // Fetch locale from server on mount
  useEffect(() => {
    const fetchLocale = async () => {
      try {
        const res = await fetch("/api/settings/language");
        if (res.ok) {
          const data = await res.json();
          if (data.language && locales.includes(data.language)) {
            setLocaleState(data.language);
            await loadMessages(data.language);
          } else {
            await loadMessages(defaultLocale);
          }
        } else {
          await loadMessages(defaultLocale);
        }
      } catch {
        await loadMessages(defaultLocale);
      } finally {
        setIsLoading(false);
      }
    };
    fetchLocale();
  }, [loadMessages]);

  // Set locale and save to server
  const setLocale = useCallback(async (newLocale: Locale) => {
    try {
      const res = await fetch("/api/settings/language", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: newLocale }),
      });

      if (res.ok) {
        setLocaleState(newLocale);
        await loadMessages(newLocale);
        // Update HTML lang attribute for proper CSS :lang() selectors
        document.documentElement.lang = newLocale;
      }
    } catch (error) {
      console.error("Failed to save locale:", error);
    }
  }, [loadMessages]);

  // Update HTML lang attribute when locale changes on initial load
  useEffect(() => {
    if (!isLoading) {
      document.documentElement.lang = locale;
    }
  }, [locale, isLoading]);

  // Translation function with nested key support (e.g., "settings.title")
  const t = useCallback((key: string, params?: Record<string, string>): string => {
    const keys = key.split(".");
    let value: unknown = messages;

    for (const k of keys) {
      if (value && typeof value === "object" && k in value) {
        value = (value as Record<string, unknown>)[k];
      } else {
        return key; // Return key if not found
      }
    }

    if (typeof value !== "string") {
      return key;
    }

    // Replace params like {name} with actual values
    if (params) {
      return Object.entries(params).reduce((str, [paramKey, paramValue]) => {
        return str.replace(new RegExp(`\\{${paramKey}\\}`, "g"), paramValue);
      }, value);
    }

    return value;
  }, [messages]);

  return (
    <LocaleContext.Provider value={{ locale, setLocale, messages, t, isLoading }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocale must be used within a LocaleProvider");
  }
  return context;
}

export function useTranslations(namespace?: string) {
  const { t: globalT, locale, isLoading } = useLocale();

  const t = useCallback((key: string, params?: Record<string, string>): string => {
    const fullKey = namespace ? `${namespace}.${key}` : key;
    return globalT(fullKey, params);
  }, [globalT, namespace]);

  return { t, locale, isLoading };
}
