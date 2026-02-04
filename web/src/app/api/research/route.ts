import { db } from "@/db";
import { research, apiKeys } from "@/db/schema";
import { desc, eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { generateId } from "@/lib/utils";
import { runMedicalResearch } from "@/lib/agent";

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
    const {
      query,
      queryType = "pico",
      mode = "detailed",
      llmProvider = "openai",
      model,
      picoComponents,
      pccComponents,
    } = body;

    if (!query || typeof query !== "string" || query.trim().length === 0) {
      return NextResponse.json({ error: "Query is required" }, { status: 400 });
    }

    const researchId = generateId();
    const now = new Date();

    // Create research record
    await db.insert(research).values({
      id: researchId,
      query: query.trim(),
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

    const llmApiKey =
      llmProvider === "anthropic" ? keyMap.anthropic : keyMap.openai;

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

    // Start research in background (don't await)
    runMedicalResearch({
      researchId,
      query: query.trim(),
      queryType,
      llmProvider,
      model: model || (llmProvider === "anthropic" ? "claude-3-5-sonnet-20241022" : "gpt-4o"),
      apiKey: llmApiKey,
      scopusApiKey: keyMap.scopus,
      ncbiApiKey: keyMap.ncbi,
      picoComponents,
      pccComponents,
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
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
