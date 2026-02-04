import { db } from "@/db";
import { apiKeys } from "@/db/schema";
import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { generateId } from "@/lib/utils";

// GET /api/settings/api-keys - List all API keys (masked)
export async function GET() {
  try {
    const keys = await db.query.apiKeys.findMany();

    // Mask API keys for security
    const maskedKeys = keys.map((key) => ({
      id: key.id,
      service: key.service,
      apiKey: maskApiKey(key.apiKey),
      createdAt: key.createdAt,
      updatedAt: key.updatedAt,
    }));

    return NextResponse.json(maskedKeys);
  } catch (error) {
    console.error("Error fetching API keys:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

// POST /api/settings/api-keys - Add or update API key
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { service, apiKey } = body;

    if (!service || !apiKey) {
      return NextResponse.json({ error: "Service and API key are required" }, { status: 400 });
    }

    const validServices = ["openai", "anthropic", "scopus", "ncbi", "cochrane"];
    if (!validServices.includes(service)) {
      return NextResponse.json(
        { error: `Invalid service. Must be one of: ${validServices.join(", ")}` },
        { status: 400 }
      );
    }

    const now = new Date();

    // Check if key exists for this service
    const existing = await db.query.apiKeys.findFirst({
      where: eq(apiKeys.service, service),
    });

    if (existing) {
      // Update existing
      await db
        .update(apiKeys)
        .set({ apiKey, updatedAt: now })
        .where(eq(apiKeys.id, existing.id));

      return NextResponse.json({
        id: existing.id,
        service,
        apiKey: maskApiKey(apiKey),
        message: "API key updated successfully",
      });
    } else {
      // Create new
      const id = generateId();
      await db.insert(apiKeys).values({
        id,
        service,
        apiKey,
        createdAt: now,
        updatedAt: now,
      });

      return NextResponse.json({
        id,
        service,
        apiKey: maskApiKey(apiKey),
        message: "API key added successfully",
      });
    }
  } catch (error) {
    console.error("Error saving API key:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

// DELETE /api/settings/api-keys - Delete API key
export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const service = searchParams.get("service");

    if (!service) {
      return NextResponse.json({ error: "Service parameter is required" }, { status: 400 });
    }

    await db.delete(apiKeys).where(eq(apiKeys.service, service));

    return NextResponse.json({ success: true, message: "API key deleted successfully" });
  } catch (error) {
    console.error("Error deleting API key:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

function maskApiKey(key: string): string {
  if (key.length <= 8) {
    return "*".repeat(key.length);
  }
  return key.substring(0, 4) + "*".repeat(key.length - 8) + key.substring(key.length - 4);
}
