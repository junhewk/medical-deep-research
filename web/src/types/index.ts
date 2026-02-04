// Query types
export type QueryType = "pico" | "pcc" | "free";
export type ResearchMode = "quick" | "detailed";
export type ResearchStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type AgentPhase = "init" | "planning" | "searching" | "synthesizing" | "complete";
export type EvidenceLevel = "Level I" | "Level II" | "Level III" | "Level IV" | "Level V";

// PICO/PCC components
export interface PicoComponents {
  population?: string;
  intervention?: string;
  comparison?: string;
  outcome?: string;
}

export interface PccComponents {
  population?: string;
  concept?: string;
  context?: string;
}

// Search result types
export interface SearchResult {
  id: string;
  title: string;
  url?: string;
  snippet?: string;
  content?: string;
  source: "pubmed" | "scopus" | "cochrane" | "openalex" | "semantic_scholar";
  evidenceLevel?: EvidenceLevel;
  publicationType?: string;
  meshTerms?: string[];
  doi?: string;
  pmid?: string;
  relevanceScore?: number;
}

// API service types
export type ApiService = "openai" | "anthropic" | "scopus" | "ncbi" | "cochrane";

export interface ApiKeyConfig {
  service: ApiService;
  apiKey: string;
}
