"use client";

import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlanningSteps } from "./PlanningSteps";
import { AgentStatus } from "./AgentStatus";
import { ToolLog } from "./ToolLog";
import type { ResearchProgress as ResearchProgressType } from "@/lib/research";
import { FileText, Database, Clock, BookOpen, AlertCircle } from "lucide-react";

interface ResearchProgressProps {
  data: ResearchProgressType;
}

export function ResearchProgressView({ data }: ResearchProgressProps) {
  const statusColors: Record<string, "secondary" | "default" | "destructive"> = {
    pending: "secondary",
    running: "default",
    completed: "secondary",
    failed: "destructive",
    cancelled: "secondary",
  };

  const formatDate = (date?: string) => {
    if (!date) return "N/A";
    return new Date(date).toLocaleString();
  };

  return (
    <div className="space-y-4">
      {/* Query and Status Header */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                {data.queryType && (
                  <Badge variant="outline" className="text-xs">
                    {data.queryType.toUpperCase()}
                  </Badge>
                )}
                <Badge variant={statusColors[data.status] || "secondary"}>
                  {data.status.charAt(0).toUpperCase() + data.status.slice(1)}
                </Badge>
              </div>
              <CardTitle className="text-lg">{data.query}</CardTitle>
              <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Created: {formatDate(data.createdAt)}
                </span>
                {data.completedAt && (
                  <span className="flex items-center gap-1">
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
            <Progress value={data.progress} className="h-2" />
          </div>
        </CardContent>
      </Card>

      {/* PICO/PCC Query Display */}
      {(data.picoQuery || data.pccQuery) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <BookOpen className="h-5 w-5" />
              {data.picoQuery ? "PICO Query" : "PCC Query"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.picoQuery && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Population</p>
                  <p className="text-sm">{data.picoQuery.population || "Not specified"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Intervention</p>
                  <p className="text-sm">{data.picoQuery.intervention || "Not specified"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Comparison</p>
                  <p className="text-sm">{data.picoQuery.comparison || "Not specified"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Outcome</p>
                  <p className="text-sm">{data.picoQuery.outcome || "Not specified"}</p>
                </div>
                {data.picoQuery.generatedPubmedQuery && (
                  <div className="col-span-2 mt-2">
                    <p className="text-sm font-medium text-muted-foreground">Generated PubMed Query</p>
                    <code className="text-xs bg-muted p-2 rounded block mt-1">
                      {data.picoQuery.generatedPubmedQuery}
                    </code>
                  </div>
                )}
                {data.picoQuery.meshTerms && data.picoQuery.meshTerms.length > 0 && (
                  <div className="col-span-2">
                    <p className="text-sm font-medium text-muted-foreground">MeSH Terms</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {data.picoQuery.meshTerms.map((term, i) => (
                        <Badge key={i} variant="outline" className="text-xs">
                          {term}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {data.pccQuery && (
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Population</p>
                  <p className="text-sm">{data.pccQuery.population || "Not specified"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Concept</p>
                  <p className="text-sm">{data.pccQuery.concept || "Not specified"}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Context</p>
                  <p className="text-sm">{data.pccQuery.context || "Not specified"}</p>
                </div>
                {data.pccQuery.generatedQuery && (
                  <div className="col-span-3 mt-2">
                    <p className="text-sm font-medium text-muted-foreground">Generated Query</p>
                    <code className="text-xs bg-muted p-2 rounded block mt-1">
                      {data.pccQuery.generatedQuery}
                    </code>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Progress Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PlanningSteps steps={data.planning_steps || []} />
        <AgentStatus agents={data.active_agents || []} phase={data.phase} />
      </div>

      {/* Tool Log */}
      <ToolLog executions={data.tool_executions || []} />

      {/* Error Display */}
      {(data.error || data.errorMessage) && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-lg text-destructive flex items-center gap-2">
              <AlertCircle className="h-5 w-5" />
              Error
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-sm text-destructive whitespace-pre-wrap">
              {data.error || data.errorMessage}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Results Display */}
      {data.status === "completed" && (data.result || data.report) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Research Report
              {data.report && (
                <span className="text-sm font-normal text-muted-foreground">
                  ({data.report.wordCount} words, {data.report.referenceCount} references)
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="formatted">
              <TabsList>
                <TabsTrigger value="formatted">Formatted</TabsTrigger>
                <TabsTrigger value="raw">Raw Markdown</TabsTrigger>
              </TabsList>
              <TabsContent value="formatted" className="mt-4">
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <div
                    dangerouslySetInnerHTML={{
                      __html: simpleMarkdownToHtml(data.result || data.report?.content || ""),
                    }}
                  />
                </div>
              </TabsContent>
              <TabsContent value="raw" className="mt-4">
                <pre className="whitespace-pre-wrap font-mono text-xs bg-muted p-4 rounded-lg overflow-auto max-h-[600px]">
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
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="h-5 w-5" />
              Search Results
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Found {data.searchResultsCount} articles from medical databases.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// Simple markdown to HTML converter (basic implementation)
function simpleMarkdownToHtml(markdown: string): string {
  let html = markdown
    // Headers
    .replace(/^### (.*$)/gim, "<h3>$1</h3>")
    .replace(/^## (.*$)/gim, "<h2>$1</h2>")
    .replace(/^# (.*$)/gim, "<h1>$1</h1>")
    // Bold
    .replace(/\*\*(.*?)\*\*/gim, "<strong>$1</strong>")
    // Italic
    .replace(/\*(.*?)\*/gim, "<em>$1</em>")
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/gim, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    // Unordered lists
    .replace(/^\s*[-*]\s+(.*$)/gim, "<li>$1</li>")
    // Ordered lists
    .replace(/^\s*\d+\.\s+(.*$)/gim, "<li>$1</li>")
    // Line breaks
    .replace(/\n\n/g, "</p><p>")
    // Code blocks
    .replace(/```([\s\S]*?)```/gim, "<pre><code>$1</code></pre>")
    // Inline code
    .replace(/`([^`]+)`/gim, "<code>$1</code>")
    // Horizontal rules
    .replace(/^---$/gim, "<hr />");

  // Wrap in paragraphs
  html = "<p>" + html + "</p>";

  // Fix list items
  html = html.replace(/<\/li>\s*<li>/g, "</li><li>");
  html = html.replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>");
  html = html.replace(/<\/ul>\s*<ul>/g, "");

  return html;
}
