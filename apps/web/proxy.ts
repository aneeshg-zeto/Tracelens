import { getSessionCookie } from "better-auth/cookies";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Optimistic redirect only: the presence of a session cookie is not proof of a
 * valid session. Every page and API call re-validates the session server-side.
 */
export function proxy(request: NextRequest) {
  if (getSessionCookie(request)) return NextResponse.next();
  const verifyError = request.nextUrl.searchParams.get("error");
  if (request.nextUrl.pathname === "/onboarding" && verifyError) {
    const url = new URL("/verify-email", request.url);
    url.searchParams.set("error", verifyError);
    return NextResponse.redirect(url);
  }
  const url = new URL("/sign-in", request.url);
  url.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/projects/:path*", "/p/:path*", "/settings/:path*", "/onboarding/:path*", "/accept-invitation/:path*"],
};
