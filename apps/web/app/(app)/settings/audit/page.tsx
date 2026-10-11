import { ScrollText } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState, Mono, PageHeader, Panel } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { pool } from "@/lib/db";
import { requireOrg } from "@/lib/session";
import type { AuditEvent } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export const metadata: Metadata = { title: "Audit log" };

const LABELS: Record<string, string> = {
  "project.created": "created project",
  "project.settings_changed": "changed project settings",
  "project.deleted": "deleted project",
  "api_key.created": "created an API key",
  "api_key.revoked": "revoked an API key",
  "provider_credential.saved": "saved a provider credential",
  "provider_credential.deleted": "deleted a provider credential",
  "trace.deleted": "deleted a trace",
  "prompt.published": "published a prompt version",
  "prompt.activated": "activated a prompt version",
  "member.added": "added a member",
  "member.removed": "removed a member",
  "member.role_changed": "changed a member role",
  "invitation.created": "invited a member",
  "invitation.accepted": "accepted an invitation",
  "organization.created": "created the organization",
};

export default async function AuditPage({ searchParams }: PageProps<"/settings/audit">) {
  const { organizationId } = await requireOrg();
  const { before } = await searchParams;
  const beforeValue = typeof before === "string" ? before : undefined;

  let data: { items: AuditEvent[]; next_before: string | null };
  try {
    data = await api(`/orgs/${encodeURIComponent(organizationId)}/audit-events`, {
      query: { limit: 50, before: beforeValue },
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return (
        <div className="mx-auto max-w-4xl">
          <PageHeader title="Audit log" />
          <Alert tone="info">Only owners and admins can view the audit log.</Alert>
        </div>
      );
    }
    throw error;
  }

  const actorIds = [...new Set(data.items.map((e) => e.actor_user_id).filter((v): v is string => !!v))];
  const actors = new Map<string, { name: string; email: string }>();
  if (actorIds.length) {
    const { rows } = await pool().query<{ id: string; name: string; email: string }>(
      `SELECT id, name, email FROM "user" WHERE id = ANY($1::text[])`,
      [actorIds],
    );
    for (const r of rows) actors.set(r.id, r);
  }

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Audit log"
        description="Security-relevant changes in this organization: keys, members, project settings, and prompt releases."
      />
      <Panel>
        {data.items.length === 0 ? (
          <EmptyState icon={<ScrollText />} title="No events yet">
            Events appear when someone creates a project, manages API keys, or changes members.
          </EmptyState>
        ) : (
          <ol className="divide-y divide-border">
            {data.items.map((e) => {
              const actor = e.actor_user_id ? actors.get(e.actor_user_id) : null;
              const details = Object.entries(e.metadata ?? {}).filter(([, v]) => v !== null && typeof v !== "object");
              return (
                <li key={e.id} className="grid gap-1 px-4 py-3 sm:grid-cols-[168px_1fr] sm:gap-4">
                  <Mono className="text-muted-foreground">{formatDateTime(e.created_at)}</Mono>
                  <div className="min-w-0 text-sm">
                    <p>
                      <span className="font-medium">{actor?.name || actor?.email || (e.actor_user_id ? "Removed user" : "System")}</span>{" "}
                      <span className="text-muted-foreground">{LABELS[e.action] ?? e.action}</span>
                    </p>
                    <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                      <Mono>{e.action}</Mono>
                      {e.target_id ? (
                        <span>
                          {e.target_type} <Mono>{e.target_id.slice(0, 12)}</Mono>
                        </span>
                      ) : null}
                      {details.map(([k, v]) => (
                        <span key={k}>
                          {k}: <Mono>{String(v)}</Mono>
                        </span>
                      ))}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Panel>
      {data.next_before || beforeValue ? (
        <div className="mt-3 flex justify-end gap-2">
          {beforeValue ? (
            <Button asChild variant="outline" size="sm">
              <Link href="/settings/audit">Newest</Link>
            </Button>
          ) : null}
          {data.next_before ? (
            <Button asChild variant="outline" size="sm">
              <Link href={`/settings/audit?before=${encodeURIComponent(data.next_before)}`}>Older</Link>
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
