import { sqliteTable, text, integer, real, index } from "drizzle-orm/sqlite-core";

// Research sessions
export const research = sqliteTable("research", {
  id: text("id").primaryKey(),
  query: text("query").notNull(),
  queryType: text("query_type", { enum: ["pico", "pcc", "free"] }).default("pico"),
  mode: text("mode", { enum: ["quick", "detailed"] }).default("detailed"),
  status: text("status", {
    enum: ["pending", "running", "completed", "failed", "cancelled"],
  }).default("pending"),
  progress: integer("progress").default(0),
  title: text("title"),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  startedAt: integer("started_at", { mode: "timestamp" }),
  completedAt: integer("completed_at", { mode: "timestamp" }),
  durationSeconds: integer("duration_seconds"),
  errorMessage: text("error_message"),
}, (table) => ({
  statusIdx: index("research_status_idx").on(table.status),
  createdAtIdx: index("research_created_at_idx").on(table.createdAt),
}));

// PICO queries
export const picoQueries = sqliteTable("pico_queries", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, {
    onDelete: "cascade",
  }),
  population: text("population"),
  intervention: text("intervention"),
  comparison: text("comparison"),
  outcome: text("outcome"),
  generatedPubmedQuery: text("generated_pubmed_query"),
  meshTerms: text("mesh_terms"), // JSON array
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
}, (table) => ({
  researchIdIdx: index("pico_research_id_idx").on(table.researchId),
}));

// PCC queries (qualitative research)
export const pccQueries = sqliteTable("pcc_queries", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, {
    onDelete: "cascade",
  }),
  population: text("population"),
  concept: text("concept"),
  context: text("context"),
  generatedQuery: text("generated_query"),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
}, (table) => ({
  researchIdIdx: index("pcc_research_id_idx").on(table.researchId),
}));

// Reports (markdown content)
export const reports = sqliteTable("reports", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, {
    onDelete: "cascade",
  }),
  title: text("title"),
  content: text("content"), // Final report (translated if language != 'en')
  originalContent: text("original_content"), // English original (always stored)
  language: text("language").default("en"), // Report language ('en' or 'ko')
  format: text("format").default("markdown"),
  wordCount: integer("word_count"),
  referenceCount: integer("reference_count"),
  version: integer("version").default(1),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
}, (table) => ({
  researchIdIdx: index("reports_research_id_idx").on(table.researchId),
}));

// Agent state snapshots
export const agentStates = sqliteTable("agent_states", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, {
    onDelete: "cascade",
  }),
  phase: text("phase").notNull(), // init, planning, execution, synthesis, complete
  message: text("message"),
  overallProgress: integer("overall_progress").default(0),
  planningSteps: text("planning_steps"), // JSON array
  activeAgents: text("active_agents"), // JSON array
  toolExecutions: text("tool_executions"), // JSON array
  stateFilePath: text("state_file_path"),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
}, (table) => ({
  researchIdIdx: index("agent_states_research_id_idx").on(table.researchId),
  createdAtIdx: index("agent_states_created_at_idx").on(table.createdAt),
}));

// Search results
export const searchResults = sqliteTable("search_results", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, {
    onDelete: "cascade",
  }),
  title: text("title"),
  url: text("url"),
  snippet: text("snippet"),
  content: text("content"),
  source: text("source"), // pubmed, scopus, cochrane, openalex, semantic_scholar
  evidenceLevel: text("evidence_level"), // Level I-V
  publicationType: text("publication_type"),
  meshTerms: text("mesh_terms"), // JSON array
  doi: text("doi"),
  pmid: text("pmid"),
  relevanceScore: real("relevance_score"),
  // Bibliographic data for Vancouver formatting
  authors: text("authors"), // JSON array
  journal: text("journal"),
  volume: text("volume"),
  issue: text("issue"),
  pages: text("pages"),
  publicationYear: text("publication_year"),
  citationCount: integer("citation_count"),
  // Composite scoring data
  compositeScore: real("composite_score"),
  evidenceLevelScore: real("evidence_level_score"),
  citationScore: real("citation_score"),
  recencyScore: real("recency_score"),
  // Reference tracking
  referenceNumber: integer("reference_number"), // [1], [2], etc.
  vancouverCitation: text("vancouver_citation"), // Pre-formatted string
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
}, (table) => ({
  researchIdIdx: index("search_results_research_id_idx").on(table.researchId),
  sourceIdx: index("search_results_source_idx").on(table.source),
  compositeScoreIdx: index("search_results_composite_score_idx").on(table.compositeScore),
}));

// API keys (BYOK)
export const apiKeys = sqliteTable("api_keys", {
  id: text("id").primaryKey(),
  service: text("service").notNull().unique(), // scopus, ncbi, openai, anthropic, etc.
  apiKey: text("api_key").notNull(),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
});

// Settings
export const settings = sqliteTable("settings", {
  key: text("key").primaryKey(),
  value: text("value").notNull(),
  category: text("category"),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
});

// LLM configuration
export const llmConfig = sqliteTable("llm_config", {
  id: text("id").primaryKey(),
  provider: text("provider", { enum: ["openai", "anthropic", "google"] }).notNull(),
  model: text("model").notNull(),
  isDefault: integer("is_default", { mode: "boolean" }).default(false),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
});

// MeSH term cache (for dynamic NLM API lookups)
export const meshCache = sqliteTable("mesh_cache", {
  id: text("id").primaryKey(), // DescriptorUI (e.g., "D009204")
  label: text("label").notNull(), // Primary label
  alternateLabels: text("alternate_labels"), // JSON array of synonyms
  treeNumbers: text("tree_numbers"), // JSON array (e.g., ["E04.100.814"])
  broaderTerms: text("broader_terms"), // JSON array of parent UIDs
  narrowerTerms: text("narrower_terms"), // JSON array of child UIDs
  scopeNote: text("scope_note"), // Definition
  fetchedAt: integer("fetched_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
});

// Text-to-MeSH lookup index (for fast text matching)
export const meshLookupIndex = sqliteTable("mesh_lookup_index", {
  id: text("id").primaryKey(),
  searchTerm: text("search_term").notNull(), // Lowercase normalized
  meshId: text("mesh_id").references(() => meshCache.id),
  matchType: text("match_type", { enum: ["exact", "contains", "synonym"] }),
}, (table) => ({
  searchTermIdx: index("mesh_lookup_search_term_idx").on(table.searchTerm),
}));

// Research todos (dynamic task tracking for DeepAgents)
export const researchTodos = sqliteTable("research_todos", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, { onDelete: "cascade" }),
  text: text("text").notNull(),
  status: text("status", { enum: ["pending", "in_progress", "completed"] }).default("pending"),
  order: integer("order").default(0),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  completedAt: integer("completed_at", { mode: "timestamp" }),
}, (table) => ({
  researchIdIdx: index("research_todos_research_id_idx").on(table.researchId),
}));

// Research files (context offloading storage for DeepAgents)
export const researchFiles = sqliteTable("research_files", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, { onDelete: "cascade" }),
  path: text("path").notNull(),
  content: text("content"),
  size: integer("size"),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
}, (table) => ({
  researchIdIdx: index("research_files_research_id_idx").on(table.researchId),
  pathIdx: index("research_files_path_idx").on(table.path),
}));

// Subagent executions (audit trail for DeepAgents)
export const subagentExecutions = sqliteTable("subagent_executions", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, { onDelete: "cascade" }),
  subagentName: text("subagent_name").notNull(),
  task: text("task").notNull(),
  result: text("result"),
  duration: integer("duration"), // milliseconds
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
}, (table) => ({
  researchIdIdx: index("subagent_executions_research_id_idx").on(table.researchId),
}));

// Type exports
export type Research = typeof research.$inferSelect;
export type NewResearch = typeof research.$inferInsert;
export type PicoQuery = typeof picoQueries.$inferSelect;
export type NewPicoQuery = typeof picoQueries.$inferInsert;
export type PccQuery = typeof pccQueries.$inferSelect;
export type NewPccQuery = typeof pccQueries.$inferInsert;
export type Report = typeof reports.$inferSelect;
export type NewReport = typeof reports.$inferInsert;
export type AgentState = typeof agentStates.$inferSelect;
export type NewAgentState = typeof agentStates.$inferInsert;
export type SearchResult = typeof searchResults.$inferSelect;
export type NewSearchResult = typeof searchResults.$inferInsert;
export type ApiKey = typeof apiKeys.$inferSelect;
export type NewApiKey = typeof apiKeys.$inferInsert;
export type Setting = typeof settings.$inferSelect;
export type NewSetting = typeof settings.$inferInsert;
export type LlmConfig = typeof llmConfig.$inferSelect;
export type NewLlmConfig = typeof llmConfig.$inferInsert;
export type MeshCache = typeof meshCache.$inferSelect;
export type NewMeshCache = typeof meshCache.$inferInsert;
export type MeshLookupIndex = typeof meshLookupIndex.$inferSelect;
export type NewMeshLookupIndex = typeof meshLookupIndex.$inferInsert;
export type ResearchTodo = typeof researchTodos.$inferSelect;
export type NewResearchTodo = typeof researchTodos.$inferInsert;
export type ResearchFile = typeof researchFiles.$inferSelect;
export type NewResearchFile = typeof researchFiles.$inferInsert;
export type SubagentExecution = typeof subagentExecutions.$inferSelect;
export type NewSubagentExecution = typeof subagentExecutions.$inferInsert;
