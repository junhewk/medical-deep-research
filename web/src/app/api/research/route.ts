import { validateRequest } from "@/lib/auth";
import { db } from "@/lib/db";
import { research } from "@/db/schema";
import { eq, desc } from "drizzle-orm";
import { NextResponse } from "next/server";
import { generateId } from "@/lib/utils";

const PYTHON_API_URL = process.env.PYTHON_API_URL || "http://localhost:8000";

// GET /api/research - List all research for current user
export async function GET() {
  try {
    const { user } = await validateRequest();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const items = await db.query.research.findMany({
      where: eq(research.userId, user.id),
      orderBy: [desc(research.createdAt)],
    });

    return NextResponse.json(items);
  } catch (error) {
    console.error("Error fetching research:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// POST /api/research - Start new research
export async function POST(request: Request) {
  try {
    const { user } = await validateRequest();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const { query, llmProvider, model } = body;

    if (!query || typeof query !== "string" || query.trim().length === 0) {
      return NextResponse.json(
        { error: "Query is required" },
        { status: 400 }
      );
    }

    const researchId = generateId();

    // Create research record in database
    await db.insert(research).values({
      id: researchId,
      userId: user.id,
      query: query.trim(),
      status: "pending",
      progress: 0,
      createdAt: new Date(),
    });

    // Start research in Python backend
    try {
      const response = await fetch(`${PYTHON_API_URL}/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          research_id: researchId,
          query: query.trim(),
          llm_provider: llmProvider || "openai",
          model: model || "gpt-4o",
          user_id: user.id,
        }),
      });

      if (!response.ok) {
        // Update status to failed
        await db
          .update(research)
          .set({ status: "failed" })
          .where(eq(research.id, researchId));

        const error = await response.json();
        return NextResponse.json(
          { error: error.detail || "Failed to start research" },
          { status: 500 }
        );
      }

      // Update status to running
      await db
        .update(research)
        .set({ status: "running" })
        .where(eq(research.id, researchId));
    } catch (fetchError) {
      console.error("Error calling Python API:", fetchError);
      // Mark as failed but still return the ID for debugging
      await db
        .update(research)
        .set({ status: "failed" })
        .where(eq(research.id, researchId));
    }

    return NextResponse.json({ research_id: researchId });
  } catch (error) {
    console.error("Error creating research:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
