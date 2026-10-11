import { Activity, ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { CostChart, LatencyChart, LatencyHistogram, VolumeChart } from "@/components/analytics/charts";
import { KindTag, StatusBadge } from "@/components/traces/status";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState, Mono, PageHeader, Panel, PanelHeader, Stat } from "@/components/ui/primitives";
import { SegmentedLinks } from "@/components/ui/segmented";
import { api } from "@/lib/api";
import { enc, getProject } from "@/lib/project";
import type { Overview } from "@/lib/types";
import { formatCost, formatDuration, formatNumber, formatPercent, formatRelative } from "@/lib/utils";

export const metadata: Metadata = { title: "Overview" };

const RANGES = { "1h": 1, "24h": 24, "7d": 24 * 7, "30d": 24 * 30 } as const;
type Range = keyof typeof RANGES;

export default async function OverviewPage({ params, searchParams }: PageProps<"/p/[projectId]">) {
  const { projectId } = await params;
  const sp = await searchParams;
  const range: Range = typeof sp.range === "string" && sp.range in RANGES ? (sp.range as Range) : "24h";
  const end = new Date();
  const start = new Date(end.getTime() - RANGES[range] * 3_600_000);

  const [{ project }, data] = await Promise.all([
    getProject(projectId),
    api<Overview>(`/projects/${enc(projectId)}/analytics/overview`, {
      query: { start: start.toISOString(), end: end.toISOString() },
    }),
  ]);
  const t = data.totals;
  const base = `/p/${projectId}`;
  const tracesHref = (extra: Record<string, string> = {}) =>
    `${base}/traces?${new URLSearchParams({ range, ...extra }).toString()}`;

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title={project.name}
        description="Volume, reliability, latency, and spend computed from the traces this project received."
        actions={
          <SegmentedLinks
            label="Time range"
            value={range}
            options={(Object.keys(RANGES) as Range[]).map((r) => ({ value: r, label: r, href: `${base}?range=${r}` }))}
          />
        }
      />

      {t.traces === 0 ? (
        <Panel>
          <EmptyState
            icon={<Activity />}
            title={`No traces in the last ${range}`}
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button asChild variant="primary">
                  <Link href={`${base}/integrations`}>Connect an integration</Link>
                </Button>
                {range !== "30d" ? (
                  <Button asChild variant="secondary">
                    <Link href={`${base}?range=30d`}>Show last 30 days</Link>
                  </Button>
                ) : null}
              </div>
            }
          >
            Instrument your agent with the Python SDK or OpenTelemetry and traces will appear here within seconds.
          </EmptyState>
        </Panel>
      ) : (
        <div className="space-y-4">
          <Panel>
            <dl className="grid grid-cols-2 divide-border sm:grid-cols-3 lg:grid-cols-6 lg:divide-x [&>div]:border-b [&>div]:border-border lg:[&>div]:border-b-0">
              <Stat label="Traces" value={formatNumber(t.traces, true)} sub={`${formatNumber(t.incomplete)} incomplete`} />
              <Stat
                label="Error rate"
                value={<span className={t.error_rate && t.error_rate > 0.05 ? "text-error" : undefined}>{formatPercent(t.error_rate)}</span>}
                sub={`${formatNumber(t.error)} failed`}
              />
              <Stat label="p50 latency" value={formatDuration(t.p50_ms)} sub={`p99 ${formatDuration(t.p99_ms)}`} />
              <Stat label="p95 latency" value={formatDuration(t.p95_ms)} />
              <Stat
                label="Tokens"
                value={formatNumber(t.total_tokens, true)}
                sub={`${formatNumber(t.input_tokens, true)} in · ${formatNumber(t.output_tokens, true)} out`}
              />
              <Stat
                label="Estimated cost"
                value={formatCost(t.cost_usd)}
                sub={t.unpriced_traces ? `${formatNumber(t.unpriced_traces)} traces unpriced` : "All usage priced"}
              />
            </dl>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Panel>
              <PanelHeader title="Traces" description="Successful and failed traces per bucket" />
              <div className="px-2 pb-2 pt-3">
                <VolumeChart series={data.series} bucket={data.range.bucket} />
              </div>
            </Panel>
            <Panel>
              <PanelHeader title="Latency distribution" description="Trace duration, log scale" />
              <div className="px-2 pb-2 pt-3">
                <LatencyHistogram buckets={data.latency_histogram} />
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader title="p95 latency" />
              <div className="px-2 pb-2 pt-3">
                <LatencyChart series={data.series} bucket={data.range.bucket} />
              </div>
            </Panel>
            <Panel>
              <PanelHeader
                title="Estimated cost"
                description={t.unpriced_traces ? "Excludes models without pricing data" : undefined}
              />
              <div className="px-2 pb-2 pt-3">
                <CostChart series={data.series} bucket={data.range.bucket} />
              </div>
            </Panel>
          </div>

          <Panel>
            <PanelHeader title="Models" description="LLM spans grouped by provider and model" />
            {data.models.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">No LLM spans with a model name in this range.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="px-4 py-2 font-medium">Model</th>
                      <th className="px-4 py-2 text-right font-medium">Calls</th>
                      <th className="px-4 py-2 text-right font-medium">Errors</th>
                      <th className="px-4 py-2 text-right font-medium">p50</th>
                      <th className="px-4 py-2 text-right font-medium">Tokens</th>
                      <th className="px-4 py-2 text-right font-medium">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.models.map((m) => (
                      <tr key={`${m.provider}:${m.model}`} className="border-b border-border last:border-0">
                        <td className="px-4 py-2.5">
                          <Link href={tracesHref({ model: m.model })} className="hover:text-accent">
                            <Mono>{m.model}</Mono>
                          </Link>
                          {m.provider ? <span className="ml-2 text-xs text-muted-foreground">{m.provider}</span> : null}
                        </td>
                        <td className="px-4 py-2.5 text-right"><Mono>{formatNumber(m.calls)}</Mono></td>
                        <td className="px-4 py-2.5 text-right">
                          <Mono className={m.errors ? "text-error" : "text-muted-foreground"}>{formatNumber(m.errors)}</Mono>
                        </td>
                        <td className="px-4 py-2.5 text-right"><Mono>{formatDuration(m.p50_ms)}</Mono></td>
                        <td className="px-4 py-2.5 text-right"><Mono>{formatNumber(m.total_tokens, true)}</Mono></td>
                        <td className="px-4 py-2.5 text-right">
                          <Mono>{formatCost(m.cost_usd)}</Mono>
                          {m.unpriced_calls ? (
                            <span className="ml-1 text-xs text-warn" title={`${m.unpriced_calls} calls without pricing`}>*</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Panel>
              <PanelHeader
                title="Top errors"
                actions={
                  <Button asChild variant="ghost" size="sm">
                    <Link href={tracesHref({ status: "error" })}>
                      Failed traces <ArrowRight />
                    </Link>
                  </Button>
                }
              />
              {data.top_errors.length === 0 ? (
                <p className="px-4 py-6 text-sm text-muted-foreground">No span errors in this range.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {data.top_errors.map((e) => (
                    <li key={`${e.kind}:${e.error_type}:${e.message}`}>
                      <Link
                        href={`${base}/traces/${enc(e.example_trace_id)}`}
                        className="group grid grid-cols-[1fr_auto] gap-x-4 px-4 py-2.5 hover:bg-muted/40"
                      >
                        <span className="min-w-0">
                          <span className="flex items-center gap-2">
                            <Mono className="text-error">{e.error_type}</Mono>
                            <KindTag kind={e.kind} />
                          </span>
                          <span className="mt-0.5 block truncate text-xs text-muted-foreground">{e.message}</span>
                        </span>
                        <span className="text-right">
                          <Mono className="block">{formatNumber(e.occurrences)}×</Mono>
                          <span className="text-xs text-muted-foreground">{formatRelative(e.last_seen)}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel>
              <PanelHeader title="Slowest traces" />
              {data.slowest.length === 0 ? (
                <p className="px-4 py-6 text-sm text-muted-foreground">No completed traces in this range.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {data.slowest.map((s) => (
                    <li key={s.trace_id}>
                      <Link
                        href={`${base}/traces/${enc(s.trace_id)}`}
                        className="flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40"
                      >
                        <span className="min-w-0 flex-1 truncate text-sm">{s.name}</span>
                        <StatusBadge status={s.status} />
                        <Mono className="w-16 text-right">{formatDuration(s.duration_ms)}</Mono>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          {data.recent_failed.length ? (
            <Panel>
              <PanelHeader title="Recent failures" />
              <ul className="divide-y divide-border">
                {data.recent_failed.map((f) => (
                  <li key={f.trace_id}>
                    <Link
                      href={`${base}/traces/${enc(f.trace_id)}`}
                      className="grid grid-cols-[1fr_auto] items-center gap-x-4 px-4 py-2.5 hover:bg-muted/40 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]"
                    >
                      <span className="truncate text-sm">{f.name}</span>
                      <span className="hidden truncate text-xs text-muted-foreground sm:block">
                        {f.error_type ? <Mono className="mr-2 text-error">{f.error_type}</Mono> : null}
                        {f.error_message}
                      </span>
                      <span className="text-xs text-muted-foreground">{formatRelative(f.start_time)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}

          {t.unpriced_traces ? (
            <Alert tone="info">
              Cost is estimated from a bundled pricing table. Models missing from that table show no cost instead of a
              guess. Point <Mono>PRICING_FILE</Mono> at your own table to price them.
            </Alert>
          ) : null}
        </div>
      )}
    </div>
  );
}
