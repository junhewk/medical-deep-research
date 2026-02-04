import { db } from "@/db";
import { settings } from "@/db/schema";
import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";

// GET /api/settings - Get all settings
export async function GET() {
  try {
    const allSettings = await db.query.settings.findMany();

    // Convert to object
    const settingsObj: Record<string, string> = {};
    for (const s of allSettings) {
      settingsObj[s.key] = s.value;
    }

    return NextResponse.json(settingsObj);
  } catch (error) {
    console.error("Error fetching settings:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

// POST /api/settings - Save settings
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const now = new Date();

    // Upsert each setting
    for (const [key, value] of Object.entries(body)) {
      const existing = await db.query.settings.findFirst({
        where: eq(settings.key, key),
      });

      if (existing) {
        await db
          .update(settings)
          .set({ value: value as string, updatedAt: now })
          .where(eq(settings.key, key));
      } else {
        await db.insert(settings).values({
          key,
          value: value as string,
          updatedAt: now,
        });
      }
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Error saving settings:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
