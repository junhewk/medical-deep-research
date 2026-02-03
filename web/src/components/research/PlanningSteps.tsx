"use client";

import { cn } from "@/lib/utils";
import type { PlanningStep } from "@/lib/research";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle, Circle, Loader2, XCircle } from "lucide-react";

interface PlanningStepsProps {
  steps: PlanningStep[];
}

export function PlanningSteps({ steps }: PlanningStepsProps) {
  if (!steps || steps.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Planning Steps</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            Waiting for research plan...
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Planning Steps</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {steps.map((step, index) => (
            <div
              key={step.id}
              className={cn(
                "flex items-start gap-3 p-3 rounded-lg transition-colors",
                step.status === "in_progress" && "bg-blue-50 border border-blue-200",
                step.status === "completed" && "bg-green-50",
                step.status === "failed" && "bg-red-50"
              )}
            >
              <div className="flex-shrink-0 mt-0.5">
                {step.status === "pending" && (
                  <Circle className="h-5 w-5 text-muted-foreground" />
                )}
                {step.status === "in_progress" && (
                  <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
                )}
                {step.status === "completed" && (
                  <CheckCircle className="h-5 w-5 text-green-500" />
                )}
                {step.status === "failed" && (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-muted-foreground">
                    {index + 1}.
                  </span>
                  <span
                    className={cn(
                      "font-medium text-sm",
                      step.status === "in_progress" && "text-blue-700",
                      step.status === "completed" && "text-green-700",
                      step.status === "failed" && "text-red-700"
                    )}
                  >
                    {step.name}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Action: {step.action}
                </p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
