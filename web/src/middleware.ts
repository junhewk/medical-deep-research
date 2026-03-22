import { NextResponse, type NextRequest } from "next/server";

const TOKEN_COOKIE = "__session_token";
const TOKEN_QUERY = "__auth_token";
const TOKEN_HEADER = "x-internal-token";

export function middleware(request: NextRequest) {
  const expectedToken = process.env.INTERNAL_AUTH_TOKEN;

  // No token configured (dev mode) — skip auth
  if (!expectedToken) return NextResponse.next();

  // Health check from Rust — validate via header
  const headerToken = request.headers.get(TOKEN_HEADER);
  if (headerToken === expectedToken) return NextResponse.next();

  // Token exchange: query param → HttpOnly cookie → redirect
  const url = request.nextUrl;
  const queryToken = url.searchParams.get(TOKEN_QUERY);
  if (queryToken === expectedToken) {
    url.searchParams.delete(TOKEN_QUERY);
    const response = NextResponse.redirect(url);
    response.cookies.set(TOKEN_COOKIE, expectedToken, {
      httpOnly: true,
      sameSite: "strict",
      path: "/",
    });
    return response;
  }

  // Validate session cookie
  const cookieToken = request.cookies.get(TOKEN_COOKIE)?.value;
  if (cookieToken === expectedToken) return NextResponse.next();

  return new NextResponse("Forbidden", { status: 403 });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
