"use client";

import { Progress } from "@/components/ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PlanningSteps } from "./PlanningSteps";
import { AgentStatus } from "./AgentStatus";
import { ToolLog } from "./ToolLog";
import type { ResearchProgress as ResearchProgressType } from "@/lib/research";

interface ResearchProgressProps {
  data: ResearchProgressType;
}

export function ResearchProgressView({ data }: ResearchProgressProps) {
  const statusColors = {
    pending: "secondary",
    running: "default",
    completed: "success",
    failed: "destructive",
  } as const;

  return (
    <div className="space-y-4">
      {/* Query and Status Header */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <CardTitle className="text-lg">{data.query}</CardTitle>
            </div>
            <Badge variant={statusColors[data.status] || "secondary"}>
              {data.status.charAt(0).toUpperCase() + data.status.slice(1)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Progress</span>
              <span className="font-medium">{data.progress}%</span>
            </div>
            <Progress value={data.progress} className="h-2" />
          </div>
        </CardContent>
      </Card>

      {/* Progress Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PlanningSteps steps={data.planning_steps || []} />
        <AgentStatus
          agents={data.active_agents || []}
          phase={data.phase}
        />
      </div>

      {/* Tool Log */}
      <ToolLog executions={data.tool_executions || []} />

      {/* Error Display */}
      {data.error && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-lg text-destructive">Error</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-sm text-destructive whitespace-pre-wrap">
              {data.error}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Results Display */}
      {data.status === "completed" && data.result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Research Results</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm max-w-none">
              <pre className="whitespace-pre-wrap font-sans text-sm">
                {data.result}
              </pre>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
