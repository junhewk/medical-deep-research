#!/usr/bin/env npx tsx
/**
 * Database initialization script
 *
 * This script initializes the SQLite database with all required tables.
 * It handles both new installations and upgrades from existing databases.
 *
 * IMPORTANT: Uses sqlite.exec() directly instead of Drizzle's db.run()
 * because Drizzle's sql template literal doesn't execute raw DDL properly.
 *
 * Usage:
 *   npx tsx scripts/init-db.ts
 *   npm run db:init
 */

import Database from "better-sqlite3";
import * as fs from "fs";
import * as path from "path";

const DB_PATH = process.env.DATABASE_PATH || "./data/medical-deep-research.db";

function initDatabase() {
  console.log("🗄️  Initializing database...");
  console.log(`   Path: ${DB_PATH}`);

  // Ensure data directory exists
  const dataDir = path.dirname(DB_PATH);
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
    console.log(`   Created directory: ${dataDir}`);
  }

  // Connect directly to SQLite (not through Drizzle for DDL operations)
  const sqlite = new Database(DB_PATH);

  // Enable foreign keys
  sqlite.pragma("foreign_keys = ON");

  // All DDL statements as raw SQL strings
  // Using sqlite.exec() for proper execution
  const statements = [
    // ==========================================
    // Core tables
    // ==========================================
    `CREATE TABLE IF NOT EXISTS research (
      id TEXT PRIMARY KEY,
      query TEXT NOT NULL,
      query_type TEXT DEFAULT 'pico',
      mode TEXT DEFAULT 'detailed',
      status TEXT DEFAULT 'pending',
      progress INTEGER DEFAULT 0,
      title TEXT,
      created_at INTEGER NOT NULL,
      started_at INTEGER,
      completed_at INTEGER,
      duration_seconds INTEGER,
      error_message TEXT
    )`,
    `CREATE INDEX IF NOT EXISTS research_status_idx ON research (status)`,
    `CREATE INDEX IF NOT EXISTS research_created_at_idx ON research (created_at)`,

    `CREATE TABLE IF NOT EXISTS pico_queries (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      population TEXT,
      intervention TEXT,
      comparison TEXT,
      outcome TEXT,
      generated_pubmed_query TEXT,
      mesh_terms TEXT,
      created_at INTEGER NOT NULL
    )`,
    `CREATE INDEX IF NOT EXISTS pico_research_id_idx ON pico_queries (research_id)`,

    `CREATE TABLE IF NOT EXISTS pcc_queries (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      population TEXT,
      concept TEXT,
      context TEXT,
      generated_query TEXT,
      created_at INTEGER NOT NULL
    )`,
    `CREATE INDEX IF NOT EXISTS pcc_research_id_idx ON pcc_queries (research_id)`,

    `CREATE TABLE IF NOT EXISTS reports (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      title TEXT,
      content TEXT,
      original_content TEXT,
      language TEXT DEFAULT 'en',
      format TEXT DEFAULT 'markdown',
      word_count INTEGER,
      reference_count INTEGER,
      version INTEGER DEFAULT 1,
      created_at INTEGER NOT NULL,
      updated_at INTEGER
    )`,
    `CREATE INDEX IF NOT EXISTS reports_research_id_idx ON reports (research_id)`,

    `CREATE TABLE IF NOT EXISTS agent_states (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      phase TEXT NOT NULL,
      message TEXT,
      overall_progress INTEGER DEFAULT 0,
      planning_steps TEXT,
      active_agents TEXT,
      tool_executions TEXT,
      state_file_path TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER
    )`,
    `CREATE INDEX IF NOT EXISTS agent_states_research_id_idx ON agent_states (research_id)`,
    `CREATE INDEX IF NOT EXISTS agent_states_created_at_idx ON agent_states (created_at)`,

    `CREATE TABLE IF NOT EXISTS search_results (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      title TEXT,
      url TEXT,
      snippet TEXT,
      content TEXT,
      source TEXT,
      evidence_level TEXT,
      publication_type TEXT,
      mesh_terms TEXT,
      doi TEXT,
      pmid TEXT,
      relevance_score REAL,
      authors TEXT,
      journal TEXT,
      volume TEXT,
      issue TEXT,
      pages TEXT,
      publication_year TEXT,
      citation_count INTEGER,
      composite_score REAL,
      evidence_level_score REAL,
      citation_score REAL,
      recency_score REAL,
      reference_number INTEGER,
      vancouver_citation TEXT,
      created_at INTEGER NOT NULL
    )`,
    `CREATE INDEX IF NOT EXISTS search_results_research_id_idx ON search_results (research_id)`,
    `CREATE INDEX IF NOT EXISTS search_results_source_idx ON search_results (source)`,
    `CREATE INDEX IF NOT EXISTS search_results_composite_score_idx ON search_results (composite_score)`,

    // ==========================================
    // Configuration tables
    // ==========================================
    `CREATE TABLE IF NOT EXISTS api_keys (
      id TEXT PRIMARY KEY,
      service TEXT NOT NULL UNIQUE,
      api_key TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER
    )`,

    `CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      category TEXT,
      updated_at INTEGER
    )`,

    `CREATE TABLE IF NOT EXISTS llm_config (
      id TEXT PRIMARY KEY,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      is_default INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER
    )`,

    // ==========================================
    // MeSH cache tables
    // ==========================================
    `CREATE TABLE IF NOT EXISTS mesh_cache (
      id TEXT PRIMARY KEY,
      label TEXT NOT NULL,
      alternate_labels TEXT,
      tree_numbers TEXT,
      broader_terms TEXT,
      narrower_terms TEXT,
      scope_note TEXT,
      fetched_at INTEGER NOT NULL
    )`,

    `CREATE TABLE IF NOT EXISTS mesh_lookup_index (
      id TEXT PRIMARY KEY,
      search_term TEXT NOT NULL,
      mesh_id TEXT REFERENCES mesh_cache(id),
      match_type TEXT
    )`,
    `CREATE INDEX IF NOT EXISTS mesh_lookup_search_term_idx ON mesh_lookup_index (search_term)`,

    // ==========================================
    // DeepAgents middleware tables (v2.4+)
    // ==========================================
    `CREATE TABLE IF NOT EXISTS research_todos (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      text TEXT NOT NULL,
      status TEXT DEFAULT 'pending',
      "order" INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      completed_at INTEGER
    )`,
    `CREATE INDEX IF NOT EXISTS research_todos_research_id_idx ON research_todos (research_id)`,

    `CREATE TABLE IF NOT EXISTS research_files (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      path TEXT NOT NULL,
      content TEXT,
      size INTEGER,
      created_at INTEGER NOT NULL,
      updated_at INTEGER
    )`,
    `CREATE INDEX IF NOT EXISTS research_files_research_id_idx ON research_files (research_id)`,
    `CREATE INDEX IF NOT EXISTS research_files_path_idx ON research_files (path)`,

    `CREATE TABLE IF NOT EXISTS subagent_executions (
      id TEXT PRIMARY KEY,
      research_id TEXT REFERENCES research(id) ON DELETE CASCADE,
      subagent_name TEXT NOT NULL,
      task TEXT NOT NULL,
      result TEXT,
      duration INTEGER,
      created_at INTEGER NOT NULL
    )`,
    `CREATE INDEX IF NOT EXISTS subagent_executions_research_id_idx ON subagent_executions (research_id)`,
  ];

  // Execute each statement using sqlite.exec() for proper DDL execution
  let created = 0;
  let skipped = 0;
  let errors = 0;

  for (const stmt of statements) {
    try {
      sqlite.exec(stmt);
      created++;
    } catch (error) {
      const msg = (error as Error).message;
      if (msg.includes("already exists")) {
        skipped++;
      } else {
        console.error(`   ⚠️  Error: ${msg}`);
        errors++;
      }
    }
  }

  // Verify tables were created
  const tableCount = sqlite
    .prepare("SELECT COUNT(*) as count FROM sqlite_master WHERE type='table'")
    .get() as { count: number };

  const indexCount = sqlite
    .prepare("SELECT COUNT(*) as count FROM sqlite_master WHERE type='index'")
    .get() as { count: number };

  console.log(`✅ Database initialized`);
  console.log(`   ${created} statements executed, ${skipped} skipped (already exist)`);
  if (errors > 0) {
    console.log(`   ⚠️  ${errors} errors occurred`);
  }
  console.log(`   Total: ${tableCount.count} tables, ${indexCount.count} indexes`);

  // Close connection
  sqlite.close();
}

initDatabase();
