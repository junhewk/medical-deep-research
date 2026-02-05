import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface PlanningStep {
  id: string;
  name: string;
  action?: string;
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

export interface PicoQuery {
  population?: string;
  intervention?: string;
  comparison?: string;
  outcome?: string;
  generatedPubmedQuery?: string;
  meshTerms?: string[];
}

export interface PccQuery {
  population?: string;
  concept?: string;
  context?: string;
  generatedQuery?: string;
}

export interface Report {
  id: string;
  title?: string;
  content?: string;
  originalContent?: string;  // English original (when translated)
  language?: string;         // Report language ('en' or 'ko')
  wordCount?: number;
  referenceCount?: number;
  createdAt?: string;
}

export interface ResearchProgress {
  id: string;
  query: string;
  queryType?: "pico" | "pcc" | "free";
  mode?: "quick" | "detailed";
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  phase?: string;
  title?: string;
  planning_steps?: PlanningStep[];
  active_agents?: Array<{ name: string; status: string }>;
  tool_executions?: ToolExecution[];
  picoQuery?: PicoQuery;
  pccQuery?: PccQuery;
  searchResultsCount?: number;
  report?: Report;
  result?: string;
  error?: string;
  errorMessage?: string;
  createdAt?: string;
  startedAt?: string;
  completedAt?: string;
  durationSeconds?: number;
  stateMarkdown?: string;
  reportMarkdown?: string;
}

export interface ResearchListItem {
  id: string;
  query: string;
  queryType?: string;
  status: string;
  progress: number;
  createdAt: string;
  completedAt?: string;
}

// Get list of all research
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
      queryType?: "pico" | "pcc" | "free";
      llmProvider?: string;
      model?: string;
      picoComponents?: {
        population?: string;
        intervention?: string;
        comparison?: string;
        outcome?: string;
      };
      pccComponents?: {
        population?: string;
        concept?: string;
        context?: string;
      };
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

// Cancel research
export function useCancelResearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const res = await fetch(`/api/research/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "cancel" }),
      });
      if (!res.ok) throw new Error("Failed to cancel research");
    },
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["research", id] });
      queryClient.invalidateQueries({ queryKey: ["research-list"] });
    },
  });
}

// Delete research
export function useDeleteResearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const res = await fetch(`/api/research/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete research");
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["research-list"] });
    },
  });
}
