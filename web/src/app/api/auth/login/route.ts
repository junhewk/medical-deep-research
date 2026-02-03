import { lucia } from "@/lib/auth";
import { db } from "@/lib/db";
import { users } from "@/db/schema";
import { eq } from "drizzle-orm";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { username, password } = body;

    if (
      typeof username !== "string" ||
      username.length < 3 ||
      username.length > 31
    ) {
      return NextResponse.json(
        { error: "Invalid username" },
        { status: 400 }
      );
    }

    if (
      typeof password !== "string" ||
      password.length < 8 ||
      password.length > 255
    ) {
      return NextResponse.json(
        { error: "Invalid password" },
        { status: 400 }
      );
    }

    const existingUser = await db.query.users.findFirst({
      where: eq(users.username, username.toLowerCase()),
    });

    if (!existingUser) {
      return NextResponse.json(
        { error: "Incorrect username or password" },
        { status: 400 }
      );
    }

    const validPassword = await bcrypt.compare(
      password,
      existingUser.hashedPassword
    );

    if (!validPassword) {
      return NextResponse.json(
        { error: "Incorrect username or password" },
        { status: 400 }
      );
    }

    const session = await lucia.createSession(existingUser.id, {});
    const sessionCookie = lucia.createSessionCookie(session.id);

    cookies().set(
      sessionCookie.name,
      sessionCookie.value,
      sessionCookie.attributes
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Login error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
