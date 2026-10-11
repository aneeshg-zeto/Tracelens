import type { Metadata } from "next";
import {
  ApiKeysSection,
  DangerZone,
  GeneralSection,
  PrivacySection,
  ProvidersSection,
} from "@/components/projects/project-settings";
import { Alert, PageHeader } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { can, enc, getProject } from "@/lib/project";
import type { ApiKey, ProviderCredentials } from "@/lib/types";

export const metadata: Metadata = { title: "Project settings" };

const SECTIONS = [
  { id: "general", label: "General" },
  { id: "api-keys", label: "API keys" },
  { id: "privacy", label: "Privacy and retention" },
  { id: "providers", label: "AI providers" },
  { id: "danger", label: "Delete project" },
];

export default async function ProjectSettingsPage({ params, searchParams }: PageProps<"/p/[projectId]/settings">) {
  const { projectId } = await params;
  const sp = await searchParams;
  const { project, permissions, role } = await getProject(projectId);
  const canUpdate = can(permissions, "project", "update");
  const canKeys = can(permissions, "apiKey", "create");
  const canDelete = can(permissions, "project", "delete");
  const canProviders = can(permissions, "integration", "update");

  const [keys, credentials] = await Promise.all([
    canKeys ? api<ApiKey[]>(`/projects/${enc(projectId)}/api-keys`) : Promise.resolve(null),
    api<ProviderCredentials>(`/projects/${enc(projectId)}/provider-credentials`),
  ]);
  const sections = SECTIONS.filter((s) => (s.id === "api-keys" ? canKeys : s.id === "danger" ? canDelete : true));

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Project settings" description={`Configuration for ${project.name}.`} />
      {sp.created ? (
        <Alert tone="ok" title="Project created" className="mb-4">
          Create an API key below, then send your first trace with the Python SDK or OpenTelemetry.
        </Alert>
      ) : null}
      {!canUpdate ? (
        <Alert tone="info" className="mb-4">
          Your role is <strong className="text-foreground">{role}</strong>. Only owners and admins can change project
          settings.
        </Alert>
      ) : null}
      <div className="grid items-start gap-8 lg:grid-cols-[160px_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="hidden lg:sticky lg:top-6 lg:block">
          <ul className="space-y-0.5 text-sm">
            {sections.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className="block rounded-md px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-6">
          <GeneralSection project={project} canUpdate={canUpdate} />
          {keys ? <ApiKeysSection projectId={projectId} keys={keys} autoOpen={!!sp.created && keys.length === 0} /> : null}
          <PrivacySection project={project} canUpdate={canUpdate} />
          <ProvidersSection projectId={projectId} data={credentials} canUpdate={canProviders} />
          {canDelete ? <DangerZone project={project} /> : null}
        </div>
      </div>
    </div>
  );
}
