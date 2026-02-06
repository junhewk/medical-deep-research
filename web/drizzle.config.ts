import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./src/db/schema.ts",
  dialect: "sqlite",
  dbCredentials: {
    url: process.env.DATABASE_PATH || "./data/medical-deep-research.db",
  },
  // Use verbose mode for better debugging
  verbose: true,
  // Strict mode ensures schema changes are intentional
  strict: false,
});
