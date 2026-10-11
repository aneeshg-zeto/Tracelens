import { NextResponse, type NextRequest } from "next/server";
import { ApiError, backendFetch, mintInternalToken } from "@/lib/api";
import { getSession } from "@/lib/session";

/**
 * Read-only pass-through for client components (lazy span detail, polling).
 * The backend authorizes every request from the signed token; only GET is
 * exposed so this route cannot be used for cross-site state changes.
 */
export async function GET(request: NextRequest, ctx: RouteContext<"/api/backend/[...path]">) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: { code: "unauthorized", message: "Sign in required" } }, { status: 401 });
  }
  const { path } = await ctx.params;
  if (path.some((segment) => segment === "." || segment === ".." || segment === "")) {
    return NextResponse.json({ error: { code: "invalid_path", message: "Invalid path" } }, { status: 400 });
  }
  const query: Record<string, string[]> = {};
  request.nextUrl.searchParams.forEach((value, key) => {
    (query[key] ??= []).push(value);
  });
  try {
    const token = await mintInternalToken(session.user.id, session.session.activeOrganizationId);
    const res = await backendFetch(`/${path.map(encodeURIComponent).join("/")}`, { token, query });
    const body = await res.text();
    return new NextResponse(body || null, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
