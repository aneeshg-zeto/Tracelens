import { ArrowRight, ListTree } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { TraceFilters } from "@/components/traces/trace-filters";
import { TraceTable } from "@/components/traces/trace-table";
import { Button } from "@/components/ui/button";
import { EmptyState, PageHeader, Panel } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { enc } from "@/lib/project";
import { isTraceRange, RANGE_HOURS } from "@/lib/trace-ranges";
import type { TraceList } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

export const metadata: Metadata = { title: "Traces" };

const PASS_THROUGH = [
  "q",
  "model",
  "provider",
  "environment",
  "release",
  "user_id",
  "session_id",
  "tag",
  "min_duration_ms",
  "max_duration_ms",
  "sort",
  "order",
  "cursor",
] as const;

function hoursAgo(hours: number) {
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

export default async function TracesPage({ params, searchParams }: PageProps<"/p/[projectId]/traces">) {
  const { projectId } = await params;
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : Array.isArray(sp[k]) ? sp[k][0] : undefined);

  const query: Record<string, string | string[]> = { limit: "50" };
  for (const k of PASS_THROUGH) {
    const v = one(k);
    if (v) query[k] = v;
  }
  const statuses = ([] as string[]).concat(sp.status ?? []).filter((s) => ["ok", "error", "incomplete"].includes(s));
  if (statuses.length) query.status = statuses;
  const requested = one("range");
  const range = isTraceRange(requested) ? requested : "24h";
  if (range !== "all") query.start = hoursAgo(RANGE_HOURS[range]);

  const [data, options] = await Promise.all([
    api<TraceList>(`/projects/${enc(projectId)}/traces`, { query }),
    api<{ environments: string[]; models: string[] }>(`/projects/${enc(projectId)}/trace-filters`),
  ]);

  const filtered = Object.keys(query).some((k) => !["limit", "start", "sort", "order", "cursor"].includes(k));
  const nextParams = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) for (const item of ([] as string[]).concat(v ?? [])) nextParams.append(k, item);
  const firstParams = new URLSearchParams(nextParams);
  firstParams.delete("cursor");
  if (data.next_cursor) nextParams.set("cursor", data.next_cursor);

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title="Traces"
        description={
          <>
            <span className="font-mono tabular">
              {formatNumber(data.total)}
              {data.total_capped ? "+" : ""}
            </span>{" "}
            {data.total === 1 ? "trace matches" : "traces match"} the current filters.
          </>
        }
      />
      <div className="mb-3">
        <TraceFilters options={options} />
      </div>
      <Panel>
        {data.items.length === 0 ? (
          <EmptyState
            icon={<ListTree />}
            title={filtered ? "No traces match these filters" : "No traces in this time range"}
            action={
              filtered ? (
                <Button asChild variant="secondary">
                  <Link href={`/p/${projectId}/traces?range=${range}`}>Clear filters</Link>
                </Button>
              ) : (
                <div className="flex flex-wrap justify-center gap-2">
                  {range !== "all" ? (
                    <Button asChild variant="secondary">
                      <Link href={`/p/${projectId}/traces?range=all`}>Show all time</Link>
                    </Button>
                  ) : null}
                  <Button asChild variant="primary">
                    <Link href={`/p/${projectId}/integrations`}>Set up an integration</Link>
                  </Button>
                </div>
              )
            }
          >
            {filtered
              ? "Try removing a filter or widening the time range."
              : "Traces appear here a few seconds after your application sends them."}
          </EmptyState>
        ) : (
          <TraceTable projectId={projectId} items={data.items} />
        )}
      </Panel>
      {sp.cursor || data.next_cursor ? (
        <nav aria-label="Pagination" className="mt-3 flex items-center justify-end gap-2">
          {sp.cursor ? (
            <Button asChild variant="ghost" size="sm">
              <Link href={`?${firstParams.toString()}`}>Back to first page</Link>
            </Button>
          ) : null}
          {data.next_cursor ? (
            <Button asChild variant="secondary" size="sm">
              <Link href={`?${nextParams.toString()}`}>
                Next page <ArrowRight />
              </Link>
            </Button>
          ) : null}
        </nav>
      ) : null}
    </div>
  );
}
