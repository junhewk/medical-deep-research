import Database from "better-sqlite3";
import { drizzle, BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import * as schema from "./schema";
import path from "path";
import fs from "fs";

// Determine data directory path
// Priority: DATA_DIR env var > relative to package root > relative to cwd
function getDataDir(): string {
  if (process.env.DATA_DIR) {
    return process.env.DATA_DIR;
  }

  // Try common locations
  const candidates = [
    path.join(process.cwd(), "data"),           // web/data (when running from web/)
    path.join(process.cwd(), "..", "data"),     // medical-deep-research/data
  ];

  for (const candidate of candidates) {
    // Check if parent directory exists (we'll create data dir if needed)
    const parentDir = path.dirname(candidate);
    if (fs.existsSync(parentDir)) {
      return candidate;
    }
  }

  // Default fallback
  return path.join(process.cwd(), "data");
}

// Lazy initialization to avoid issues during build
let _db: BetterSQLite3Database<typeof schema> | null = null;

function initializeDb(): BetterSQLite3Database<typeof schema> {
  if (_db) return _db;

  const dataDir = getDataDir();

  // Ensure data directory exists
  try {
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true });
    }
  } catch (error) {
    console.error(`Failed to create data directory at ${dataDir}:`, error);
    throw new Error(`Cannot create data directory: ${dataDir}`);
  }

  const dbPath = path.join(dataDir, "medical-deep-research.db");

  let sqlite: Database.Database;
  try {
    sqlite = new Database(dbPath);
    // Enable WAL mode for better concurrent access
    sqlite.pragma("journal_mode = WAL");
  } catch (error) {
    console.error(`Failed to open database at ${dbPath}:`, error);
    throw new Error(`Cannot open database: ${dbPath}`);
  }

  _db = drizzle(sqlite, { schema });
  return _db;
}

// Export as a getter to ensure lazy initialization
export const db = new Proxy({} as BetterSQLite3Database<typeof schema>, {
  get(_, prop) {
    const realDb = initializeDb();
    return (realDb as unknown as Record<string | symbol, unknown>)[prop];
  },
});

// Export schema for convenience
export * from "./schema";
