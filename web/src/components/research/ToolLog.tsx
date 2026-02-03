"use client";

import { cn } from "@/lib/utils";
import type { ToolExecution } from "@/lib/research";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Terminal, CheckCircle, Loader2, XCircle } from "lucide-react";

interface ToolLogProps {
  executions: ToolExecution[];
}

export function ToolLog({ executions }: ToolLogProps) {
  if (!executions || executions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Terminal className="h-5 w-5" />
            Tool Execution Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            No tool executions yet...
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Terminal className="h-5 w-5" />
          Tool Execution Log
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {executions.map((exec, index) => (
            <div
              key={index}
              className={cn(
                "flex items-start gap-3 p-2 rounded font-mono text-sm",
                exec.status === "running" && "bg-blue-50",
                exec.status === "completed" && "bg-green-50/50",
                exec.status === "failed" && "bg-red-50"
              )}
            >
              <div className="flex-shrink-0 mt-0.5">
                {exec.status === "running" && (
                  <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
                )}
                {exec.status === "completed" && (
                  <CheckCircle className="h-4 w-4 text-green-500" />
                )}
                {exec.status === "failed" && (
                  <XCircle className="h-4 w-4 text-red-500" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className="text-xs">
                    {exec.tool}
                  </Badge>
                  {exec.duration && (
                    <span className="text-xs text-muted-foreground">
                      ({exec.duration.toFixed(1)}s)
                    </span>
                  )}
                </div>
                {exec.query && (
                  <p className="text-xs text-muted-foreground mt-1 truncate">
                    {exec.query}
                  </p>
                )}
                {exec.error && (
                  <p className="text-xs text-red-600 mt-1">{exec.error}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
