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
import { Key, Loader2, Check, Trash2, ExternalLink } from "lucide-react";

interface ApiKey {
  id: string;
  service: string;
  apiKey: string;
  createdAt: string;
  updatedAt?: string;
}

const API_SERVICES = [
  {
    id: "openai",
    name: "OpenAI",
    description: "Required for GPT-4 based research (default LLM)",
    required: true,
    docsUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "anthropic",
    name: "Anthropic",
    description: "Required for Claude-based research",
    required: false,
    docsUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "ncbi",
    name: "NCBI/PubMed",
    description: "Optional - increases PubMed rate limits (free)",
    required: false,
    docsUrl: "https://www.ncbi.nlm.nih.gov/account/settings/#accountSettingsApiKeyManagement",
  },
  {
    id: "scopus",
    name: "Scopus/Elsevier",
    description: "Required for Scopus database searches",
    required: false,
    docsUrl: "https://dev.elsevier.com/apikey/manage",
  },
  {
    id: "cochrane",
    name: "Cochrane Library",
    description: "Optional - for direct Cochrane API access",
    required: false,
    docsUrl: "https://www.cochranelibrary.com/",
  },
];

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [newKeys, setNewKeys] = useState<Record<string, string>>({});
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchKeys();
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
    if (!confirm(`Delete ${service} API key?`)) return;

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

  const getKeyStatus = (serviceId: string) => {
    return keys.find((k) => k.service === serviceId);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Key className="h-6 w-6" />
          API Keys
        </h1>
        <p className="text-muted-foreground mt-1">
          Manage your API keys for LLM providers and search engines (BYOK - Bring Your
          Own Key)
        </p>
      </div>

      {successMessage && (
        <div className="p-3 bg-green-100 dark:bg-green-900/20 text-green-800 dark:text-green-200 rounded-md text-sm flex items-center gap-2">
          <Check className="h-4 w-4" />
          {successMessage}
        </div>
      )}

      <div className="space-y-4">
        {API_SERVICES.map((service) => {
          const existingKey = getKeyStatus(service.id);
          const isConfigured = !!existingKey;

          return (
            <Card key={service.id}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg flex items-center gap-2">
                    {service.name}
                    {service.required && (
                      <Badge variant="outline" className="text-xs">
                        Required
                      </Badge>
                    )}
                    {isConfigured && (
                      <Badge variant="default" className="text-xs bg-green-600">
                        Configured
                      </Badge>
                    )}
                  </CardTitle>
                  <a
                    href={service.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                  >
                    Get API Key
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
                <CardDescription>{service.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {isConfigured && (
                    <div className="flex items-center justify-between p-2 bg-muted rounded-md">
                      <span className="text-sm font-mono">{existingKey.apiKey}</span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => deleteKey(service.id)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
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
                          isConfigured ? "Enter new key to update" : "Enter API key"
                        }
                        value={newKeys[service.id] || ""}
                        onChange={(e) =>
                          setNewKeys((prev) => ({
                            ...prev,
                            [service.id]: e.target.value,
                          }))
                        }
                      />
                    </div>
                    <Button
                      onClick={() => saveKey(service.id)}
                      disabled={!newKeys[service.id]?.trim() || saving === service.id}
                    >
                      {saving === service.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        "Save"
                      )}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="bg-muted/50">
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">
            <strong>Security Note:</strong> API keys are stored locally in your
            database. They are never sent to external servers except for the specific
            API they belong to. For production use, consider using environment
            variables instead.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
