import { validateRequest } from "@/lib/auth";
import { db } from "@/lib/db";
import { settings } from "@/db/schema";
import { eq, and } from "drizzle-orm";
import { NextResponse } from "next/server";
import { generateId } from "@/lib/utils";

// GET /api/settings - Get all settings for current user
export async function GET() {
  try {
    const { user } = await validateRequest();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const userSettings = await db.query.settings.findMany({
      where: eq(settings.userId, user.id),
    });

    // Convert to object
    const settingsObj: Record<string, string | null> = {};
    for (const s of userSettings) {
      settingsObj[s.key] = s.value;
    }

    return NextResponse.json(settingsObj);
  } catch (error) {
    console.error("Error fetching settings:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

// POST /api/settings - Save settings for current user
export async function POST(request: Request) {
  try {
    const { user } = await validateRequest();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();

    // Upsert each setting
    for (const [key, value] of Object.entries(body)) {
      const existing = await db.query.settings.findFirst({
        where: and(eq(settings.userId, user.id), eq(settings.key, key)),
      });

      if (existing) {
        await db
          .update(settings)
          .set({ value: value as string })
          .where(eq(settings.id, existing.id));
      } else {
        await db.insert(settings).values({
          id: generateId(),
          userId: user.id,
          key,
          value: value as string,
        });
      }
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Error saving settings:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
