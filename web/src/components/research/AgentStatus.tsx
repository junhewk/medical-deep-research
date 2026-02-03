"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Bot, Loader2 } from "lucide-react";

interface Agent {
  name: string;
  status: string;
  currentTool?: string;
}

interface AgentStatusProps {
  agents: Agent[];
  phase?: string;
}

export function AgentStatus({ agents, phase }: AgentStatusProps) {
  const hasActiveAgents = agents && agents.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Bot className="h-5 w-5" />
          Agent Status
        </CardTitle>
      </CardHeader>
      <CardContent>
        {phase && (
          <div className="mb-4">
            <span className="text-sm text-muted-foreground">Current Phase: </span>
            <Badge variant="secondary" className="capitalize">
              {phase}
            </Badge>
          </div>
        )}

        {!hasActiveAgents ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Initializing agent...</span>
          </div>
        ) : (
          <div className="space-y-3">
            {agents.map((agent, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-3 bg-muted/50 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <Bot className="h-4 w-4 text-primary" />
                  <span className="font-medium text-sm">{agent.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  {agent.status === "running" ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                      <Badge variant="default">Running</Badge>
                    </>
                  ) : agent.status === "completed" ? (
                    <Badge variant="success">Completed</Badge>
                  ) : agent.status === "failed" ? (
                    <Badge variant="destructive">Failed</Badge>
                  ) : (
                    <Badge variant="secondary">{agent.status}</Badge>
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
