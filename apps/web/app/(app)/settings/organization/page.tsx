import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { OrganizationSettings } from "@/components/org/organization-settings";
import { PageHeader } from "@/components/ui/primitives";
import { auth } from "@/lib/auth";
import { getActiveMember, requireOrg } from "@/lib/session";

export const metadata: Metadata = { title: "Members" };

export default async function OrganizationSettingsPage() {
  const session = await requireOrg();
  const [org, me] = await Promise.all([
    auth.api.getFullOrganization({ headers: await headers(), query: { organizationId: session.organizationId } }),
    getActiveMember(),
  ]);
  if (!org || !me) redirect("/onboarding");

  const roles = me.role.split(",").map((r) => r.trim());
  const canManage = roles.includes("owner") || roles.includes("admin");

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title={org.name} description="Members, roles, and pending invitations for this organization." />
      <OrganizationSettings
        org={{ id: org.id, name: org.name, slug: org.slug }}
        currentUserId={session.user.id}
        myRole={me.role}
        canManage={canManage}
        isOwner={roles.includes("owner")}
        members={org.members.map((m) => ({
          id: m.id,
          userId: m.userId,
          role: m.role,
          createdAt: new Date(m.createdAt).toISOString(),
          name: m.user.name,
          email: m.user.email,
        }))}
        invitations={(org.invitations ?? [])
          .filter((i) => i.status === "pending")
          .map((i) => ({ id: i.id, email: i.email, role: i.role ?? "member", expiresAt: new Date(i.expiresAt).toISOString() }))}
      />
    </div>
  );
}
