"use client";

import { cn } from "@/lib/utils";
import type { PlanningStep, TodoItem } from "@/lib/research";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle, Circle, Loader2, XCircle, ListChecks, ListTodo } from "lucide-react";
import { useTranslations } from "@/i18n/client";

interface PlanningStepsProps {
  steps?: PlanningStep[];
  todos?: TodoItem[];
}

/**
 * Display research tasks - supports both legacy planning_steps and new todos format
 * Prefers todos (DeepAgents-style) if available, falls back to planning_steps
 */
export function PlanningSteps({ steps, todos }: PlanningStepsProps) {
  const { t } = useTranslations();

  // Convert todos to steps format if available
  const displaySteps: PlanningStep[] = todos && todos.length > 0
    ? todos.map(todo => ({
        id: todo.id,
        name: todo.content,
        status: todo.status,
      }))
    : steps || [];

  const hasTodos = todos && todos.length > 0;

  if (displaySteps.length === 0) {
    return (
      <Card>
        <CardHeader className="border-b border-border/50">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              {hasTodos ? (
                <ListTodo className="h-4 w-4 text-primary" />
              ) : (
                <ListChecks className="h-4 w-4 text-primary" />
              )}
            </div>
            {hasTodos ? t("progress.taskList") : t("progress.planningSteps")}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="flex items-center gap-4 p-4 rounded-xl bg-muted/30 border border-dashed">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <div>
              <span className="text-sm font-medium">{t("progress.generatingPlan")}</span>
              <p className="text-xs text-muted-foreground mt-0.5">{t("progress.analyzingQuery")}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const completedCount = displaySteps.filter((s) => s.status === "completed").length;
  const inProgressCount = displaySteps.filter((s) => s.status === "in_progress").length;

  return (
    <Card>
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              {hasTodos ? (
                <ListTodo className="h-4 w-4 text-primary" />
              ) : (
                <ListChecks className="h-4 w-4 text-primary" />
              )}
            </div>
            {hasTodos ? t("progress.taskList") : t("progress.planningSteps")}
          </CardTitle>
          <div className="flex items-center gap-3 text-sm">
            {inProgressCount > 0 && (
              <span className="flex items-center gap-1.5 text-status-running">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {inProgressCount} {t("progress.active")}
              </span>
            )}
            <span className="text-muted-foreground">
              {completedCount}/{displaySteps.length} {t("progress.complete")}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-6">
        <div className="space-y-2">
          {displaySteps.map((step, index) => (
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
                {step.action && (
                  <p className="text-xs text-muted-foreground mt-1 pl-5">
                    {step.action}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
