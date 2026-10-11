import { FolderKanban } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { CreateProjectButton } from "@/components/projects/create-project";
import { Button } from "@/components/ui/button";
import { EmptyState, Mono, PageHeader, Panel } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { requireOrg } from "@/lib/session";
import type { ProjectList } from "@/lib/types";
import { formatNumber, formatRelative } from "@/lib/utils";

export const metadata: Metadata = { title: "Projects" };

export default async function ProjectsPage() {
  const { organizationId } = await requireOrg();
  const data = await api<ProjectList>(`/orgs/${encodeURIComponent(organizationId)}/projects`);
  const canCreate = (data.permissions.project ?? []).includes("create");

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Projects"
        description="Each project has its own API keys, traces, privacy settings, and retention."
        actions={canCreate ? <CreateProjectButton orgId={organizationId} /> : null}
      />
      <Panel>
        {data.items.length === 0 ? (
          <EmptyState
            icon={<FolderKanban />}
            title="No projects yet"
            action={
              canCreate ? (
                <Button asChild variant="primary">
                  <Link href="/onboarding">Start guided setup</Link>
                </Button>
              ) : null
            }
          >
            {canCreate
              ? "Create a project to get an API key and send your first trace."
              : "An owner or admin needs to create a project before you can view traces."}
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 text-right font-medium">Traces</th>
                  <th className="px-4 py-2.5 font-medium">Last trace</th>
                  <th className="hidden px-4 py-2.5 font-medium sm:table-cell">Retention</th>
                  <th className="hidden px-4 py-2.5 font-medium md:table-cell">Payloads</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id} className="group border-b border-border last:border-0 hover:bg-muted/40">
                    <td className="px-4 py-3">
                      <Link href={`/p/${p.id}`} className="font-medium text-foreground group-hover:text-accent">
                        {p.name}
                      </Link>
                      {p.slug !== p.name ? <Mono className="ml-2 text-muted-foreground">{p.slug}</Mono> : null}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Mono>{formatNumber(p.trace_count)}</Mono>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {p.last_trace_at ? formatRelative(p.last_trace_at) : <span className="text-muted-foreground/70">Never</span>}
                    </td>
                    <td className="hidden px-4 py-3 text-muted-foreground sm:table-cell">
                      <Mono>{p.retention_days}d</Mono>
                    </td>
                    <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
                      {p.capture_payloads ? "Captured" : "Metadata only"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
