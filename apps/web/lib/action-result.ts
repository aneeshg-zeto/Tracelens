import "server-only";

import { unstable_rethrow } from "next/navigation";
import { ApiError } from "@/lib/api";

export type ActionResult<T = undefined> = { ok: true; data: T } | { ok: false; error: string; code?: string };

/** Runs a server-action body and converts failures into a serializable result. */
export async function run<T>(fn: () => Promise<T>): Promise<ActionResult<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (error) {
    unstable_rethrow(error);
    if (error instanceof ApiError) return { ok: false, error: error.message, code: error.code };
    console.error("[tracelens] server action failed", error);
    return { ok: false, error: "Something went wrong. Try again." };
  }
}
