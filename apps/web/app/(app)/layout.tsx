import { redirect } from "next/navigation";
import { AppSidebar } from "@/components/shell/sidebar";
import { api, ApiError } from "@/lib/api";
import { listOrganizations, requireOrg } from "@/lib/session";
import type { ProjectList } from "@/lib/types";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await requireOrg();
  const organizations = await listOrganizations();
  const activeOrg = organizations.find((o) => o.id === session.organizationId);
  if (!activeOrg) redirect("/onboarding");

  let projects: ProjectList;
  try {
    projects = await api<ProjectList>(`/orgs/${encodeURIComponent(activeOrg.id)}/projects`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) redirect("/onboarding");
    throw error;
  }

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_1fr]">
      <AppSidebar
        user={{ name: session.user.name, email: session.user.email, image: session.user.image ?? null }}
        organizations={organizations.map((o) => ({ id: o.id, name: o.name }))}
        activeOrg={{ id: activeOrg.id, name: activeOrg.name }}
        role={projects.role}
        permissions={projects.permissions}
        projects={projects.items.map((p) => ({ id: p.id, name: p.name }))}
      />
      <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
