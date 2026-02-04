import { db } from "@/db";
import { llmConfig } from "@/db/schema";
import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { generateId } from "@/lib/utils";
import { z } from "zod";

// Available models by provider (internal to this route)
const MODEL_OPTIONS = {
  openai: [
    { id: "gpt-5.2", name: "GPT-5.2 (Recommended)", description: "Latest flagship model" },
    { id: "gpt-5-mini", name: "GPT-5 Mini", description: "Compact, efficient" },
    { id: "gpt-4.1", name: "GPT-4.1", description: "Enhanced GPT-4" },
    { id: "gpt-4.1-mini", name: "GPT-4.1 Mini", description: "Fast, lower cost" },
    { id: "gpt-4o", name: "GPT-4o", description: "Multimodal model" },
    { id: "gpt-4o-mini", name: "GPT-4o Mini", description: "Compact multimodal" },
  ],
  anthropic: [
    { id: "claude-opus-4-5-20251101", name: "Claude Opus 4.5 (Recommended)", description: "Most capable model" },
    { id: "claude-sonnet-4-5-20250929", name: "Claude Sonnet 4.5", description: "Balanced performance" },
    { id: "claude-haiku-4-5-20251001", name: "Claude Haiku 4.5", description: "Fast, efficient" },
  ],
  google: [
    { id: "gemini-3-pro-preview", name: "Gemini 3 Pro (Recommended)", description: "Latest pro model" },
    { id: "gemini-3-flash-preview", name: "Gemini 3 Flash", description: "Fast, capable" },
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", description: "Balanced performance" },
    { id: "gemini-2.5-flash-lite", name: "Gemini 2.5 Flash Lite", description: "Lightweight, fast" },
  ],
} as const;

const updateLlmConfigSchema = z.object({
  provider: z.enum(["openai", "anthropic", "google"]),
  model: z.string().min(1),
  isDefault: z.boolean().optional().default(true),
});

// GET /api/settings/llm - Get current LLM configuration
export async function GET() {
  try {
    // Find the default config
    const defaultConfig = await db.query.llmConfig.findFirst({
      where: eq(llmConfig.isDefault, true),
    });

    // If no default, return sensible defaults
    if (!defaultConfig) {
      return NextResponse.json({
        provider: "openai",
        model: "gpt-4o",
        isDefault: true,
        availableModels: MODEL_OPTIONS,
      });
    }

    return NextResponse.json({
      id: defaultConfig.id,
      provider: defaultConfig.provider,
      model: defaultConfig.model,
      isDefault: defaultConfig.isDefault,
      createdAt: defaultConfig.createdAt,
      updatedAt: defaultConfig.updatedAt,
      availableModels: MODEL_OPTIONS,
    });
  } catch (error) {
    console.error("Error fetching LLM config:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// POST /api/settings/llm - Update LLM configuration
export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Validate input
    const parseResult = updateLlmConfigSchema.safeParse(body);
    if (!parseResult.success) {
      const errors = parseResult.error.errors.map((e) => e.message).join(", ");
      return NextResponse.json({ error: errors }, { status: 400 });
    }

    const { provider, model, isDefault } = parseResult.data;

    // Validate model exists for provider
    const providerModels = MODEL_OPTIONS[provider as keyof typeof MODEL_OPTIONS];
    if (!providerModels.some((m) => m.id === model)) {
      return NextResponse.json(
        { error: `Invalid model "${model}" for provider "${provider}"` },
        { status: 400 }
      );
    }

    const now = new Date();

    // If setting as default, unset other defaults first
    if (isDefault) {
      await db
        .update(llmConfig)
        .set({ isDefault: false, updatedAt: now })
        .where(eq(llmConfig.isDefault, true));
    }

    // Check if config exists for this provider
    const existingConfig = await db.query.llmConfig.findFirst({
      where: eq(llmConfig.provider, provider),
    });

    if (existingConfig) {
      // Update existing
      await db
        .update(llmConfig)
        .set({
          model,
          isDefault,
          updatedAt: now,
        })
        .where(eq(llmConfig.id, existingConfig.id));

      return NextResponse.json({
        id: existingConfig.id,
        provider,
        model,
        isDefault,
        updatedAt: now,
      });
    } else {
      // Create new
      const id = generateId();
      await db.insert(llmConfig).values({
        id,
        provider,
        model,
        isDefault,
        createdAt: now,
        updatedAt: now,
      });

      return NextResponse.json({
        id,
        provider,
        model,
        isDefault,
        createdAt: now,
      });
    }
  } catch (error) {
    console.error("Error updating LLM config:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
