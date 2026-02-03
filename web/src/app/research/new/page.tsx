"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useStartResearch } from "@/lib/research";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2, Search, FlaskConical } from "lucide-react";

export default function NewResearchPage() {
  const router = useRouter();
  const startResearch = useStartResearch();

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"free" | "pico">("free");

  // PICO fields
  const [population, setPopulation] = useState("");
  const [intervention, setIntervention] = useState("");
  const [comparison, setComparison] = useState("");
  const [outcome, setOutcome] = useState("");

  const buildPicoQuery = () => {
    const parts = [];
    if (population) parts.push(`Population: ${population}`);
    if (intervention) parts.push(`Intervention: ${intervention}`);
    if (comparison) parts.push(`Comparison: ${comparison}`);
    if (outcome) parts.push(`Outcome: ${outcome}`);
    return parts.join("\n");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const finalQuery = mode === "pico" ? buildPicoQuery() : query;

    if (!finalQuery.trim()) {
      return;
    }

    try {
      const result = await startResearch.mutateAsync({ query: finalQuery });
      router.push(`/research/${result.research_id}`);
    } catch (error) {
      console.error("Failed to start research:", error);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">New Research</h1>
        <p className="text-muted-foreground">
          Start a new evidence-based medical research query
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5" />
            Research Query
          </CardTitle>
          <CardDescription>
            Enter your research question using free-form text or the PICO
            framework
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            <Tabs value={mode} onValueChange={(v) => setMode(v as "free" | "pico")}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="free">Free-form Query</TabsTrigger>
                <TabsTrigger value="pico">PICO Framework</TabsTrigger>
              </TabsList>

              <TabsContent value="free" className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label htmlFor="query">Research Question</Label>
                  <Textarea
                    id="query"
                    placeholder="Enter your research question, e.g., 'What is the effectiveness of metformin vs SGLT2 inhibitors for type 2 diabetes cardiovascular outcomes?'"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    rows={4}
                    className="resize-none"
                  />
                </div>
              </TabsContent>

              <TabsContent value="pico" className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label htmlFor="population">
                    P - Population/Patient
                    <span className="text-muted-foreground font-normal ml-2">
                      Who are the patients?
                    </span>
                  </Label>
                  <Input
                    id="population"
                    placeholder="e.g., Adults with type 2 diabetes"
                    value={population}
                    onChange={(e) => setPopulation(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="intervention">
                    I - Intervention
                    <span className="text-muted-foreground font-normal ml-2">
                      What treatment/exposure?
                    </span>
                  </Label>
                  <Input
                    id="intervention"
                    placeholder="e.g., SGLT2 inhibitors"
                    value={intervention}
                    onChange={(e) => setIntervention(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="comparison">
                    C - Comparison
                    <span className="text-muted-foreground font-normal ml-2">
                      What is the alternative?
                    </span>
                  </Label>
                  <Input
                    id="comparison"
                    placeholder="e.g., Metformin monotherapy"
                    value={comparison}
                    onChange={(e) => setComparison(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="outcome">
                    O - Outcome
                    <span className="text-muted-foreground font-normal ml-2">
                      What results matter?
                    </span>
                  </Label>
                  <Input
                    id="outcome"
                    placeholder="e.g., Cardiovascular events, mortality"
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value)}
                  />
                </div>

                {(population || intervention || comparison || outcome) && (
                  <div className="mt-4 p-4 bg-muted rounded-lg">
                    <p className="text-sm font-medium mb-2">Generated Query:</p>
                    <p className="text-sm text-muted-foreground whitespace-pre-line">
                      {buildPicoQuery() || "Fill in the fields above..."}
                    </p>
                  </div>
                )}
              </TabsContent>
            </Tabs>

            {startResearch.error && (
              <div className="p-3 bg-destructive/10 text-destructive rounded-md text-sm">
                {startResearch.error.message}
              </div>
            )}

            <Button
              type="submit"
              className="w-full"
              size="lg"
              disabled={
                startResearch.isPending ||
                (mode === "free" && !query.trim()) ||
                (mode === "pico" && !population && !intervention && !outcome)
              }
            >
              {startResearch.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Starting Research...
                </>
              ) : (
                <>
                  <Search className="h-4 w-4 mr-2" />
                  Start Research
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
