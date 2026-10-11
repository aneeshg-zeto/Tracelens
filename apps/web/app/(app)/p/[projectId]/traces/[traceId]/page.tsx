import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { DeleteTraceButton } from "@/components/traces/delete-trace";
import { StatusBadge } from "@/components/traces/status";
import { TraceDiagnosis } from "@/components/traces/trace-diagnosis";
import { TraceExplorer } from "@/components/traces/trace-explorer";
import { CopyButton } from "@/components/ui/code-block";
import { Alert, Badge, Mono } from "@/components/ui/primitives";
import { api, apiOrNotFound } from "@/lib/api";
import { can, enc, getProject } from "@/lib/project";
import type { Finding, Investigation, TraceDetail } from "@/lib/types";
import { formatCost, formatDateTime, formatDuration, formatNumber } from "@/lib/utils";

export async function generateMetadata({ params }: PageProps<"/p/[projectId]/traces/[traceId]">): Promise<Metadata> {
  const { traceId } = await params;
  return { title: `Trace ${traceId.slice(0, 12)}` };
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate text-sm">{children}</dd>
    </div>
  );
}

export default async function TraceDetailPage({ params }: PageProps<"/p/[projectId]/traces/[traceId]">) {
  const { projectId, traceId } = await params;
  const base = `/projects/${enc(projectId)}/traces/${enc(traceId)}`;
  const [{ project, permissions }, detail] = await Promise.all([
    getProject(projectId),
    apiOrNotFound<TraceDetail>(base),
  ]);
  const [diagnosis, investigations] = await Promise.all([
    api<{ findings: Finding[] }>(`${base}/diagnosis`),
    api<Investigation[]>(`${base}/investigations`),
  ]);
  const t = detail.trace;
  const list = `/p/${projectId}/traces`;
  const filterLink = (key: string, value: string) => `${list}?${new URLSearchParams({ [key]: value, range: "all" })}`;

  return (
    <div className="mx-auto max-w-[1440px] space-y-4">
      <div>
        <Link href={list} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Traces
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-lg font-semibold tracking-[-0.01em]">{t.name}</h1>
              <StatusBadge status={t.status} />
              {t.source !== "sdk" ? <Badge className="font-mono">{t.source}</Badge> : null}
            </div>
            <div className="mt-1 flex items-center gap-1">
              <Mono className="truncate text-muted-foreground">{t.trace_id}</Mono>
              <CopyButton value={t.trace_id} label="Copy trace ID" className="[&>span]:sr-only" />
            </div>
          </div>
          {can(permissions, "trace", "delete") ? <DeleteTraceButton projectId={projectId} traceId={t.trace_id} /> : null}
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border border-border bg-surface px-4 py-3 sm:grid-cols-4 lg:grid-cols-8">
          <Meta label="Started">
            <span title={t.start_time}>{formatDateTime(t.start_time)}</span>
          </Meta>
          <Meta label="Duration">
            <Mono>{formatDuration(t.duration_ms)}</Mono>
          </Meta>
          <Meta label="Spans">
            <Mono>
              {formatNumber(t.span_count)}
              {t.error_span_count ? <span className="text-error"> · {t.error_span_count} failed</span> : null}
            </Mono>
          </Meta>
          <Meta label="Tokens">
            <Mono>{formatNumber(t.total_tokens)}</Mono>
          </Meta>
          <Meta label="Cost">
            {t.cost_status === "unavailable" ? (
              <span className="text-xs text-muted-foreground">Unpriced model</span>
            ) : (
              <Mono>
                {formatCost(t.cost_usd)}
                {t.cost_status === "partial" ? <span className="text-warn" title="Some spans have no pricing">*</span> : null}
              </Mono>
            )}
          </Meta>
          <Meta label="Environment">
            {t.environment ? <Link href={filterLink("environment", t.environment)} className="hover:text-accent">{t.environment}</Link> : "—"}
            {t.release ? <Mono className="ml-1.5 text-muted-foreground">{t.release}</Mono> : null}
          </Meta>
          <Meta label="User">
            {t.user_id ? (
              <Link href={filterLink("user_id", t.user_id)} className="font-mono text-[12px] hover:text-accent">
                {t.user_id}
              </Link>
            ) : (
              "—"
            )}
          </Meta>
          <Meta label="Session">
            {t.session_id ? (
              <Link href={filterLink("session_id", t.session_id)} className="font-mono text-[12px] hover:text-accent">
                {t.session_id}
              </Link>
            ) : (
              "—"
            )}
          </Meta>
        </dl>
        {t.tags.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {t.tags.map((tag) => (
              <Link key={tag} href={filterLink("tag", tag)}>
                <Badge className="font-mono hover:border-accent/60 hover:text-foreground">{tag}</Badge>
              </Link>
            ))}
          </div>
        ) : null}
      </div>

      {t.status === "error" && (t.error_type || t.error_message) ? (
        <Alert tone="error" title={t.error_type ?? "Trace failed"}>
          {t.error_message}
        </Alert>
      ) : null}
      {t.status === "incomplete" ? (
        <Alert tone="warn" title="Incomplete trace">
          The trace has not reported an end time yet. It may still be running, or the process exited before flushing.
        </Alert>
      ) : null}

      <TraceExplorer projectId={projectId} detail={detail} capturePayloads={project.capture_payloads} />

      <TraceDiagnosis
        projectId={projectId}
        traceId={t.trace_id}
        findings={diagnosis.findings}
        initialInvestigations={investigations}
        spans={detail.spans}
        canRun={can(permissions, "investigation", "run")}
        canConfigure={can(permissions, "integration", "update")}
      />
    </div>
  );
}
