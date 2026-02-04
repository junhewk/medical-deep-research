"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Bot, Loader2, CheckCircle2, XCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface Agent {
  name: string;
  status: string;
  currentTool?: string;
}

interface AgentStatusProps {
  agents: Agent[];
  phase?: string;
}

const phaseConfig: Record<string, { label: string; color: string }> = {
  init: { label: "Initializing", color: "text-muted-foreground" },
  planning: { label: "Planning", color: "text-status-running" },
  execution: { label: "Executing", color: "text-primary" },
  synthesis: { label: "Synthesizing", color: "text-pico-i" },
  complete: { label: "Complete", color: "text-status-completed" },
};

export function AgentStatus({ agents, phase }: AgentStatusProps) {
  const hasActiveAgents = agents && agents.length > 0;
  const phaseInfo = phase ? phaseConfig[phase] || { label: phase, color: "text-muted-foreground" } : null;

  return (
    <Card>
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            Agent Status
          </CardTitle>
          {phaseInfo && (
            <Badge
              variant="outline"
              className={cn("capitalize font-medium", phaseInfo.color)}
            >
              {phaseInfo.label}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-6">
        {!hasActiveAgents ? (
          <div className="flex items-center gap-4 p-4 rounded-xl bg-muted/30 border border-dashed">
            <div className="p-2 rounded-lg bg-primary/10">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
            </div>
            <div>
              <span className="text-sm font-medium">Initializing agent...</span>
              <p className="text-xs text-muted-foreground mt-0.5">
                Setting up research environment
              </p>
            </div>
          </div>
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
                  !["running", "completed", "failed"].includes(agent.status) &&
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
                      !["running", "completed", "failed"].includes(agent.status) &&
                        "bg-muted"
                    )}
                  >
                    <Bot
                      className={cn(
                        "h-4 w-4",
                        agent.status === "running" && "text-status-running",
                        agent.status === "completed" && "text-status-completed",
                        agent.status === "failed" && "text-status-failed",
                        !["running", "completed", "failed"].includes(agent.status) &&
                          "text-muted-foreground"
                      )}
                    />
                  </div>
                  <div>
                    <span className="font-medium text-sm">{agent.name}</span>
                    {agent.currentTool && agent.status === "running" && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Using: {agent.currentTool}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {agent.status === "running" && (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin text-status-running" />
                      <Badge className="status-running">Running</Badge>
                    </>
                  )}
                  {agent.status === "completed" && (
                    <>
                      <CheckCircle2 className="h-4 w-4 text-status-completed" />
                      <Badge className="status-completed">Done</Badge>
                    </>
                  )}
                  {agent.status === "failed" && (
                    <>
                      <XCircle className="h-4 w-4 text-status-failed" />
                      <Badge className="status-failed">Failed</Badge>
                    </>
                  )}
                  {!["running", "completed", "failed"].includes(agent.status) && (
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
