import { lucia } from "@/lib/auth";
import { db } from "@/lib/db";
import { users } from "@/db/schema";
import { eq } from "drizzle-orm";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { generateId } from "@/lib/utils";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { username, password } = body;

    if (
      typeof username !== "string" ||
      username.length < 3 ||
      username.length > 31 ||
      !/^[a-z0-9_-]+$/i.test(username)
    ) {
      return NextResponse.json(
        { error: "Invalid username. Use 3-31 characters (letters, numbers, _, -)" },
        { status: 400 }
      );
    }

    if (
      typeof password !== "string" ||
      password.length < 8 ||
      password.length > 255
    ) {
      return NextResponse.json(
        { error: "Password must be between 8 and 255 characters" },
        { status: 400 }
      );
    }

    const existingUser = await db.query.users.findFirst({
      where: eq(users.username, username.toLowerCase()),
    });

    if (existingUser) {
      return NextResponse.json(
        { error: "Username already taken" },
        { status: 400 }
      );
    }

    const hashedPassword = await bcrypt.hash(password, 10);
    const userId = generateId();

    await db.insert(users).values({
      id: userId,
      username: username.toLowerCase(),
      hashedPassword,
      createdAt: new Date(),
    });

    const session = await lucia.createSession(userId, {});
    const sessionCookie = lucia.createSessionCookie(session.id);

    cookies().set(
      sessionCookie.name,
      sessionCookie.value,
      sessionCookie.attributes
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Registration error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
