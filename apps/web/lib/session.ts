import "server-only";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { auth } from "@/lib/auth";

export const getSession = cache(async () => auth.api.getSession({ headers: await headers() }));

export async function requireSession(next?: string) {
  const session = await getSession();
  if (!session) redirect(next ? `/sign-in?next=${encodeURIComponent(next)}` : "/sign-in");
  return session;
}

/** Session with an active organization; users without one finish onboarding first. */
export async function requireOrg() {
  const session = await requireSession();
  const organizationId = session.session.activeOrganizationId;
  if (!organizationId) redirect("/onboarding");
  return { ...session, organizationId };
}

export const getActiveMember = cache(async () => {
  try {
    return await auth.api.getActiveMember({ headers: await headers() });
  } catch {
    return null;
  }
});

export const listOrganizations = cache(async () => auth.api.listOrganizations({ headers: await headers() }));
