import { db } from "@/db";
import { research, apiKeys, llmConfig, settings } from "@/db/schema";
import { desc, eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { generateId } from "@/lib/utils";
import { runMedicalResearch } from "@/lib/agent";
import { z } from "zod";
import { defaultLocale, type Locale } from "@/i18n/config";

// Input validation schema
const createResearchSchema = z.object({
  query: z.string().min(1, "Query is required").max(5000),
  queryType: z.enum(["pico", "pcc", "free"]).default("pico"),
  mode: z.enum(["quick", "detailed"]).default("detailed"),
  llmProvider: z.enum(["openai", "anthropic", "google"]).default("openai"),
  model: z.string().optional(),
  picoComponents: z.object({
    population: z.string().optional(),
    intervention: z.string().optional(),
    comparison: z.string().optional(),
    outcome: z.string().optional(),
  }).optional(),
  pccComponents: z.object({
    population: z.string().optional(),
    concept: z.string().optional(),
    context: z.string().optional(),
  }).optional(),
});

// GET /api/research - List all research
export async function GET() {
  try {
    const items = await db.query.research.findMany({
      orderBy: [desc(research.createdAt)],
    });

    return NextResponse.json(items);
  } catch (error) {
    console.error("Error fetching research:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

// POST /api/research - Start new research
export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const parseResult = createResearchSchema.safeParse(body);
    if (!parseResult.success) {
      const errors = parseResult.error.errors.map(e => e.message).join(", ");
      return NextResponse.json({ error: errors }, { status: 400 });
    }

    const {
      query,
      queryType,
      mode,
      llmProvider: requestedProvider,
      model: requestedModel,
      picoComponents,
      pccComponents,
    } = parseResult.data;

    const researchId = generateId();
    const now = new Date();

    // Create research record
    await db.insert(research).values({
      id: researchId,
      query: query,
      queryType,
      mode,
      status: "pending",
      progress: 0,
      createdAt: now,
    });

    // Get API keys from database
    const keys = await db.query.apiKeys.findMany();
    const keyMap = keys.reduce(
      (acc, k) => {
        acc[k.service] = k.apiKey;
        return acc;
      },
      {} as Record<string, string>
    );

    // Get default LLM config if not specified in request
    const defaultLlmConfig = await db.query.llmConfig.findFirst({
      where: eq(llmConfig.isDefault, true),
    });

    const llmProvider: "openai" | "anthropic" | "google" = requestedProvider
      || (defaultLlmConfig?.provider as "openai" | "anthropic" | "google")
      || "openai";

    const getDefaultModel = (provider: string) => {
      if (provider === "anthropic") return "claude-opus-4-5-20251101";
      if (provider === "google") return "gemini-3-pro-preview";
      return "gpt-5.2";
    };

    const model: string = requestedModel
      || defaultLlmConfig?.model
      || getDefaultModel(llmProvider);

    const getApiKey = (provider: string) => {
      if (provider === "anthropic") return keyMap.anthropic;
      if (provider === "google") return keyMap.google;
      return keyMap.openai;
    };

    const llmApiKey = getApiKey(llmProvider);

    if (!llmApiKey) {
      await db.update(research).set({ status: "failed", errorMessage: `${llmProvider} API key not configured` }).where(eq(research.id, researchId));
      return NextResponse.json(
        { error: `${llmProvider} API key not configured. Please add it in Settings > API Keys.` },
        { status: 400 }
      );
    }

    // Update status to running
    await db
      .update(research)
      .set({ status: "running", startedAt: now })
      .where(eq(research.id, researchId));

    // Fetch language setting
    const languageSetting = await db.query.settings.findFirst({
      where: eq(settings.key, "language"),
    });
    const language: Locale = (languageSetting?.value as Locale) || defaultLocale;

    // Start research in background (don't await)
    // Note: Population validator now uses the user's configured LLM provider (apiKey)
    // instead of a separate OpenAI key
    runMedicalResearch({
      researchId,
      query,
      queryType,
      llmProvider,
      model,
      apiKey: llmApiKey,
      scopusApiKey: keyMap.scopus,
      ncbiApiKey: keyMap.ncbi,
      picoComponents,
      pccComponents,
      language,
    }).catch(async (error) => {
      console.error("Research error:", error);
      await db
        .update(research)
        .set({
          status: "failed",
          errorMessage: error instanceof Error ? error.message : "Unknown error",
        })
        .where(eq(research.id, researchId));
    });

    return NextResponse.json({ research_id: researchId });
  } catch (error) {
    console.error("Error creating research:", error);
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: `Internal server error: ${message}` }, { status: 500 });
  }
}
