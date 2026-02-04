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
import { Loader2, Search, FlaskConical, BookOpen, FileText } from "lucide-react";

type QueryType = "pico" | "pcc" | "free";

export default function NewResearchPage() {
  const router = useRouter();
  const startResearch = useStartResearch();

  const [queryType, setQueryType] = useState<QueryType>("pico");
  const [freeQuery, setFreeQuery] = useState("");

  // PICO fields
  const [picoPopulation, setPicoPopulation] = useState("");
  const [picoIntervention, setPicoIntervention] = useState("");
  const [picoComparison, setPicoComparison] = useState("");
  const [picoOutcome, setPicoOutcome] = useState("");

  // PCC fields
  const [pccPopulation, setPccPopulation] = useState("");
  const [pccConcept, setPccConcept] = useState("");
  const [pccContext, setPccContext] = useState("");

  const buildPicoQuery = () => {
    const parts = [];
    if (picoPopulation) parts.push(`Population: ${picoPopulation}`);
    if (picoIntervention) parts.push(`Intervention: ${picoIntervention}`);
    if (picoComparison) parts.push(`Comparison: ${picoComparison}`);
    if (picoOutcome) parts.push(`Outcome: ${picoOutcome}`);
    return parts.join("\n");
  };

  const buildPccQuery = () => {
    const parts = [];
    if (pccPopulation) parts.push(`Population: ${pccPopulation}`);
    if (pccConcept) parts.push(`Concept: ${pccConcept}`);
    if (pccContext) parts.push(`Context: ${pccContext}`);
    return parts.join("\n");
  };

  const getQuery = () => {
    if (queryType === "pico") return buildPicoQuery();
    if (queryType === "pcc") return buildPccQuery();
    return freeQuery;
  };

  const isValid = () => {
    if (queryType === "pico") {
      return picoPopulation.trim() || picoIntervention.trim() || picoOutcome.trim();
    }
    if (queryType === "pcc") {
      return pccPopulation.trim() || pccConcept.trim() || pccContext.trim();
    }
    return freeQuery.trim();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const query = getQuery();
    if (!query.trim()) return;

    try {
      const result = await startResearch.mutateAsync({
        query,
        queryType,
        picoComponents:
          queryType === "pico"
            ? {
                population: picoPopulation,
                intervention: picoIntervention,
                comparison: picoComparison,
                outcome: picoOutcome,
              }
            : undefined,
        pccComponents:
          queryType === "pcc"
            ? {
                population: pccPopulation,
                concept: pccConcept,
                context: pccContext,
              }
            : undefined,
      });
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
            Choose a framework for your research question. PICO is recommended for
            clinical intervention questions, PCC for scoping reviews.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            <Tabs
              value={queryType}
              onValueChange={(v) => setQueryType(v as QueryType)}
            >
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="pico" className="flex items-center gap-1">
                  <BookOpen className="h-4 w-4" />
                  PICO
                </TabsTrigger>
                <TabsTrigger value="pcc" className="flex items-center gap-1">
                  <FileText className="h-4 w-4" />
                  PCC
                </TabsTrigger>
                <TabsTrigger value="free" className="flex items-center gap-1">
                  <Search className="h-4 w-4" />
                  Free-form
                </TabsTrigger>
              </TabsList>

              {/* PICO Framework */}
              <TabsContent value="pico" className="space-y-4 mt-4">
                <div className="text-sm text-muted-foreground bg-muted p-3 rounded-lg">
                  <strong>PICO Framework</strong> - Best for clinical questions about
                  interventions, therapies, or treatments.
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pico-population">
                    P - Population/Patient
                    <span className="text-muted-foreground font-normal ml-2">
                      Who are the patients?
                    </span>
                  </Label>
                  <Input
                    id="pico-population"
                    placeholder="e.g., Adults with type 2 diabetes"
                    value={picoPopulation}
                    onChange={(e) => setPicoPopulation(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pico-intervention">
                    I - Intervention
                    <span className="text-muted-foreground font-normal ml-2">
                      What treatment/exposure?
                    </span>
                  </Label>
                  <Input
                    id="pico-intervention"
                    placeholder="e.g., SGLT2 inhibitors"
                    value={picoIntervention}
                    onChange={(e) => setPicoIntervention(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pico-comparison">
                    C - Comparison{" "}
                    <span className="text-xs text-muted-foreground">(optional)</span>
                    <span className="text-muted-foreground font-normal ml-2">
                      What is the alternative?
                    </span>
                  </Label>
                  <Input
                    id="pico-comparison"
                    placeholder="e.g., Metformin monotherapy"
                    value={picoComparison}
                    onChange={(e) => setPicoComparison(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pico-outcome">
                    O - Outcome
                    <span className="text-muted-foreground font-normal ml-2">
                      What results matter?
                    </span>
                  </Label>
                  <Input
                    id="pico-outcome"
                    placeholder="e.g., Cardiovascular events, mortality"
                    value={picoOutcome}
                    onChange={(e) => setPicoOutcome(e.target.value)}
                  />
                </div>

                {(picoPopulation || picoIntervention || picoComparison || picoOutcome) && (
                  <div className="mt-4 p-4 bg-muted rounded-lg">
                    <p className="text-sm font-medium mb-2">Generated Query:</p>
                    <p className="text-sm text-muted-foreground whitespace-pre-line">
                      {buildPicoQuery() || "Fill in the fields above..."}
                    </p>
                  </div>
                )}
              </TabsContent>

              {/* PCC Framework */}
              <TabsContent value="pcc" className="space-y-4 mt-4">
                <div className="text-sm text-muted-foreground bg-muted p-3 rounded-lg">
                  <strong>PCC Framework</strong> - Best for scoping reviews, qualitative
                  research, or exploratory questions.
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pcc-population">
                    P - Population
                    <span className="text-muted-foreground font-normal ml-2">
                      Who is being studied?
                    </span>
                  </Label>
                  <Input
                    id="pcc-population"
                    placeholder="e.g., Healthcare workers"
                    value={pccPopulation}
                    onChange={(e) => setPccPopulation(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pcc-concept">
                    C - Concept
                    <span className="text-muted-foreground font-normal ml-2">
                      What phenomenon of interest?
                    </span>
                  </Label>
                  <Input
                    id="pcc-concept"
                    placeholder="e.g., Burnout experiences"
                    value={pccConcept}
                    onChange={(e) => setPccConcept(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="pcc-context">
                    C - Context
                    <span className="text-muted-foreground font-normal ml-2">
                      In what setting?
                    </span>
                  </Label>
                  <Input
                    id="pcc-context"
                    placeholder="e.g., During COVID-19 pandemic"
                    value={pccContext}
                    onChange={(e) => setPccContext(e.target.value)}
                  />
                </div>

                {(pccPopulation || pccConcept || pccContext) && (
                  <div className="mt-4 p-4 bg-muted rounded-lg">
                    <p className="text-sm font-medium mb-2">Generated Query:</p>
                    <p className="text-sm text-muted-foreground whitespace-pre-line">
                      {buildPccQuery() || "Fill in the fields above..."}
                    </p>
                  </div>
                )}
              </TabsContent>

              {/* Free-form Query */}
              <TabsContent value="free" className="space-y-4 mt-4">
                <div className="text-sm text-muted-foreground bg-muted p-3 rounded-lg">
                  <strong>Free-form Query</strong> - Enter your research question in
                  natural language. The agent will determine the best search strategy.
                </div>

                <div className="space-y-2">
                  <Label htmlFor="free-query">Research Question</Label>
                  <Textarea
                    id="free-query"
                    placeholder="Enter your research question, e.g., 'What is the effectiveness of metformin vs SGLT2 inhibitors for type 2 diabetes cardiovascular outcomes?'"
                    value={freeQuery}
                    onChange={(e) => setFreeQuery(e.target.value)}
                    rows={4}
                    className="resize-none"
                  />
                </div>
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
              disabled={startResearch.isPending || !isValid()}
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
