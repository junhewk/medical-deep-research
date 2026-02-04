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
  Key,
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
} from "lucide-react";
import { cn } from "@/lib/utils";

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
    name: "OpenAI",
    description: "Required for GPT based research (default LLM)",
    required: false,
    docsUrl: "https://platform.openai.com/api-keys",
    icon: Sparkles,
    color: "text-emerald-600 dark:text-emerald-400",
  },
  {
    id: "anthropic",
    name: "Anthropic",
    description: "Required for Claude-based research",
    required: false,
    docsUrl: "https://console.anthropic.com/settings/keys",
    icon: Brain,
    color: "text-orange-600 dark:text-orange-400",
  },
  {
    id: "google",
    name: "Google AI",
    description: "Required for Gemini-based research",
    required: false,
    docsUrl: "https://aistudio.google.com/app/apikey",
    icon: Sparkles,
    color: "text-blue-600 dark:text-blue-400",
  },
  {
    id: "ncbi",
    name: "NCBI/PubMed",
    description: "Optional - increases PubMed rate limits (free)",
    required: false,
    docsUrl:
      "https://www.ncbi.nlm.nih.gov/account/settings/#accountSettingsApiKeyManagement",
    icon: Database,
    color: "text-blue-600 dark:text-blue-400",
  },
  {
    id: "scopus",
    name: "Scopus/Elsevier",
    description: "Required for Scopus database searches",
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

export default function ApiKeysPage() {
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
        setSuccessMessage(`${service} API key saved successfully`);
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
        setSuccessMessage(`${service} API key deleted`);
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
        setSuccessMessage("LLM configuration saved successfully");
        setTimeout(() => setSuccessMessage(null), 3000);
      }
    } catch (error) {
      console.error("Failed to save LLM config:", error);
    } finally {
      setSavingLlm(false);
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
            <Key className="h-8 w-8 text-primary" />
            API Keys
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage your API keys for LLM providers and search engines
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
          <Key className="h-8 w-8 text-primary" />
        </div>
        <h1 className="font-serif text-3xl sm:text-4xl tracking-tight">
          API Configuration
        </h1>
        <p className="text-muted-foreground max-w-md mx-auto">
          Configure your API keys for LLM providers and search databases
        </p>
        <Badge variant="outline" className="text-xs">BYOK — Bring Your Own Key</Badge>
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

      {/* LLM Model Selector */}
      <Card className="overflow-hidden border-2 border-primary/20">
        <CardHeader className="bg-gradient-to-br from-primary/8 via-primary/4 to-transparent border-b border-primary/10">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <Settings2 className="h-4 w-4 text-primary" />
            </div>
            Default LLM Model
          </CardTitle>
          <CardDescription>
            Select the default language model for research tasks
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6 space-y-5">
          {/* Provider Selection */}
          <div className="space-y-3">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Provider</Label>
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
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Model</Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger className="h-12">
                <SelectValue placeholder="Select a model" />
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
              <span className="text-muted-foreground">Current:</span>
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
            Save as Default
          </Button>
        </CardContent>
      </Card>

      {/* API Key Cards */}
      <div className="space-y-4">
        {API_SERVICES.map((service, index) => {
          const existingKey = getKeyStatus(service.id);
          const isConfigured = !!existingKey;
          const Icon = service.icon;

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
                        {service.name}
                        {service.required && (
                          <Badge
                            variant="outline"
                            className="text-xs font-normal"
                          >
                            Required
                          </Badge>
                        )}
                        {isConfigured && (
                          <Badge className="text-xs bg-status-completed text-white">
                            <Check className="h-3 w-3 mr-1" />
                            Configured
                          </Badge>
                        )}
                      </CardTitle>
                      <CardDescription className="mt-0.5">
                        {service.description}
                      </CardDescription>
                    </div>
                  </div>
                  <a
                    href={service.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-primary flex items-center gap-1 transition-colors"
                  >
                    Get API Key
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
                          <AlertDialogTitle>Delete API Key</AlertDialogTitle>
                          <AlertDialogDescription>
                            Are you sure you want to delete the {service.name}{" "}
                            API key? This action cannot be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => deleteKey(service.id)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          >
                            Delete
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
                          ? "Enter new key to update..."
                          : "Enter API key..."
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
                      "Save"
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
              <p className="font-serif font-medium">Security Note</p>
              <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                API keys are stored locally in your database and are never sent
                to external servers except for the specific API they belong to.
                For production deployments, consider using environment variables
                instead.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
