"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Bot, Loader2, CheckCircle2, XCircle, Sparkles, Languages, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslations } from "@/i18n/client";

interface Agent {
  name: string;
  status: string;
  currentTool?: string;
}

interface AgentStatusProps {
  agents: Agent[];
  phase?: string;
}

const KNOWN_STATUSES = ["running", "completed", "failed"] as const;
type KnownStatus = (typeof KNOWN_STATUSES)[number];

function isKnownStatus(status: string): status is KnownStatus {
  return KNOWN_STATUSES.includes(status as KnownStatus);
}

export function AgentStatus({ agents, phase }: AgentStatusProps) {
  const { t } = useTranslations();

  const phaseConfig: Record<string, { labelKey: string; color: string; icon?: typeof Sparkles }> = {
    init: { labelKey: "agent.phases.init", color: "text-muted-foreground" },
    planning: { labelKey: "agent.phases.planning", color: "text-status-running" },
    execution: { labelKey: "agent.phases.execution", color: "text-primary" },
    synthesis: { labelKey: "agent.phases.synthesis", color: "text-pico-i" },
    translating: { labelKey: "agent.phases.translating", color: "text-[hsl(275,45%,48%)]", icon: Languages },
    complete: { labelKey: "agent.phases.complete", color: "text-status-completed" },
  };

  const hasActiveAgents = agents && agents.length > 0;
  const phaseInfo = phase ? phaseConfig[phase] || { labelKey: phase, color: "text-muted-foreground" } : null;
  const isTranslating = phase === "translating";
  const isSynthesizing = phase === "synthesizing";

  return (
    <Card className={cn(
      "transition-all duration-500",
      isTranslating && "ring-2 ring-[hsl(275,45%,48%)]/30 shadow-lg shadow-[hsl(275,45%,48%)]/10",
      isSynthesizing && "ring-2 ring-[hsl(175,60%,40%)]/30 shadow-lg shadow-[hsl(175,60%,40%)]/10"
    )}>
      <CardHeader className={cn(
        "border-b border-border/50 transition-colors duration-500",
        isTranslating && "bg-gradient-to-r from-[hsl(275,45%,48%)]/8 via-[hsl(275,45%,48%)]/4 to-transparent",
        isSynthesizing && "bg-gradient-to-r from-[hsl(175,60%,40%)]/8 via-[hsl(175,60%,40%)]/4 to-transparent"
      )}>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-3">
            <div className={cn(
              "p-2 rounded-lg transition-colors duration-500",
              isTranslating ? "bg-[hsl(275,45%,48%)]/15" :
              isSynthesizing ? "bg-[hsl(175,60%,40%)]/15" : "bg-primary/10"
            )}>
              {isTranslating ? (
                <Languages className="h-4 w-4 text-[hsl(275,45%,48%)] animate-pulse" />
              ) : isSynthesizing ? (
                <FileText className="h-4 w-4 text-[hsl(175,60%,40%)] animate-pulse" />
              ) : (
                <Sparkles className="h-4 w-4 text-primary" />
              )}
            </div>
            {t("agent.title")}
          </CardTitle>
          {phaseInfo && (
            <Badge
              variant="outline"
              className={cn(
                "capitalize font-medium transition-all duration-300",
                phaseInfo.color,
                isTranslating && "border-[hsl(275,45%,48%)]/40 bg-[hsl(275,45%,48%)]/10 animate-pulse",
                isSynthesizing && "border-[hsl(175,60%,40%)]/40 bg-[hsl(175,60%,40%)]/10 animate-pulse"
              )}
            >
              {phaseInfo.icon && <phaseInfo.icon className="h-3 w-3 mr-1.5" />}
              {t(phaseInfo.labelKey)}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-6">
        {/* Synthesis Progress Indicator */}
        {isSynthesizing && (
          <div className="mb-4 p-4 rounded-xl bg-gradient-to-br from-[hsl(175,60%,40%)]/10 via-[hsl(175,60%,40%)]/5 to-transparent border border-[hsl(175,60%,40%)]/20 animate-fade-in">
            <div className="flex items-center gap-4">
              <div className="relative">
                <div className="p-3 rounded-xl bg-[hsl(175,60%,40%)]/15">
                  <FileText className="h-6 w-6 text-[hsl(175,60%,40%)]" />
                </div>
                {/* Orbiting dots animation */}
                <div className="absolute -inset-1 rounded-xl">
                  <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1 w-1.5 h-1.5 rounded-full bg-[hsl(175,60%,40%)] animate-[orbit_2s_linear_infinite]" />
                  <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1 w-1.5 h-1.5 rounded-full bg-[hsl(175,60%,40%)]/60 animate-[orbit_2s_linear_infinite_1s]" />
                </div>
              </div>
              <div className="flex-1">
                <p className="font-serif text-base font-medium text-[hsl(175,60%,40%)]">
                  {t("agent.synthesizing")}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("agent.synthesizingDescription")}
                </p>
                {/* Progress bar */}
                <div className="mt-3 h-1 rounded-full bg-[hsl(175,60%,40%)]/20 overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-[hsl(175,60%,40%)] to-[hsl(205,65%,50%)] rounded-full animate-[translateProgress_2s_ease-in-out_infinite]" style={{ width: '60%' }} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Translation Progress Indicator */}
        {isTranslating && (
          <div className="mb-4 p-4 rounded-xl bg-gradient-to-br from-[hsl(275,45%,48%)]/10 via-[hsl(275,45%,48%)]/5 to-transparent border border-[hsl(275,45%,48%)]/20 animate-fade-in">
            <div className="flex items-center gap-4">
              <div className="relative">
                <div className="p-3 rounded-xl bg-[hsl(275,45%,48%)]/15">
                  <Languages className="h-6 w-6 text-[hsl(275,45%,48%)]" />
                </div>
                {/* Orbiting dots animation */}
                <div className="absolute -inset-1 rounded-xl">
                  <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1 w-1.5 h-1.5 rounded-full bg-[hsl(275,45%,48%)] animate-[orbit_2s_linear_infinite]" />
                  <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1 w-1.5 h-1.5 rounded-full bg-[hsl(275,45%,48%)]/60 animate-[orbit_2s_linear_infinite_1s]" />
                </div>
              </div>
              <div className="flex-1">
                <p className="font-serif text-base font-medium text-[hsl(275,45%,48%)]">
                  {t("agent.translating")}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("agent.translatingDescription")}
                </p>
                {/* Progress bar */}
                <div className="mt-3 h-1 rounded-full bg-[hsl(275,45%,48%)]/20 overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-[hsl(275,45%,48%)] to-[hsl(205,65%,50%)] rounded-full animate-[translateProgress_2s_ease-in-out_infinite]" style={{ width: '60%' }} />
                </div>
              </div>
            </div>
          </div>
        )}

        {!hasActiveAgents ? (
          phase === "complete" ? (
            // Research complete - show completion message instead of initializing
            <div className="flex items-center gap-4 p-4 rounded-xl bg-status-completed/10 border border-status-completed/20">
              <div className="p-2 rounded-lg bg-status-completed/10">
                <CheckCircle2 className="h-5 w-5 text-status-completed" />
              </div>
              <div>
                <span className="text-sm font-medium text-status-completed">{t("agent.phases.complete")}</span>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t("agent.researchComplete")}
                </p>
              </div>
            </div>
          ) : (
            // Still initializing
            <div className="flex items-center gap-4 p-4 rounded-xl bg-muted/30 border border-dashed">
              <div className="p-2 rounded-lg bg-primary/10">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
              </div>
              <div>
                <span className="text-sm font-medium">{t("agent.initializing")}</span>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t("agent.settingUp")}
                </p>
              </div>
            </div>
          )
        ) : (
          <div className="space-y-2">
            {agents.map((agent, index) => (
              <div
                key={index}
                className={cn(
                  "flex items-center justify-between p-3 rounded-lg border transition-all duration-200",
                  agent.status === "running" &&
                    "bg-status-running/5 border-status-running/20",
                  agent.status === "completed" &&
                    "bg-status-completed/5 border-status-completed/20",
                  agent.status === "failed" &&
                    "bg-status-failed/5 border-status-failed/20",
                  !isKnownStatus(agent.status) &&
                    "bg-muted/30 border-transparent"
                )}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "p-1.5 rounded-md",
                      agent.status === "running" && "bg-status-running/10",
                      agent.status === "completed" && "bg-status-completed/10",
                      agent.status === "failed" && "bg-status-failed/10",
                      !isKnownStatus(agent.status) && "bg-muted"
                    )}
                  >
                    <Bot
                      className={cn(
                        "h-4 w-4",
                        agent.status === "running" && "text-status-running",
                        agent.status === "completed" && "text-status-completed",
                        agent.status === "failed" && "text-status-failed",
                        !isKnownStatus(agent.status) && "text-muted-foreground"
                      )}
                    />
                  </div>
                  <div>
                    <span className="font-medium text-sm">{agent.name}</span>
                    {agent.currentTool && agent.status === "running" && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {t("agent.using")}: {agent.currentTool}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {agent.status === "running" && (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin text-status-running" />
                      <Badge className="status-running">{t("status.running")}</Badge>
                    </>
                  )}
                  {agent.status === "completed" && (
                    <>
                      <CheckCircle2 className="h-4 w-4 text-status-completed" />
                      <Badge className="status-completed">{t("agent.done")}</Badge>
                    </>
                  )}
                  {agent.status === "failed" && (
                    <>
                      <XCircle className="h-4 w-4 text-status-failed" />
                      <Badge className="status-failed">{t("status.failed")}</Badge>
                    </>
                  )}
                  {!isKnownStatus(agent.status) && (
                    <Badge variant="secondary" className="text-xs">
                      {agent.status}
                    </Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
