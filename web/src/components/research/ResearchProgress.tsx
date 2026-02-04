"use client";

import ReactMarkdown from "react-markdown";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlanningSteps } from "./PlanningSteps";
import { AgentStatus } from "./AgentStatus";
import { ToolLog } from "./ToolLog";
import { QueryDisplayInline } from "./QueryDisplay";
import type { ResearchProgress as ResearchProgressType } from "@/lib/research";
import {
  FileText,
  Database,
  Clock,
  BookOpen,
  AlertCircle,
  Users,
  Syringe,
  GitCompare,
  Target,
  Lightbulb,
  MapPin,
  Sparkles,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ResearchProgressProps {
  data: ResearchProgressType;
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<
    string,
    { className: string; label: string; icon: typeof CheckCircle2 }
  > = {
    pending: {
      className: "status-pending",
      label: "Pending",
      icon: Clock,
    },
    running: {
      className: "status-running",
      label: "Running",
      icon: Loader2,
    },
    completed: {
      className: "status-completed",
      label: "Completed",
      icon: CheckCircle2,
    },
    failed: {
      className: "status-failed",
      label: "Failed",
      icon: XCircle,
    },
    cancelled: {
      className: "status-pending",
      label: "Cancelled",
      icon: XCircle,
    },
  };

  const { className, label, icon: Icon } = config[status] || config.pending;

  return (
    <Badge
      variant="outline"
      className={cn(className, "border font-medium gap-1.5")}
    >
      <Icon
        className={cn("h-3 w-3", status === "running" && "animate-spin")}
      />
      {label}
    </Badge>
  );
}

function QueryTypeBadge({ type }: { type?: string }) {
  if (!type) return null;

  const config: Record<string, { icon: typeof BookOpen; color: string }> = {
    pico: {
      icon: BookOpen,
      color: "text-pico-p border-pico-p/30 bg-pico-p/10",
    },
    pcc: { icon: FileText, color: "text-pico-c border-pico-c/30 bg-pico-c/10" },
    free: {
      icon: Sparkles,
      color: "text-accent border-accent/30 bg-accent/10",
    },
  };

  const { icon: Icon, color } = config[type] || config.free;

  return (
    <Badge variant="outline" className={cn("text-xs font-medium border", color)}>
      <Icon className="h-3 w-3 mr-1" />
      {type.toUpperCase()}
    </Badge>
  );
}

function PicoDisplay({
  picoQuery,
}: {
  picoQuery: ResearchProgressType["picoQuery"];
}) {
  if (!picoQuery) return null;

  const fields = [
    {
      key: "population",
      label: "Population",
      shortLabel: "P",
      icon: Users,
      colorClass: "pico-population",
    },
    {
      key: "intervention",
      label: "Intervention",
      shortLabel: "I",
      icon: Syringe,
      colorClass: "pico-intervention",
    },
    {
      key: "comparison",
      label: "Comparison",
      shortLabel: "C",
      icon: GitCompare,
      colorClass: "pico-comparison",
    },
    {
      key: "outcome",
      label: "Outcome",
      shortLabel: "O",
      icon: Target,
      colorClass: "pico-outcome",
    },
  ];

  return (
    <Card className="card-hover">
      <CardHeader className="border-b border-border/50 bg-gradient-to-r from-[hsl(var(--pico-p))]/5 to-transparent">
        <CardTitle className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[hsl(var(--pico-p))]/10">
            <BookOpen className="h-4 w-4 text-[hsl(var(--pico-p))]" />
          </div>
          PICO Query
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {fields.map((field) => {
            const value =
              picoQuery[field.key as keyof typeof picoQuery] as string;
            if (!value && field.key === "comparison") return null;
            return (
              <div key={field.key} className="p-3 rounded-lg bg-muted/30 space-y-1.5">
                <div className="flex items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn("text-xs font-bold border", field.colorClass)}
                  >
                    {field.shortLabel}
                  </Badge>
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {field.label}
                  </span>
                </div>
                <p className="text-sm font-medium">{value || "Not specified"}</p>
              </div>
            );
          })}
        </div>

        {picoQuery.generatedPubmedQuery && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium text-muted-foreground mb-2">
              Generated PubMed Query
            </p>
            <QueryDisplayInline query={picoQuery.generatedPubmedQuery} />
          </div>
        )}

        {picoQuery.meshTerms && picoQuery.meshTerms.length > 0 && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium text-muted-foreground mb-2">
              MeSH Terms
            </p>
            <div className="flex flex-wrap gap-1.5">
              {picoQuery.meshTerms.map((term, i) => (
                <Badge
                  key={i}
                  variant="secondary"
                  className="text-xs font-normal"
                >
                  {term}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PccDisplay({
  pccQuery,
}: {
  pccQuery: ResearchProgressType["pccQuery"];
}) {
  if (!pccQuery) return null;

  const fields = [
    {
      key: "population",
      label: "Population",
      shortLabel: "P",
      icon: Users,
      colorClass: "pico-population",
    },
    {
      key: "concept",
      label: "Concept",
      shortLabel: "C",
      icon: Lightbulb,
      colorClass: "pico-comparison",
    },
    {
      key: "context",
      label: "Context",
      shortLabel: "C",
      icon: MapPin,
      colorClass: "pico-outcome",
    },
  ];

  return (
    <Card className="card-hover">
      <CardHeader className="border-b border-border/50 bg-gradient-to-r from-[hsl(var(--pico-c))]/5 to-transparent">
        <CardTitle className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[hsl(var(--pico-c))]/10">
            <FileText className="h-4 w-4 text-[hsl(var(--pico-c))]" />
          </div>
          PCC Query
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {fields.map((field) => {
            const value =
              pccQuery[field.key as keyof typeof pccQuery] as string;
            return (
              <div key={field.key} className="p-3 rounded-lg bg-muted/30 space-y-1.5">
                <div className="flex items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn("text-xs font-bold border", field.colorClass)}
                  >
                    {field.shortLabel}
                  </Badge>
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {field.label}
                  </span>
                </div>
                <p className="text-sm font-medium">{value || "Not specified"}</p>
              </div>
            );
          })}
        </div>

        {pccQuery.generatedQuery && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium text-muted-foreground mb-2">
              Generated Query
            </p>
            <QueryDisplayInline query={pccQuery.generatedQuery} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ResearchProgressView({ data }: ResearchProgressProps) {
  const formatDate = (date?: string) => {
    if (!date) return "N/A";
    return new Date(date).toLocaleString();
  };

  return (
    <div className="space-y-6 stagger-fade">
      {/* Query and Status Header */}
      <Card
        className={cn(
          "overflow-hidden border-l-4 relative",
          data.status === "completed" && "border-l-[hsl(var(--status-completed))]",
          data.status === "running" && "border-l-[hsl(var(--status-running))]",
          data.status === "failed" && "border-l-[hsl(var(--status-failed))]",
          data.status === "pending" && "border-l-[hsl(var(--status-pending))]"
        )}
      >
        {data.status === "running" && (
          <div className="absolute inset-0 bg-gradient-to-r from-[hsl(var(--status-running))]/5 to-transparent pointer-events-none" />
        )}
        <CardHeader className="relative">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <QueryTypeBadge type={data.queryType} />
                <StatusBadge status={data.status} />
              </div>
              <CardTitle className="text-xl sm:text-2xl leading-relaxed">
                {data.query}
              </CardTitle>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-4 text-sm text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5" />
                  {formatDate(data.createdAt)}
                </span>
                {data.completedAt && (
                  <span className="flex items-center gap-1.5 text-[hsl(var(--status-completed))]">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Completed {formatDate(data.completedAt)}
                  </span>
                )}
                {data.durationSeconds && (
                  <span className="px-2 py-0.5 rounded-full bg-muted text-xs">
                    {Math.round(data.durationSeconds)}s
                  </span>
                )}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="relative">
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground font-medium">
                {data.phase ? data.phase.charAt(0).toUpperCase() + data.phase.slice(1) : "Progress"}
              </span>
              <span className="font-semibold text-foreground">{data.progress}%</span>
            </div>
            <div className="relative">
              <Progress
                value={data.progress}
                className={cn(
                  "h-2.5 rounded-full",
                  data.status === "running" && "progress-shimmer"
                )}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* PICO/PCC Query Display */}
      {data.picoQuery && <PicoDisplay picoQuery={data.picoQuery} />}
      {data.pccQuery && <PccDisplay pccQuery={data.pccQuery} />}

      {/* Progress Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PlanningSteps steps={data.planning_steps || []} />
        <AgentStatus agents={data.active_agents || []} phase={data.phase} />
      </div>

      {/* Tool Log */}
      <ToolLog executions={data.tool_executions || []} />

      {/* Error Display */}
      {(data.error || data.errorMessage) && (
        <Card className="border-destructive/30 bg-gradient-to-br from-destructive/5 to-transparent overflow-hidden">
          <CardHeader className="border-b border-destructive/20">
            <CardTitle className="text-destructive flex items-center gap-3">
              <div className="p-2 rounded-lg bg-destructive/10">
                <AlertCircle className="h-4 w-4" />
              </div>
              Error Occurred
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <pre className="text-sm text-destructive/90 whitespace-pre-wrap font-mono p-4 rounded-lg bg-destructive/5 border border-destructive/10">
              {data.error || data.errorMessage}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Results Display */}
      {data.status === "completed" && (data.result || data.report) && (
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border/50 bg-gradient-to-br from-[hsl(var(--status-completed))]/8 via-transparent to-[hsl(var(--pico-i))]/5">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-[hsl(var(--status-completed))]/15">
                  <FileText className="h-4 w-4 text-[hsl(var(--status-completed))]" />
                </div>
                Research Report
              </CardTitle>
              {data.report && (
                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                  <span className="px-2 py-1 rounded-md bg-muted">
                    {(data.report.wordCount ?? 0).toLocaleString()} words
                  </span>
                  <span className="px-2 py-1 rounded-md bg-muted">
                    {data.report.referenceCount ?? 0} refs
                  </span>
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            <Tabs defaultValue="formatted">
              <TabsList className="bg-muted/50">
                <TabsTrigger value="formatted" className="data-[state=active]:bg-background">
                  Formatted
                </TabsTrigger>
                <TabsTrigger value="raw" className="data-[state=active]:bg-background">
                  Raw Markdown
                </TabsTrigger>
              </TabsList>
              <TabsContent value="formatted" className="mt-6">
                <div className="prose-medical">
                  <ReactMarkdown>
                    {data.result || data.report?.content || ""}
                  </ReactMarkdown>
                </div>
              </TabsContent>
              <TabsContent value="raw" className="mt-6">
                <pre className="whitespace-pre-wrap font-mono text-xs bg-muted/50 p-4 rounded-xl overflow-auto max-h-[600px] border border-border/50">
                  {data.result || data.report?.content}
                </pre>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      )}

      {/* Search Results Summary */}
      {data.searchResultsCount !== undefined && data.searchResultsCount > 0 && (
        <Card className="card-hover">
          <CardHeader className="border-b border-border/50">
            <CardTitle className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10">
                <Database className="h-4 w-4 text-primary" />
              </div>
              Search Results
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <div className="p-4 bg-gradient-to-br from-primary/15 to-primary/5 rounded-xl border border-primary/10">
                <span className="text-3xl font-bold text-primary">
                  {data.searchResultsCount}
                </span>
              </div>
              <div>
                <p className="font-medium">Articles Retrieved</p>
                <p className="text-sm text-muted-foreground">
                  From PubMed, Scopus, and Cochrane databases
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
