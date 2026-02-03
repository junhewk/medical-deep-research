"use client";

import { useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { CheckCircle, Loader2, XCircle } from "lucide-react";

export default function SettingsPage() {
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [ncbiKey, setNcbiKey] = useState("");
  const [testStatus, setTestStatus] = useState<
    Record<string, "idle" | "testing" | "success" | "error">
  >({});

  const testConnection = async (provider: string) => {
    setTestStatus((prev) => ({ ...prev, [provider]: "testing" }));

    // Simulate API test - in production, this would call the backend
    await new Promise((resolve) => setTimeout(resolve, 1500));

    // Random success/failure for demo
    const success = Math.random() > 0.3;
    setTestStatus((prev) => ({
      ...prev,
      [provider]: success ? "success" : "error",
    }));
  };

  const saveSettings = async () => {
    // Save settings to backend
    const settings = {
      openai_api_key: openaiKey,
      anthropic_api_key: anthropicKey,
      gemini_api_key: geminiKey,
      ncbi_api_key: ncbiKey,
    };

    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      if (response.ok) {
        alert("Settings saved successfully!");
      }
    } catch (error) {
      console.error("Failed to save settings:", error);
      alert("Failed to save settings");
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-muted-foreground">
          Configure your AI providers and API keys
        </p>
      </div>

      <Tabs defaultValue="ai">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="ai">AI Providers</TabsTrigger>
          <TabsTrigger value="search">Search Settings</TabsTrigger>
        </TabsList>

        <TabsContent value="ai" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">OpenAI</CardTitle>
              <CardDescription>
                GPT-4, GPT-4o, and other OpenAI models
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="openai-key">API Key</Label>
                <div className="flex gap-2">
                  <Input
                    id="openai-key"
                    type="password"
                    placeholder="sk-..."
                    value={openaiKey}
                    onChange={(e) => setOpenaiKey(e.target.value)}
                  />
                  <Button
                    variant="outline"
                    onClick={() => testConnection("openai")}
                    disabled={!openaiKey || testStatus.openai === "testing"}
                  >
                    {testStatus.openai === "testing" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : testStatus.openai === "success" ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : testStatus.openai === "error" ? (
                      <XCircle className="h-4 w-4 text-red-500" />
                    ) : (
                      "Test"
                    )}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Anthropic</CardTitle>
              <CardDescription>
                Claude 3.5 Sonnet, Claude 3 Opus
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="anthropic-key">API Key</Label>
                <div className="flex gap-2">
                  <Input
                    id="anthropic-key"
                    type="password"
                    placeholder="sk-ant-..."
                    value={anthropicKey}
                    onChange={(e) => setAnthropicKey(e.target.value)}
                  />
                  <Button
                    variant="outline"
                    onClick={() => testConnection("anthropic")}
                    disabled={
                      !anthropicKey || testStatus.anthropic === "testing"
                    }
                  >
                    {testStatus.anthropic === "testing" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : testStatus.anthropic === "success" ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : testStatus.anthropic === "error" ? (
                      <XCircle className="h-4 w-4 text-red-500" />
                    ) : (
                      "Test"
                    )}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Google Gemini</CardTitle>
              <CardDescription>Gemini Pro, Gemini Ultra</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="gemini-key">API Key</Label>
                <div className="flex gap-2">
                  <Input
                    id="gemini-key"
                    type="password"
                    placeholder="AIza..."
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                  />
                  <Button
                    variant="outline"
                    onClick={() => testConnection("gemini")}
                    disabled={!geminiKey || testStatus.gemini === "testing"}
                  >
                    {testStatus.gemini === "testing" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : testStatus.gemini === "success" ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : testStatus.gemini === "error" ? (
                      <XCircle className="h-4 w-4 text-red-500" />
                    ) : (
                      "Test"
                    )}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CardTitle className="text-lg">Ollama</CardTitle>
                <Badge variant="secondary">Local</Badge>
              </div>
              <CardDescription>
                Run models locally - no API key needed
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Ollama runs locally at http://localhost:11434. Make sure Ollama
                is installed and running.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="search" className="space-y-4 mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">PubMed / NCBI</CardTitle>
              <CardDescription>
                Optional: Add an NCBI API key for higher rate limits
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="ncbi-key">NCBI API Key (Optional)</Label>
                <Input
                  id="ncbi-key"
                  type="password"
                  placeholder="NCBI API Key"
                  value={ncbiKey}
                  onChange={(e) => setNcbiKey(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Get a free API key from{" "}
                  <a
                    href="https://www.ncbi.nlm.nih.gov/account/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    NCBI
                  </a>
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Button onClick={saveSettings} className="w-full">
        Save Settings
      </Button>
    </div>
  );
}
