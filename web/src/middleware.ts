import { NextResponse, type NextRequest } from "next/server";

const TOKEN_COOKIE = "__session_token";
const TOKEN_QUERY = "__auth_token";
const TOKEN_HEADER = "x-internal-token";

// Read once at module load — stable for the process lifetime
const EXPECTED_TOKEN = process.env.INTERNAL_AUTH_TOKEN;

export function middleware(request: NextRequest) {
  // No token configured (dev mode) — skip auth
  if (!EXPECTED_TOKEN) return NextResponse.next();

  // Health check from Rust — validate via header
  const headerToken = request.headers.get(TOKEN_HEADER);
  if (headerToken === EXPECTED_TOKEN) return NextResponse.next();

  // Session cookie (steady-state hot path — check before URL parsing)
  const cookieToken = request.cookies.get(TOKEN_COOKIE)?.value;
  if (cookieToken === EXPECTED_TOKEN) return NextResponse.next();

  // Token exchange: query param → HttpOnly cookie → redirect
  const url = request.nextUrl;
  const queryToken = url.searchParams.get(TOKEN_QUERY);
  if (queryToken === EXPECTED_TOKEN) {
    url.searchParams.delete(TOKEN_QUERY);
    const response = NextResponse.redirect(url);
    response.cookies.set(TOKEN_COOKIE, EXPECTED_TOKEN, {
      httpOnly: true,
      sameSite: "strict",
      path: "/",
    });
    return response;
  }

  return new NextResponse("Forbidden", { status: 403 });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
