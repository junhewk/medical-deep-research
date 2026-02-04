"use client";

import { cn } from "@/lib/utils";
import type { ToolExecution } from "@/lib/research";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Terminal,
  CheckCircle,
  Loader2,
  XCircle,
  Clock,
  Search,
  Database,
  FileText,
} from "lucide-react";

interface ToolLogProps {
  executions: ToolExecution[];
}

const toolIcons: Record<string, typeof Search> = {
  pubmed_search: Database,
  scopus_search: Database,
  cochrane_search: Database,
  mesh_mapping: FileText,
  pico_query: Search,
  web_search: Search,
};

export function ToolLog({ executions }: ToolLogProps) {
  if (!executions || executions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2 font-serif">
            <Terminal className="h-5 w-5 text-primary" />
            Tool Execution Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 p-4 rounded-lg bg-muted/30 border border-dashed">
            <Clock className="h-5 w-5 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">
              Waiting for tool executions...
            </span>
          </div>
        </CardContent>
      </Card>
    );
  }

  const completedCount = executions.filter((e) => e.status === "completed").length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2 font-serif">
          <Terminal className="h-5 w-5 text-primary" />
          Tool Execution Log
          <span className="text-sm font-normal text-muted-foreground font-sans ml-auto">
            {completedCount}/{executions.length} completed
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
          {executions.map((exec, index) => {
            const ToolIcon = toolIcons[exec.tool] || Terminal;
            return (
              <div
                key={index}
                className={cn(
                  "flex items-start gap-3 p-3 rounded-lg border transition-all duration-200",
                  exec.status === "running" &&
                    "bg-status-running/5 border-status-running/20",
                  exec.status === "completed" &&
                    "bg-muted/30 border-transparent",
                  exec.status === "failed" &&
                    "bg-status-failed/5 border-status-failed/20"
                )}
              >
                <div
                  className={cn(
                    "flex-shrink-0 p-1.5 rounded-md mt-0.5",
                    exec.status === "running" && "bg-status-running/10",
                    exec.status === "completed" && "bg-status-completed/10",
                    exec.status === "failed" && "bg-status-failed/10"
                  )}
                >
                  {exec.status === "running" ? (
                    <Loader2 className="h-4 w-4 text-status-running animate-spin" />
                  ) : exec.status === "completed" ? (
                    <CheckCircle className="h-4 w-4 text-status-completed" />
                  ) : exec.status === "failed" ? (
                    <XCircle className="h-4 w-4 text-status-failed" />
                  ) : (
                    <ToolIcon className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge
                      variant="outline"
                      className="text-xs font-mono bg-background"
                    >
                      {exec.tool}
                    </Badge>
                    {exec.duration !== undefined && (
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {exec.duration.toFixed(1)}s
                      </span>
                    )}
                  </div>
                  {exec.query && (
                    <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">
                      {exec.query}
                    </p>
                  )}
                  {exec.error && (
                    <p className="text-xs text-status-failed mt-1.5 font-medium">
                      {exec.error}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
