import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
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

// Get database path
function getDbPath(): string {
  if (process.env.DATABASE_PATH) {
    const dbPath = process.env.DATABASE_PATH;
    // Ensure parent directory exists
    const parentDir = path.dirname(dbPath);
    if (!fs.existsSync(parentDir)) {
      fs.mkdirSync(parentDir, { recursive: true });
    }
    return dbPath;
  }

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
  return path.join(dataDir, "medical-deep-research.db");
}

// Create database connection
// Note: In Next.js dev mode, this may be called multiple times due to hot reloading
// Using a global variable to cache the connection across hot reloads
const globalForDb = globalThis as unknown as {
  sqlite: Database.Database | undefined;
  db: ReturnType<typeof drizzle<typeof schema>> | undefined;
};

function createDb() {
  const dbPath = getDbPath();

  let sqlite: Database.Database;
  try {
    sqlite = new Database(dbPath);
    // Enable WAL mode for better concurrent access
    sqlite.pragma("journal_mode = WAL");
  } catch (error) {
    console.error(`Failed to open database at ${dbPath}:`, error);
    throw new Error(`Cannot open database: ${dbPath}`);
  }

  return { sqlite, db: drizzle(sqlite, { schema }) };
}

// Use cached connection in development to prevent connection leaks during hot reload
if (!globalForDb.db) {
  const { sqlite, db } = createDb();
  globalForDb.sqlite = sqlite;
  globalForDb.db = db;
}

export const db = globalForDb.db!;

// Export schema for convenience
export * from "./schema";
