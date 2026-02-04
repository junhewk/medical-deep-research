import { sqliteTable, text, integer, real } from "drizzle-orm/sqlite-core";

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
});

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
});

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
});

// Reports (markdown content)
export const reports = sqliteTable("reports", {
  id: text("id").primaryKey(),
  researchId: text("research_id").references(() => research.id, {
    onDelete: "cascade",
  }),
  title: text("title"),
  content: text("content"),
  format: text("format").default("markdown"),
  wordCount: integer("word_count"),
  referenceCount: integer("reference_count"),
  version: integer("version").default(1),
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
  updatedAt: integer("updated_at", { mode: "timestamp" }),
});

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
});

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
  createdAt: integer("created_at", { mode: "timestamp" })
    .notNull()
    .$defaultFn(() => new Date()),
});

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
