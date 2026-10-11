import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/brand";
import { OnboardingWizard } from "@/components/onboarding/wizard";
import { api } from "@/lib/api";
import { listOrganizations, requireSession } from "@/lib/session";
import type { Onboarding, ProjectList } from "@/lib/types";

export const metadata: Metadata = { title: "Get started" };

export default async function OnboardingPage() {
  const session = await requireSession("/onboarding");
  const [state, organizations] = await Promise.all([api<Onboarding>("/onboarding"), listOrganizations()]);
  const activeOrgId = session.session.activeOrganizationId ?? null;
  const activeOrg = organizations.find((o) => o.id === activeOrgId) ?? null;

  let projects: ProjectList | null = null;
  if (activeOrg) projects = await api<ProjectList>(`/orgs/${encodeURIComponent(activeOrg.id)}/projects`);
  const canCreateProject = projects ? (projects.permissions.project ?? []).includes("create") : true;
  const canCreateKey = projects ? (projects.permissions.apiKey ?? []).includes("create") : true;

  return (
    <div className="min-h-dvh">
      <header className="flex items-center justify-between px-6 py-5">
        <Logo href={activeOrg ? "/projects" : "/"} />
        {activeOrg ? (
          <Link href="/projects" className="text-sm text-muted-foreground hover:text-foreground">
            Skip to dashboard
          </Link>
        ) : null}
      </header>
      <main className="mx-auto max-w-2xl px-4 pb-20 pt-4">
        <h1 className="text-xl font-semibold tracking-[-0.02em]">Send your first trace</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Six short steps. Your progress is saved, so you can leave and come back.
        </p>
        <OnboardingWizard
          key={activeOrg?.id ?? "no-org"}
          userName={session.user.name}
          initial={state}
          activeOrg={activeOrg ? { id: activeOrg.id, name: activeOrg.name } : null}
          projects={projects?.items.map((p) => ({ id: p.id, name: p.name })) ?? []}
          canCreateProject={canCreateProject}
          canCreateKey={canCreateKey}
        />
      </main>
    </div>
  );
}
