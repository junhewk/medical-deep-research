"use client";

import { cn } from "@/lib/utils";
import type { PlanningStep } from "@/lib/research";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle, Circle, Loader2, XCircle, ListChecks } from "lucide-react";

interface PlanningStepsProps {
  steps: PlanningStep[];
}

export function PlanningSteps({ steps }: PlanningStepsProps) {
  if (!steps || steps.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2 font-serif">
            <ListChecks className="h-5 w-5 text-primary" />
            Planning Steps
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Generating research plan...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2 font-serif">
          <ListChecks className="h-5 w-5 text-primary" />
          Planning Steps
          <span className="text-sm font-normal text-muted-foreground font-sans ml-auto">
            {steps.filter((s) => s.status === "completed").length}/{steps.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {steps.map((step, index) => (
            <div
              key={step.id}
              className={cn(
                "flex items-start gap-3 p-3 rounded-lg transition-all duration-200 border",
                step.status === "pending" && "bg-muted/30 border-transparent",
                step.status === "in_progress" &&
                  "bg-status-running/5 border-status-running/20 shadow-sm",
                step.status === "completed" &&
                  "bg-status-completed/5 border-status-completed/20",
                step.status === "failed" &&
                  "bg-status-failed/5 border-status-failed/20"
              )}
            >
              <div className="flex-shrink-0 mt-0.5">
                {step.status === "pending" && (
                  <Circle className="h-5 w-5 text-muted-foreground/50" />
                )}
                {step.status === "in_progress" && (
                  <Loader2 className="h-5 w-5 text-status-running animate-spin" />
                )}
                {step.status === "completed" && (
                  <CheckCircle className="h-5 w-5 text-status-completed" />
                )}
                {step.status === "failed" && (
                  <XCircle className="h-5 w-5 text-status-failed" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "text-xs font-medium w-5",
                      step.status === "in_progress" && "text-status-running",
                      step.status === "completed" && "text-status-completed",
                      step.status === "failed" && "text-status-failed",
                      step.status === "pending" && "text-muted-foreground"
                    )}
                  >
                    {index + 1}.
                  </span>
                  <span
                    className={cn(
                      "font-medium text-sm",
                      step.status === "in_progress" && "text-status-running",
                      step.status === "completed" && "text-foreground",
                      step.status === "failed" && "text-status-failed",
                      step.status === "pending" && "text-muted-foreground"
                    )}
                  >
                    {step.name}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-1 pl-5">
                  {step.action}
                </p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
