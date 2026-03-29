import * as schema from "./schema";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import path from "path";
import fs from "fs";

// Runtime detection: Bun has built-in SQLite, Node.js uses better-sqlite3
const isBun = typeof (globalThis as unknown as { Bun?: unknown }).Bun !== "undefined";

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

// Cache connection across hot reloads in Next.js dev mode
const globalForDb = globalThis as unknown as {
  sqlite: unknown;
  db: unknown;
};

/* eslint-disable @typescript-eslint/no-require-imports */
function createDb() {
  const dbPath = getDbPath();

  if (isBun) {
    // Dynamic require prevents webpack from resolving bun:sqlite at build time
    const { Database } = require("bun:sqlite");
    const { drizzle } = require("drizzle-orm/bun-sqlite");
    const sqlite = new Database(dbPath, { create: true });
    sqlite.exec("PRAGMA journal_mode = WAL");
    sqlite.exec("PRAGMA foreign_keys = ON");
    sqlite.exec("PRAGMA busy_timeout = 5000");
    return { sqlite, db: drizzle(sqlite, { schema }) };
  }

  const Database = require("better-sqlite3");
  const { drizzle } = require("drizzle-orm/better-sqlite3");
  const sqlite = new Database(dbPath);
  sqlite.pragma("journal_mode = WAL");
  sqlite.pragma("foreign_keys = ON");
  sqlite.pragma("busy_timeout = 5000");
  return { sqlite, db: drizzle(sqlite, { schema }) };
}
/* eslint-enable @typescript-eslint/no-require-imports */

// Lazy initialization — avoid opening the database at module load time,
// which causes SQLITE_BUSY errors when Next.js build spawns multiple workers.
function getDb(): BetterSQLite3Database<typeof schema> {
  if (!globalForDb.db) {
    const { sqlite, db } = createDb();
    globalForDb.sqlite = sqlite;
    globalForDb.db = db;
  }
  return globalForDb.db as BetterSQLite3Database<typeof schema>;
}

export const db = new Proxy({} as BetterSQLite3Database<typeof schema>, {
  get(_target, prop, receiver) {
    const real = getDb();
    const value = Reflect.get(real, prop, receiver);
    return typeof value === "function" ? value.bind(real) : value;
  },
});

// Export schema for convenience
export * from "./schema";
