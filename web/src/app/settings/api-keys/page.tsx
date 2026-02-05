"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Loader2,
  Check,
  Trash2,
  ExternalLink,
  Shield,
  Sparkles,
  Database,
  Brain,
  BookOpen,
  Settings2,
  Globe,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale, useTranslations } from "@/i18n/client";
import type { Locale } from "@/i18n/config";

interface ApiKey {
  id: string;
  service: string;
  apiKey: string;
  createdAt: string;
  updatedAt?: string;
}

type LlmProvider = "openai" | "anthropic" | "google";

interface LlmConfig {
  provider: LlmProvider;
  model: string;
  isDefault: boolean;
  availableModels: {
    openai: { id: string; name: string; description: string }[];
    anthropic: { id: string; name: string; description: string }[];
    google: { id: string; name: string; description: string }[];
  };
}

const API_SERVICES = [
  {
    id: "openai",
    nameKey: "apiServices.openai.name",
    descriptionKey: "apiServices.openai.description",
    required: false,
    docsUrl: "https://platform.openai.com/api-keys",
    icon: Sparkles,
    color: "text-emerald-600 dark:text-emerald-400",
  },
  {
    id: "anthropic",
    nameKey: "apiServices.anthropic.name",
    descriptionKey: "apiServices.anthropic.description",
    required: false,
    docsUrl: "https://console.anthropic.com/settings/keys",
    icon: Brain,
    color: "text-orange-600 dark:text-orange-400",
  },
  {
    id: "google",
    nameKey: "apiServices.google.name",
    descriptionKey: "apiServices.google.description",
    required: false,
    docsUrl: "https://aistudio.google.com/app/apikey",
    icon: Sparkles,
    color: "text-blue-600 dark:text-blue-400",
  },
  {
    id: "ncbi",
    nameKey: "apiServices.ncbi.name",
    descriptionKey: "apiServices.ncbi.description",
    required: false,
    docsUrl:
      "https://www.ncbi.nlm.nih.gov/account/settings/#accountSettingsApiKeyManagement",
    icon: Database,
    color: "text-blue-600 dark:text-blue-400",
  },
  {
    id: "scopus",
    nameKey: "apiServices.scopus.name",
    descriptionKey: "apiServices.scopus.description",
    required: false,
    docsUrl: "https://dev.elsevier.com/apikey/manage",
    icon: BookOpen,
    color: "text-amber-600 dark:text-amber-400",
  },
];

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3, 4].map((i) => (
        <Card key={i}>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-lg" />
                <div>
                  <Skeleton className="h-5 w-24 mb-1" />
                  <Skeleton className="h-4 w-48" />
                </div>
              </div>
              <Skeleton className="h-5 w-20" />
            </div>
          </CardHeader>
          <CardContent>
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

interface LanguageButtonProps {
  localeValue: Locale;
  currentLocale: Locale;
  label: string;
  displayText: string;
  onClick: (locale: Locale) => void;
  disabled: boolean;
  isLoading: boolean;
}

function LanguageButton({
  localeValue,
  currentLocale,
  label,
  displayText,
  onClick,
  disabled,
  isLoading,
}: LanguageButtonProps) {
  const isSelected = currentLocale === localeValue;

  return (
    <button
      onClick={() => onClick(localeValue)}
      disabled={disabled}
      className={cn(
        "group relative h-24 rounded-xl border-2 transition-all duration-300 overflow-hidden",
        isSelected
          ? "border-[hsl(275,45%,48%)] bg-gradient-to-br from-[hsl(275,45%,48%)]/15 via-[hsl(275,45%,48%)]/8 to-transparent shadow-lg shadow-[hsl(275,45%,48%)]/15"
          : "border-border/60 hover:border-[hsl(275,45%,48%)]/40 hover:bg-[hsl(275,45%,48%)]/5"
      )}
    >
      {isSelected && (
        <div className="absolute top-2 right-2">
          <div className="p-1 rounded-full bg-[hsl(275,45%,48%)]">
            <Check className="h-3 w-3 text-white" />
          </div>
        </div>
      )}
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <span className="text-3xl font-serif tracking-tight text-foreground group-hover:scale-105 transition-transform">
          {displayText}
        </span>
        <span className={cn(
          "text-sm font-medium transition-colors",
          isSelected ? "text-[hsl(275,45%,48%)]" : "text-muted-foreground group-hover:text-foreground"
        )}>
          {label}
        </span>
      </div>
      {isLoading && !isSelected && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/50">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(275,45%,48%)]" />
        </div>
      )}
    </button>
  );
}

export default function ApiKeysPage() {
  const { t } = useTranslations();
  const { locale, setLocale } = useLocale();

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [newKeys, setNewKeys] = useState<Record<string, string>>({});
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // LLM Config state
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<LlmProvider>("openai");
  const [selectedModel, setSelectedModel] = useState<string>("gpt-5.2");
  const [savingLlm, setSavingLlm] = useState(false);
  const [savingLanguage, setSavingLanguage] = useState(false);

  useEffect(() => {
    fetchKeys();
    fetchLlmConfig();
  }, []);

  const fetchKeys = async () => {
    try {
      const res = await fetch("/api/settings/api-keys");
      if (res.ok) {
        const data = await res.json();
        setKeys(data);
      }
    } catch (error) {
      console.error("Failed to fetch API keys:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchLlmConfig = async () => {
    try {
      const res = await fetch("/api/settings/llm");
      if (res.ok) {
        const data = await res.json();
        setLlmConfig(data);
        setSelectedProvider(data.provider);
        setSelectedModel(data.model);
      }
    } catch (error) {
      console.error("Failed to fetch LLM config:", error);
    }
  };

  const saveKey = async (service: string) => {
    const apiKey = newKeys[service];
    if (!apiKey?.trim()) return;

    setSaving(service);
    try {
      const res = await fetch("/api/settings/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ service, apiKey: apiKey.trim() }),
      });

      if (res.ok) {
        await fetchKeys();
        setNewKeys((prev) => ({ ...prev, [service]: "" }));
        setSuccessMessage(t("settings.apiKeySaved", { service }));
        setTimeout(() => setSuccessMessage(null), 3000);
      }
    } catch (error) {
      console.error("Failed to save API key:", error);
    } finally {
      setSaving(null);
    }
  };

  const deleteKey = async (service: string) => {
    try {
      const res = await fetch(`/api/settings/api-keys?service=${service}`, {
        method: "DELETE",
      });

      if (res.ok) {
        await fetchKeys();
        setSuccessMessage(t("settings.apiKeyDeleted", { service }));
        setTimeout(() => setSuccessMessage(null), 3000);
      }
    } catch (error) {
      console.error("Failed to delete API key:", error);
    }
  };

  const saveLlmConfig = async () => {
    setSavingLlm(true);
    try {
      const res = await fetch("/api/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: selectedProvider,
          model: selectedModel,
          isDefault: true,
        }),
      });

      if (res.ok) {
        await fetchLlmConfig();
        setSuccessMessage(t("settings.llmConfigSaved"));
        setTimeout(() => setSuccessMessage(null), 3000);
      }
    } catch (error) {
      console.error("Failed to save LLM config:", error);
    } finally {
      setSavingLlm(false);
    }
  };

  const handleLanguageChange = async (newLocale: Locale) => {
    setSavingLanguage(true);
    try {
      await setLocale(newLocale);
      setSuccessMessage(t("settings.languageSaved"));
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (error) {
      console.error("Failed to save language:", error);
    } finally {
      setSavingLanguage(false);
    }
  };

  const getKeyStatus = (serviceId: string) => {
    return keys.find((k) => k.service === serviceId);
  };

  const handleProviderChange = (provider: LlmProvider) => {
    setSelectedProvider(provider);
    // Set first model as default when switching providers
    const models = llmConfig?.availableModels[provider] || [];
    if (models.length > 0) {
      setSelectedModel(models[0].id);
    }
  };

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight flex items-center gap-3">
            <Settings2 className="h-8 w-8 text-primary" />
            {t("settings.title")}
          </h1>
          <p className="text-muted-foreground mt-1">
            {t("settings.description")}
          </p>
        </div>
        <LoadingSkeleton />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-8 stagger-fade">
      {/* Header */}
      <div className="text-center space-y-3">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/15 to-primary/5 mb-2">
          <Settings2 className="h-8 w-8 text-primary" />
        </div>
        <h1 className="font-serif text-3xl sm:text-4xl tracking-tight">
          {t("settings.title")}
        </h1>
        <p className="text-muted-foreground max-w-md mx-auto">
          {t("settings.description")}
        </p>
        <Badge variant="outline" className="text-xs">{t("common.byok")}</Badge>
      </div>

      {/* Success Message */}
      {successMessage && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-gradient-to-r from-[hsl(var(--status-completed))]/10 to-transparent border border-[hsl(var(--status-completed))]/20 animate-fade-in">
          <div className="p-1.5 rounded-full bg-[hsl(var(--status-completed))]/15">
            <Check className="h-4 w-4 text-[hsl(var(--status-completed))]" />
          </div>
          <p className="text-sm font-medium text-[hsl(var(--status-completed))]">
            {successMessage}
          </p>
        </div>
      )}

      {/* Language Selector */}
      <Card className="overflow-hidden border-2 border-[hsl(275,45%,48%)]/25 relative">
        {/* Decorative background pattern for language card */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none opacity-[0.03]">
          <div className="absolute -right-8 -top-8 text-[180px] font-serif leading-none select-none text-foreground">
            가
          </div>
          <div className="absolute -left-4 -bottom-6 text-[120px] font-serif leading-none select-none text-foreground">
            A
          </div>
        </div>
        <CardHeader className="relative bg-gradient-to-br from-[hsl(275,45%,48%)]/10 via-[hsl(275,45%,48%)]/5 to-transparent border-b border-[hsl(275,45%,48%)]/15">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[hsl(275,45%,48%)]/15 relative">
              <Globe className="h-4 w-4 text-[hsl(275,45%,48%)]" />
              <div className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-[hsl(275,45%,48%)] animate-pulse" />
            </div>
            <span className="bg-gradient-to-r from-[hsl(275,45%,48%)] to-[hsl(205,65%,50%)] bg-clip-text text-transparent">
              {t("settings.language")}
            </span>
          </CardTitle>
          <CardDescription>
            {t("settings.languageDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6 space-y-5 relative">
          <div className="grid grid-cols-2 gap-4">
            <LanguageButton
              localeValue="en"
              currentLocale={locale}
              label="English"
              displayText="Aa"
              onClick={handleLanguageChange}
              disabled={savingLanguage}
              isLoading={savingLanguage}
            />
            <LanguageButton
              localeValue="ko"
              currentLocale={locale}
              label="한국어"
              displayText="가나"
              onClick={handleLanguageChange}
              disabled={savingLanguage}
              isLoading={savingLanguage}
            />
          </div>

          {/* Language-specific hint text */}
          <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
            <span className="w-8 h-px bg-border" />
            <span>
              {locale === "ko"
                ? "보고서가 한국어로 자동 번역됩니다"
                : "Reports will be generated in English"}
            </span>
            <span className="w-8 h-px bg-border" />
          </div>
        </CardContent>
      </Card>

      {/* LLM Model Selector */}
      <Card className="overflow-hidden border-2 border-primary/20">
        <CardHeader className="bg-gradient-to-br from-primary/8 via-primary/4 to-transparent border-b border-primary/10">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <Settings2 className="h-4 w-4 text-primary" />
            </div>
            {t("settings.defaultLlmModel")}
          </CardTitle>
          <CardDescription>
            {t("settings.defaultLlmDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6 space-y-5">
          {/* Provider Selection */}
          <div className="space-y-3">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">{t("settings.provider")}</Label>
            <div className="grid grid-cols-3 gap-3">
              <Button
                variant={selectedProvider === "openai" ? "default" : "outline"}
                className={cn(
                  "h-12 justify-center gap-2",
                  selectedProvider === "openai" && "shadow-md shadow-primary/20"
                )}
                onClick={() => handleProviderChange("openai")}
              >
                <Sparkles className="h-4 w-4" />
                <span>OpenAI</span>
              </Button>
              <Button
                variant={selectedProvider === "anthropic" ? "default" : "outline"}
                className={cn(
                  "h-12 justify-center gap-2",
                  selectedProvider === "anthropic" && "shadow-md shadow-primary/20"
                )}
                onClick={() => handleProviderChange("anthropic")}
              >
                <Brain className="h-4 w-4" />
                <span>Anthropic</span>
              </Button>
              <Button
                variant={selectedProvider === "google" ? "default" : "outline"}
                className={cn(
                  "h-12 justify-center gap-2",
                  selectedProvider === "google" && "shadow-md shadow-primary/20"
                )}
                onClick={() => handleProviderChange("google")}
              >
                <Sparkles className="h-4 w-4" />
                <span>Google</span>
              </Button>
            </div>
          </div>

          {/* Model Selection */}
          <div className="space-y-3">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">{t("settings.model")}</Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger className="h-12">
                <SelectValue placeholder={t("settings.selectModel")} />
              </SelectTrigger>
              <SelectContent>
                {llmConfig?.availableModels[selectedProvider]?.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    <div className="flex flex-col py-1">
                      <span className="font-medium">{model.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {model.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Current Selection Info */}
          {llmConfig && (
            <div className="flex items-center justify-center gap-2 p-3 rounded-lg bg-muted/50 text-sm">
              <span className="text-muted-foreground">{t("common.current")}:</span>
              <Badge variant="secondary" className="font-mono text-xs">
                {llmConfig.provider}/{llmConfig.model}
              </Badge>
            </div>
          )}

          {/* Save Button */}
          <Button
            onClick={saveLlmConfig}
            disabled={savingLlm}
            className="w-full h-11 shadow-md shadow-primary/15"
          >
            {savingLlm ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Check className="h-4 w-4 mr-2" />
            )}
            {t("settings.saveAsDefault")}
          </Button>
        </CardContent>
      </Card>

      {/* API Key Cards */}
      <div className="space-y-4">
        {API_SERVICES.map((service, index) => {
          const existingKey = getKeyStatus(service.id);
          const isConfigured = !!existingKey;
          const Icon = service.icon;
          const serviceName = t(service.nameKey);
          const serviceDescription = t(service.descriptionKey);

          return (
            <Card
              key={service.id}
              className={cn(
                "overflow-hidden transition-all duration-200",
                isConfigured && "border-l-4 border-l-status-completed"
              )}
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        "p-2.5 rounded-lg bg-muted",
                        isConfigured && "bg-status-completed/10"
                      )}
                    >
                      <Icon className={cn("h-5 w-5", service.color)} />
                    </div>
                    <div>
                      <CardTitle className="text-lg flex items-center gap-2">
                        {serviceName}
                        {service.required && (
                          <Badge
                            variant="outline"
                            className="text-xs font-normal"
                          >
                            {t("common.required")}
                          </Badge>
                        )}
                        {isConfigured && (
                          <Badge className="text-xs bg-status-completed text-white">
                            <Check className="h-3 w-3 mr-1" />
                            {t("common.configured")}
                          </Badge>
                        )}
                      </CardTitle>
                      <CardDescription className="mt-0.5">
                        {serviceDescription}
                      </CardDescription>
                    </div>
                  </div>
                  <a
                    href={service.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-primary flex items-center gap-1 transition-colors"
                  >
                    {t("settings.getApiKey")}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {isConfigured && (
                  <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg border">
                    <code className="text-sm font-mono text-muted-foreground">
                      {existingKey.apiKey}
                    </code>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive hover:bg-destructive/10"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>{t("settings.deleteApiKey")}</AlertDialogTitle>
                          <AlertDialogDescription>
                            {t("settings.deleteApiKeyConfirm", { service: serviceName })}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => deleteKey(service.id)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          >
                            {t("common.delete")}
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                )}
                <div className="flex gap-2">
                  <div className="flex-1">
                    <Label htmlFor={`key-${service.id}`} className="sr-only">
                      API Key
                    </Label>
                    <Input
                      id={`key-${service.id}`}
                      type="password"
                      placeholder={
                        isConfigured
                          ? t("settings.enterNewKey")
                          : t("settings.enterApiKey")
                      }
                      value={newKeys[service.id] || ""}
                      onChange={(e) =>
                        setNewKeys((prev) => ({
                          ...prev,
                          [service.id]: e.target.value,
                        }))
                      }
                      className="font-mono"
                    />
                  </div>
                  <Button
                    onClick={() => saveKey(service.id)}
                    disabled={
                      !newKeys[service.id]?.trim() || saving === service.id
                    }
                  >
                    {saving === service.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      t("common.save")
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Security Note */}
      <Card className="bg-gradient-to-br from-muted/40 to-transparent border-dashed border-2">
        <CardContent className="py-6">
          <div className="flex items-start gap-4">
            <div className="p-2.5 rounded-lg bg-muted">
              <Shield className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <p className="font-serif font-medium">{t("settings.securityNote")}</p>
              <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                {t("settings.securityDescription")}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
