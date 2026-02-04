"use client";

import ReactMarkdown from "react-markdown";
import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlanningSteps } from "./PlanningSteps";
import { AgentStatus } from "./AgentStatus";
import { ToolLog } from "./ToolLog";
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
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2 font-serif">
          <BookOpen className="h-5 w-5 text-pico-p" />
          PICO Query
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {fields.map((field) => {
            const value =
              picoQuery[field.key as keyof typeof picoQuery] as string;
            if (!value && field.key === "comparison") return null;
            const Icon = field.icon;
            return (
              <div key={field.key} className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn("text-xs font-bold border", field.colorClass)}
                  >
                    {field.shortLabel}
                  </Badge>
                  <span className="text-sm font-medium text-muted-foreground">
                    {field.label}
                  </span>
                </div>
                <p className="text-sm pl-1">{value || "Not specified"}</p>
              </div>
            );
          })}
        </div>

        {picoQuery.generatedPubmedQuery && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium text-muted-foreground mb-2">
              Generated PubMed Query
            </p>
            <code className="text-xs bg-muted p-3 rounded-lg block overflow-x-auto">
              {picoQuery.generatedPubmedQuery}
            </code>
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
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2 font-serif">
          <FileText className="h-5 w-5 text-pico-c" />
          PCC Query
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {fields.map((field) => {
            const value =
              pccQuery[field.key as keyof typeof pccQuery] as string;
            return (
              <div key={field.key} className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn("text-xs font-bold border", field.colorClass)}
                  >
                    {field.shortLabel}
                  </Badge>
                  <span className="text-sm font-medium text-muted-foreground">
                    {field.label}
                  </span>
                </div>
                <p className="text-sm pl-1">{value || "Not specified"}</p>
              </div>
            );
          })}
        </div>

        {pccQuery.generatedQuery && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium text-muted-foreground mb-2">
              Generated Query
            </p>
            <code className="text-xs bg-muted p-3 rounded-lg block overflow-x-auto">
              {pccQuery.generatedQuery}
            </code>
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
    <div className="space-y-6 fade-in-stagger">
      {/* Query and Status Header */}
      <Card
        className={cn(
          "overflow-hidden border-l-4",
          data.status === "completed" && "border-l-status-completed",
          data.status === "running" && "border-l-status-running",
          data.status === "failed" && "border-l-status-failed",
          data.status === "pending" && "border-l-status-pending"
        )}
      >
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-3">
                <QueryTypeBadge type={data.queryType} />
                <StatusBadge status={data.status} />
              </div>
              <CardTitle className="text-xl font-serif leading-relaxed">
                {data.query}
              </CardTitle>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-sm text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5" />
                  Created: {formatDate(data.createdAt)}
                </span>
                {data.completedAt && (
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Completed: {formatDate(data.completedAt)}
                  </span>
                )}
                {data.durationSeconds && (
                  <span>Duration: {Math.round(data.durationSeconds)}s</span>
                )}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">
                {data.phase ? `Phase: ${data.phase}` : "Progress"}
              </span>
              <span className="font-medium">{data.progress}%</span>
            </div>
            <Progress
              value={data.progress}
              className={cn(
                "h-2",
                data.status === "running" && "progress-animated"
              )}
            />
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
        <Card className="border-destructive/50 bg-destructive/5">
          <CardHeader>
            <CardTitle className="text-lg text-destructive flex items-center gap-2">
              <AlertCircle className="h-5 w-5" />
              Error
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-sm text-destructive whitespace-pre-wrap font-mono">
              {data.error || data.errorMessage}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Results Display */}
      {data.status === "completed" && (data.result || data.report) && (
        <Card>
          <CardHeader className="border-b bg-gradient-to-r from-status-completed/5 to-transparent">
            <CardTitle className="text-lg flex items-center gap-2 font-serif">
              <FileText className="h-5 w-5 text-status-completed" />
              Research Report
              {data.report && (
                <span className="text-sm font-normal text-muted-foreground font-sans">
                  ({data.report.wordCount} words, {data.report.referenceCount}{" "}
                  references)
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <Tabs defaultValue="formatted">
              <TabsList>
                <TabsTrigger value="formatted">Formatted</TabsTrigger>
                <TabsTrigger value="raw">Raw Markdown</TabsTrigger>
              </TabsList>
              <TabsContent value="formatted" className="mt-6">
                <div className="prose-medical">
                  <ReactMarkdown>
                    {data.result || data.report?.content || ""}
                  </ReactMarkdown>
                </div>
              </TabsContent>
              <TabsContent value="raw" className="mt-6">
                <pre className="whitespace-pre-wrap font-mono text-xs bg-muted p-4 rounded-lg overflow-auto max-h-[600px] border">
                  {data.result || data.report?.content}
                </pre>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      )}

      {/* Search Results Summary */}
      {data.searchResultsCount !== undefined && data.searchResultsCount > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2 font-serif">
              <Database className="h-5 w-5 text-primary" />
              Search Results
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-3">
              <div className="p-3 bg-primary/10 rounded-lg">
                <span className="text-2xl font-bold text-primary">
                  {data.searchResultsCount}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">
                articles retrieved from medical databases
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
