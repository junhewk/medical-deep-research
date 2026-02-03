import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface PlanningStep {
  id: string;
  name: string;
  action: string;
  status: "pending" | "in_progress" | "completed" | "failed";
}

export interface ToolExecution {
  tool: string;
  status: "running" | "completed" | "failed";
  query?: string;
  startTime?: string;
  endTime?: string;
  duration?: number;
  error?: string;
}

export interface ResearchProgress {
  id: string;
  query: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  phase?: string;
  planning_steps?: PlanningStep[];
  active_agents?: Array<{ name: string; status: string }>;
  tool_executions?: ToolExecution[];
  result?: string;
  error?: string;
}

export interface ResearchListItem {
  id: string;
  query: string;
  status: string;
  progress: number;
  createdAt: string;
  completedAt?: string;
}

// Get list of all research for current user
export function useResearchList() {
  return useQuery({
    queryKey: ["research-list"],
    queryFn: async (): Promise<ResearchListItem[]> => {
      const res = await fetch("/api/research");
      if (!res.ok) throw new Error("Failed to fetch research list");
      return res.json();
    },
  });
}

// Get single research progress/details
export function useResearch(id: string) {
  return useQuery({
    queryKey: ["research", id],
    queryFn: async (): Promise<ResearchProgress> => {
      const res = await fetch(`/api/research/${id}`);
      if (!res.ok) throw new Error("Failed to fetch research");
      return res.json();
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      // Poll while running
      if (data?.status === "running" || data?.status === "pending") {
        return 1000;
      }
      return false;
    },
  });
}

// Start new research
export function useStartResearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: {
      query: string;
      llmProvider?: string;
      model?: string;
    }): Promise<{ research_id: string }> => {
      const res = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.error || "Failed to start research");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["research-list"] });
    },
  });
}

// Get progress from Python backend directly
export function useResearchProgress(id: string) {
  return useQuery({
    queryKey: ["research-progress", id],
    queryFn: async (): Promise<ResearchProgress> => {
      const res = await fetch(`${API_URL}/research/${id}`);
      if (!res.ok) throw new Error("Failed to fetch progress");
      return res.json();
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.status === "running" || data?.status === "pending") {
        return 500; // Poll more frequently for progress
      }
      return false;
    },
    enabled: !!id,
  });
}
