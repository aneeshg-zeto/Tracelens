import "server-only";

import { SignJWT } from "jose";
import { notFound } from "next/navigation";
import { env } from "@/lib/env";
import { requireSession } from "@/lib/session";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const encoder = new TextEncoder();

/** 60-second HS256 token identifying the user and their active organization to the API. */
export async function mintInternalToken(userId: string, organizationId: string | null | undefined) {
  const e = env();
  const jwt = new SignJWT(organizationId ? { org_id: organizationId } : {})
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setIssuer("tracelens-web")
    .setAudience("tracelens-api")
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime("60s");
  return jwt.sign(encoder.encode(e.INTERNAL_JWT_SECRET));
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export async function backendFetch(
  path: string,
  { method = "GET", body, query, token }: { method?: string; body?: unknown; query?: Query; token: string },
): Promise<Response> {
  const url = `${env().TRACELENS_API_URL}/api/v1${path}${buildQuery(query)}`;
  try {
    return await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        "X-TraceLens-Internal-Token": token,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(503, "api_unreachable", "The TraceLens API is unreachable. Check that it is running.");
  }
}

export async function parseResponse<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    throw new ApiError(res.status, err?.code ?? "error", err?.message ?? `Request failed (${res.status})`);
  }
  return data as T;
}

/** Calls the FastAPI backend as the signed-in user. */
export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Query } = {},
): Promise<T> {
  const session = await requireSession();
  const token = await mintInternalToken(session.user.id, session.session.activeOrganizationId);
  return parseResponse<T>(await backendFetch(path, { ...options, token }));
}

/** Like `api`, but a 404 renders the not-found page (resources from other orgs look absent). */
export async function apiOrNotFound<T>(path: string, options: { query?: Query } = {}): Promise<T> {
  try {
    return await api<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
