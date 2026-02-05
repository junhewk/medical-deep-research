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
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslations } from "@/i18n/client";

type QueryType = "pico" | "pcc" | "free";

interface FieldConfig {
  id: string;
  labelKey: string;
  shortLabelKey: string;
  placeholderKey: string;
  helpKey: string;
  icon: typeof Users;
  colorClass: string;
  optional?: boolean;
}

const picoFields: FieldConfig[] = [
  {
    id: "population",
    labelKey: "pico.population.label",
    shortLabelKey: "pico.population.short",
    placeholderKey: "pico.population.placeholder",
    helpKey: "pico.population.help",
    icon: Users,
    colorClass: "pico-population",
  },
  {
    id: "intervention",
    labelKey: "pico.intervention.label",
    shortLabelKey: "pico.intervention.short",
    placeholderKey: "pico.intervention.placeholder",
    helpKey: "pico.intervention.help",
    icon: Syringe,
    colorClass: "pico-intervention",
  },
  {
    id: "comparison",
    labelKey: "pico.comparison.label",
    shortLabelKey: "pico.comparison.short",
    placeholderKey: "pico.comparison.placeholder",
    helpKey: "pico.comparison.help",
    icon: GitCompare,
    colorClass: "pico-comparison",
    optional: true,
  },
  {
    id: "outcome",
    labelKey: "pico.outcome.label",
    shortLabelKey: "pico.outcome.short",
    placeholderKey: "pico.outcome.placeholder",
    helpKey: "pico.outcome.help",
    icon: Target,
    colorClass: "pico-outcome",
  },
];

const pccFields: FieldConfig[] = [
  {
    id: "population",
    labelKey: "pcc.population.label",
    shortLabelKey: "pcc.population.short",
    placeholderKey: "pcc.population.placeholder",
    helpKey: "pcc.population.help",
    icon: Users,
    colorClass: "pico-population",
  },
  {
    id: "concept",
    labelKey: "pcc.concept.label",
    shortLabelKey: "pcc.concept.short",
    placeholderKey: "pcc.concept.placeholder",
    helpKey: "pcc.concept.help",
    icon: Lightbulb,
    colorClass: "pico-comparison",
  },
  {
    id: "context",
    labelKey: "pcc.context.label",
    shortLabelKey: "pcc.context.short",
    placeholderKey: "pcc.context.placeholder",
    helpKey: "pcc.context.help",
    icon: MapPin,
    colorClass: "pico-outcome",
  },
];

export default function NewResearchPage() {
  const router = useRouter();
  const startResearch = useStartResearch();
  const { t } = useTranslations();

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
            {t(field.shortLabelKey)}
          </Badge>
          <span className="font-medium">{t(field.labelKey)}</span>
          {field.optional && (
            <span className="text-xs text-muted-foreground">({t("common.optional")})</span>
          )}
        </Label>
        <div className="relative">
          <Icon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors" />
          <Input
            id={`field-${field.id}`}
            placeholder={t(field.placeholderKey)}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="pl-10 transition-shadow focus:shadow-md focus:shadow-primary/10"
          />
        </div>
        <p className="text-xs text-muted-foreground mt-1.5 ml-1">
          {t(field.helpKey)}
        </p>
      </div>
    );
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8 stagger-fade">
      {/* Header */}
      <div className="text-center space-y-3">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 text-primary text-sm font-medium">
          <Sparkles className="h-3.5 w-3.5" />
          {t("research.newResearch")}
        </div>
        <h1 className="font-serif text-3xl sm:text-4xl tracking-tight">
          {t("newResearch.title")}
        </h1>
        <p className="text-muted-foreground max-w-md mx-auto">
          {t("newResearch.description")}
        </p>
      </div>

      {/* Main Card */}
      <Card className="overflow-hidden card-hover">
        <CardHeader className="bg-gradient-to-br from-primary/5 via-transparent to-accent/5 border-b border-border/50">
          <CardTitle className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-primary/10">
              <Search className="h-4 w-4 text-primary" />
            </div>
            {t("newResearch.framework")}
          </CardTitle>
          <CardDescription>
            {t("newResearch.frameworkDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-6">
            <Tabs
              value={queryType}
              onValueChange={(v) => setQueryType(v as QueryType)}
            >
              <TabsList className="grid w-full grid-cols-3 h-auto p-1.5 bg-muted/50">
                <TabsTrigger
                  value="pico"
                  className="flex items-center gap-2 py-3 rounded-lg transition-all data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-[hsl(var(--pico-p))] dark:data-[state=active]:bg-card"
                >
                  <BookOpen className="h-4 w-4" />
                  <span className="hidden sm:inline font-medium">PICO</span>
                </TabsTrigger>
                <TabsTrigger
                  value="pcc"
                  className="flex items-center gap-2 py-3 rounded-lg transition-all data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-[hsl(var(--pico-c))] dark:data-[state=active]:bg-card"
                >
                  <FileText className="h-4 w-4" />
                  <span className="hidden sm:inline font-medium">PCC</span>
                </TabsTrigger>
                <TabsTrigger
                  value="free"
                  className="flex items-center gap-2 py-3 rounded-lg transition-all data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-accent dark:data-[state=active]:bg-card"
                >
                  <Sparkles className="h-4 w-4" />
                  <span className="hidden sm:inline font-medium">{t("newResearch.freeForm")}</span>
                </TabsTrigger>
              </TabsList>

              {/* PICO Framework */}
              <TabsContent value="pico" className="space-y-6 mt-6">
                <div className="flex items-start gap-4 p-4 rounded-xl bg-gradient-to-br from-[hsl(var(--pico-p))]/8 to-transparent border border-[hsl(var(--pico-p))]/15">
                  <div className="p-2 rounded-lg bg-[hsl(var(--pico-p))]/15">
                    <BookOpen className="h-5 w-5 text-[hsl(var(--pico-p))]" />
                  </div>
                  <div>
                    <p className="font-serif font-medium">{t("newResearch.picoFramework")}</p>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      {t("newResearch.picoDescription")}
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
              </TabsContent>

              {/* PCC Framework */}
              <TabsContent value="pcc" className="space-y-6 mt-6">
                <div className="flex items-start gap-4 p-4 rounded-xl bg-gradient-to-br from-[hsl(var(--pico-c))]/8 to-transparent border border-[hsl(var(--pico-c))]/15">
                  <div className="p-2 rounded-lg bg-[hsl(var(--pico-c))]/15">
                    <FileText className="h-5 w-5 text-[hsl(var(--pico-c))]" />
                  </div>
                  <div>
                    <p className="font-serif font-medium">{t("newResearch.pccFramework")}</p>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      {t("newResearch.pccDescription")}
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
              </TabsContent>

              {/* Free-form Query */}
              <TabsContent value="free" className="space-y-6 mt-6">
                <div className="flex items-start gap-4 p-4 rounded-xl bg-gradient-to-br from-accent/10 to-transparent border border-accent/15">
                  <div className="p-2 rounded-lg bg-accent/15">
                    <Sparkles className="h-5 w-5 text-accent" />
                  </div>
                  <div>
                    <p className="font-serif font-medium">{t("newResearch.freeForm")}</p>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      {t("newResearch.freeFormDescription")}
                    </p>
                  </div>
                </div>

                <div>
                  <Label htmlFor="free-query" className="mb-2 block">
                    {t("newResearch.researchQuestion")}
                  </Label>
                  <Textarea
                    id="free-query"
                    placeholder={t("newResearch.freeFormPlaceholder")}
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
                    {t("newResearch.errorStarting")}
                  </p>
                  <p className="text-sm text-destructive/80">
                    {startResearch.error.message}
                  </p>
                </div>
              </div>
            )}

            {/* Submit Button */}
            <div className="pt-2">
              <Button
                type="submit"
                className="w-full h-12 text-base font-medium shadow-lg shadow-primary/25 bg-gradient-to-r from-primary to-primary/90 hover:from-primary/90 hover:to-primary"
                size="lg"
                disabled={startResearch.isPending || !isValid()}
              >
                {startResearch.isPending ? (
                  <>
                    <Loader2 className="h-5 w-5 mr-2 animate-spin" />
                    {t("newResearch.startingResearch")}
                  </>
                ) : (
                  <>
                    <Search className="h-5 w-5 mr-2" />
                    {t("newResearch.startResearch")}
                  </>
                )}
              </Button>
              <p className="text-center text-xs text-muted-foreground mt-3">
                {t("newResearch.databaseNote")}
              </p>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
