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
import { Badge } from "@/components/ui/badge";
import {
  Loader2,
  Search,
  BookOpen,
  FileText,
  Sparkles,
  Users,
  Syringe,
  GitCompare,
  Target,
  Lightbulb,
  MapPin,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

type QueryType = "pico" | "pcc" | "free";

interface FieldConfig {
  id: string;
  label: string;
  shortLabel: string;
  placeholder: string;
  helpText: string;
  icon: typeof Users;
  colorClass: string;
  optional?: boolean;
}

const picoFields: FieldConfig[] = [
  {
    id: "population",
    label: "Population / Patient",
    shortLabel: "P",
    placeholder: "e.g., Adults with type 2 diabetes",
    helpText: "Who are the patients or population of interest?",
    icon: Users,
    colorClass: "pico-population",
  },
  {
    id: "intervention",
    label: "Intervention / Exposure",
    shortLabel: "I",
    placeholder: "e.g., SGLT2 inhibitors",
    helpText: "What is the treatment or exposure being studied?",
    icon: Syringe,
    colorClass: "pico-intervention",
  },
  {
    id: "comparison",
    label: "Comparison",
    shortLabel: "C",
    placeholder: "e.g., Metformin monotherapy",
    helpText: "What is the alternative or control?",
    icon: GitCompare,
    colorClass: "pico-comparison",
    optional: true,
  },
  {
    id: "outcome",
    label: "Outcome",
    shortLabel: "O",
    placeholder: "e.g., Cardiovascular events, mortality",
    helpText: "What results or outcomes matter?",
    icon: Target,
    colorClass: "pico-outcome",
  },
];

const pccFields: FieldConfig[] = [
  {
    id: "population",
    label: "Population",
    shortLabel: "P",
    placeholder: "e.g., Healthcare workers",
    helpText: "Who is the population being studied?",
    icon: Users,
    colorClass: "pico-population",
  },
  {
    id: "concept",
    label: "Concept",
    shortLabel: "C",
    placeholder: "e.g., Burnout experiences",
    helpText: "What is the phenomenon or concept of interest?",
    icon: Lightbulb,
    colorClass: "pico-comparison",
  },
  {
    id: "context",
    label: "Context",
    shortLabel: "C",
    placeholder: "e.g., During COVID-19 pandemic",
    helpText: "In what setting or context?",
    icon: MapPin,
    colorClass: "pico-outcome",
  },
];

export default function NewResearchPage() {
  const router = useRouter();
  const startResearch = useStartResearch();

  const [queryType, setQueryType] = useState<QueryType>("pico");
  const [freeQuery, setFreeQuery] = useState("");

  // PICO fields
  const [picoValues, setPicoValues] = useState({
    population: "",
    intervention: "",
    comparison: "",
    outcome: "",
  });

  // PCC fields
  const [pccValues, setPccValues] = useState({
    population: "",
    concept: "",
    context: "",
  });

  const buildPicoQuery = () => {
    const parts = [];
    if (picoValues.population) parts.push(`Population: ${picoValues.population}`);
    if (picoValues.intervention)
      parts.push(`Intervention: ${picoValues.intervention}`);
    if (picoValues.comparison)
      parts.push(`Comparison: ${picoValues.comparison}`);
    if (picoValues.outcome) parts.push(`Outcome: ${picoValues.outcome}`);
    return parts.join("\n");
  };

  const buildPccQuery = () => {
    const parts = [];
    if (pccValues.population) parts.push(`Population: ${pccValues.population}`);
    if (pccValues.concept) parts.push(`Concept: ${pccValues.concept}`);
    if (pccValues.context) parts.push(`Context: ${pccValues.context}`);
    return parts.join("\n");
  };

  const getQuery = () => {
    if (queryType === "pico") return buildPicoQuery();
    if (queryType === "pcc") return buildPccQuery();
    return freeQuery;
  };

  const isValid = () => {
    if (queryType === "pico") {
      return (
        picoValues.population.trim() ||
        picoValues.intervention.trim() ||
        picoValues.outcome.trim()
      );
    }
    if (queryType === "pcc") {
      return (
        pccValues.population.trim() ||
        pccValues.concept.trim() ||
        pccValues.context.trim()
      );
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
                population: picoValues.population,
                intervention: picoValues.intervention,
                comparison: picoValues.comparison,
                outcome: picoValues.outcome,
              }
            : undefined,
        pccComponents:
          queryType === "pcc"
            ? {
                population: pccValues.population,
                concept: pccValues.concept,
                context: pccValues.context,
              }
            : undefined,
      });
      router.push(`/research/${result.research_id}`);
    } catch (error) {
      console.error("Failed to start research:", error);
    }
  };

  const renderField = (
    field: FieldConfig,
    value: string,
    onChange: (value: string) => void
  ) => {
    const Icon = field.icon;
    return (
      <div key={field.id} className="group">
        <Label
          htmlFor={`field-${field.id}`}
          className="flex items-center gap-2 mb-2"
        >
          <Badge
            variant="outline"
            className={cn("text-xs font-bold border", field.colorClass)}
          >
            {field.shortLabel}
          </Badge>
          <span className="font-medium">{field.label}</span>
          {field.optional && (
            <span className="text-xs text-muted-foreground">(optional)</span>
          )}
        </Label>
        <div className="relative">
          <Icon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
          <Input
            id={`field-${field.id}`}
            placeholder={field.placeholder}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="pl-10 transition-shadow focus:shadow-md focus:shadow-primary/10"
          />
        </div>
        <p className="text-xs text-muted-foreground mt-1.5 ml-1">
          {field.helpText}
        </p>
      </div>
    );
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6 fade-in-stagger">
      {/* Header */}
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          New Research Query
        </h1>
        <p className="text-muted-foreground mt-1">
          Start an evidence-based medical literature search
        </p>
      </div>

      {/* Main Card */}
      <Card className="overflow-hidden">
        <CardHeader className="bg-gradient-to-r from-primary/5 to-transparent border-b">
          <CardTitle className="flex items-center gap-2 font-serif">
            <Search className="h-5 w-5 text-primary" />
            Research Framework
          </CardTitle>
          <CardDescription>
            Choose a framework for structuring your research question
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-6">
            <Tabs
              value={queryType}
              onValueChange={(v) => setQueryType(v as QueryType)}
            >
              <TabsList className="grid w-full grid-cols-3 h-auto p-1">
                <TabsTrigger
                  value="pico"
                  className="flex items-center gap-2 py-3 data-[state=active]:bg-pico-p/10 data-[state=active]:text-pico-p"
                >
                  <BookOpen className="h-4 w-4" />
                  <span className="hidden sm:inline">PICO</span>
                </TabsTrigger>
                <TabsTrigger
                  value="pcc"
                  className="flex items-center gap-2 py-3 data-[state=active]:bg-pico-c/10 data-[state=active]:text-pico-c"
                >
                  <FileText className="h-4 w-4" />
                  <span className="hidden sm:inline">PCC</span>
                </TabsTrigger>
                <TabsTrigger
                  value="free"
                  className="flex items-center gap-2 py-3 data-[state=active]:bg-accent/10 data-[state=active]:text-accent"
                >
                  <Sparkles className="h-4 w-4" />
                  <span className="hidden sm:inline">Free-form</span>
                </TabsTrigger>
              </TabsList>

              {/* PICO Framework */}
              <TabsContent value="pico" className="space-y-6 mt-6">
                <div className="flex items-start gap-3 p-4 rounded-lg bg-pico-p/5 border border-pico-p/20">
                  <BookOpen className="h-5 w-5 text-pico-p mt-0.5" />
                  <div>
                    <p className="font-medium text-sm">PICO Framework</p>
                    <p className="text-sm text-muted-foreground">
                      Best for clinical questions about interventions, therapies,
                      or treatments
                    </p>
                  </div>
                </div>

                <div className="space-y-5">
                  {picoFields.map((field) =>
                    renderField(
                      field,
                      picoValues[field.id as keyof typeof picoValues],
                      (value) =>
                        setPicoValues((prev) => ({ ...prev, [field.id]: value }))
                    )
                  )}
                </div>

                {buildPicoQuery() && (
                  <div className="p-4 rounded-lg bg-muted/50 border animate-fade-in">
                    <p className="text-sm font-medium mb-2 flex items-center gap-2">
                      <ArrowRight className="h-4 w-4 text-primary" />
                      Generated Query
                    </p>
                    <pre className="text-sm text-muted-foreground whitespace-pre-line font-sans">
                      {buildPicoQuery()}
                    </pre>
                  </div>
                )}
              </TabsContent>

              {/* PCC Framework */}
              <TabsContent value="pcc" className="space-y-6 mt-6">
                <div className="flex items-start gap-3 p-4 rounded-lg bg-pico-c/5 border border-pico-c/20">
                  <FileText className="h-5 w-5 text-pico-c mt-0.5" />
                  <div>
                    <p className="font-medium text-sm">PCC Framework</p>
                    <p className="text-sm text-muted-foreground">
                      Best for scoping reviews, qualitative research, or
                      exploratory questions
                    </p>
                  </div>
                </div>

                <div className="space-y-5">
                  {pccFields.map((field) =>
                    renderField(
                      field,
                      pccValues[field.id as keyof typeof pccValues],
                      (value) =>
                        setPccValues((prev) => ({ ...prev, [field.id]: value }))
                    )
                  )}
                </div>

                {buildPccQuery() && (
                  <div className="p-4 rounded-lg bg-muted/50 border animate-fade-in">
                    <p className="text-sm font-medium mb-2 flex items-center gap-2">
                      <ArrowRight className="h-4 w-4 text-primary" />
                      Generated Query
                    </p>
                    <pre className="text-sm text-muted-foreground whitespace-pre-line font-sans">
                      {buildPccQuery()}
                    </pre>
                  </div>
                )}
              </TabsContent>

              {/* Free-form Query */}
              <TabsContent value="free" className="space-y-6 mt-6">
                <div className="flex items-start gap-3 p-4 rounded-lg bg-accent/5 border border-accent/20">
                  <Sparkles className="h-5 w-5 text-accent mt-0.5" />
                  <div>
                    <p className="font-medium text-sm">Free-form Query</p>
                    <p className="text-sm text-muted-foreground">
                      Enter your research question in natural language. The agent
                      will determine the best search strategy.
                    </p>
                  </div>
                </div>

                <div>
                  <Label htmlFor="free-query" className="mb-2 block">
                    Research Question
                  </Label>
                  <Textarea
                    id="free-query"
                    placeholder="Enter your research question, e.g., 'What is the effectiveness of metformin vs SGLT2 inhibitors for type 2 diabetes cardiovascular outcomes?'"
                    value={freeQuery}
                    onChange={(e) => setFreeQuery(e.target.value)}
                    rows={5}
                    className="resize-none transition-shadow focus:shadow-md focus:shadow-primary/10"
                  />
                </div>
              </TabsContent>
            </Tabs>

            {/* Error Display */}
            {startResearch.error && (
              <div className="flex items-start gap-3 p-4 rounded-lg bg-destructive/10 border border-destructive/20 animate-fade-in">
                <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
                <div>
                  <p className="font-medium text-sm text-destructive">
                    Error starting research
                  </p>
                  <p className="text-sm text-destructive/80">
                    {startResearch.error.message}
                  </p>
                </div>
              </div>
            )}

            {/* Submit Button */}
            <Button
              type="submit"
              className="w-full h-12 text-base shadow-lg shadow-primary/20"
              size="lg"
              disabled={startResearch.isPending || !isValid()}
            >
              {startResearch.isPending ? (
                <>
                  <Loader2 className="h-5 w-5 mr-2 animate-spin" />
                  Starting Research...
                </>
              ) : (
                <>
                  <Search className="h-5 w-5 mr-2" />
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
