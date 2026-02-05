import { db } from "@/db";
import { settings } from "@/db/schema";
import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { z } from "zod";
import { locales, defaultLocale, type Locale } from "@/i18n/config";

const languageSchema = z.object({
  language: z.enum(locales as unknown as [string, ...string[]]),
});

// GET /api/settings/language - Get current language setting
export async function GET() {
  try {
    const setting = await db.query.settings.findFirst({
      where: eq(settings.key, "language"),
    });

    const language: Locale = (setting?.value as Locale) || defaultLocale;

    return NextResponse.json({ language });
  } catch (error) {
    console.error("Error fetching language setting:", error);
    return NextResponse.json({ language: defaultLocale });
  }
}

// POST /api/settings/language - Save language setting
export async function POST(request: Request) {
  try {
    const body = await request.json();

    const parseResult = languageSchema.safeParse(body);
    if (!parseResult.success) {
      return NextResponse.json(
        { error: "Invalid language" },
        { status: 400 }
      );
    }

    const { language } = parseResult.data;
    const now = new Date();

    // Upsert language setting
    const existing = await db.query.settings.findFirst({
      where: eq(settings.key, "language"),
    });

    if (existing) {
      await db
        .update(settings)
        .set({ value: language, updatedAt: now })
        .where(eq(settings.key, "language"));
    } else {
      await db.insert(settings).values({
        key: "language",
        value: language,
        category: "general",
        updatedAt: now,
      });
    }

    return NextResponse.json({ success: true, language });
  } catch (error) {
    console.error("Error saving language setting:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
