"use client";

import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { StatusBadge } from "@/components/traces/status";
import { Badge, Mono } from "@/components/ui/primitives";
import type { TraceSummary } from "@/lib/types";
import { cn, formatCost, formatDateTime, formatDuration, formatNumber, formatRelative } from "@/lib/utils";

const features = tableFeatures({});
const col = createColumnHelper<typeof features, TraceSummary>();

type SortKey = "start_time" | "duration_ms" | "total_tokens" | "cost_usd";

function SortHeader({ label, sortKey, align = "left" }: { label: string; sortKey: SortKey; align?: "left" | "right" }) {
  const params = useSearchParams();
  const pathname = usePathname();
  const sort = params.get("sort") ?? "start_time";
  const order = params.get("order") ?? "desc";
  const active = sort === sortKey;
  const next = new URLSearchParams(params.toString());
  next.set("sort", sortKey);
  next.set("order", active && order === "desc" ? "asc" : "desc");
  next.delete("cursor");
  const Icon = !active ? ChevronsUpDown : order === "desc" ? ArrowDown : ArrowUp;
  return (
    <Link
      href={`${pathname}?${next.toString()}`}
      scroll={false}
      aria-label={`Sort by ${label}`}
      className={cn(
        "inline-flex items-center gap-1 hover:text-foreground",
        align === "right" && "flex-row-reverse",
        active && "text-foreground",
      )}
    >
      {label}
      <Icon className={cn("size-3", !active && "opacity-50")} aria-hidden />
    </Link>
  );
}

function useColumns(projectId: string) {
  return React.useMemo(
    () =>
      col.columns([
      col.accessor("status", {
        header: () => "Status",
        cell: (info) => <StatusBadge status={info.getValue()} />,
        meta: { className: "w-24" },
      }),
      col.accessor("name", {
        header: () => "Trace",
        cell: (info) => {
          const t = info.row.original;
          return (
            <div className="min-w-0">
              <Link
                href={`/p/${projectId}/traces/${encodeURIComponent(t.trace_id)}`}
                className="block truncate font-medium text-foreground after:absolute after:inset-0 group-hover:text-accent"
              >
                {t.name}
              </Link>
              <div className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                <Mono className="text-[11px]">{t.trace_id.slice(0, 12)}</Mono>
                {t.error_message ? <span className="truncate text-error">{t.error_message}</span> : null}
                {!t.error_message && t.tags.length
                  ? t.tags.slice(0, 3).map((tag) => (
                      <Badge key={tag} className="font-mono">
                        {tag}
                      </Badge>
                    ))
                  : null}
              </div>
            </div>
          );
        },
        meta: { className: "max-w-0 w-full" },
      }),
      col.accessor("start_time", {
        header: () => <SortHeader label="Started" sortKey="start_time" />,
        cell: (info) => (
          <span title={formatDateTime(info.getValue())} className="whitespace-nowrap text-muted-foreground">
            {formatRelative(info.getValue())}
          </span>
        ),
      }),
      col.accessor("duration_ms", {
        header: () => <SortHeader label="Duration" sortKey="duration_ms" align="right" />,
        cell: (info) => <Mono>{formatDuration(info.getValue())}</Mono>,
        meta: { className: "text-right" },
      }),
      col.accessor("span_count", {
        header: () => "Spans",
        cell: (info) => {
          const t = info.row.original;
          return (
            <Mono>
              {formatNumber(t.span_count)}
              {t.error_span_count ? <span className="text-error"> · {t.error_span_count}✕</span> : null}
            </Mono>
          );
        },
        meta: { className: "text-right hidden md:table-cell" },
      }),
      col.accessor("total_tokens", {
        header: () => <SortHeader label="Tokens" sortKey="total_tokens" align="right" />,
        cell: (info) => <Mono>{formatNumber(info.getValue(), true)}</Mono>,
        meta: { className: "text-right hidden lg:table-cell" },
      }),
      col.accessor("cost_usd", {
        header: () => <SortHeader label="Cost" sortKey="cost_usd" align="right" />,
        cell: (info) => {
          const t = info.row.original;
          if (t.cost_usd === null && t.cost_status === "unavailable")
            return <span className="text-xs text-muted-foreground" title="No pricing for this model">n/a</span>;
          return <Mono>{formatCost(t.cost_usd)}</Mono>;
        },
        meta: { className: "text-right hidden lg:table-cell" },
      }),
      col.accessor("models", {
        header: () => "Model",
        cell: (info) => {
          const models = info.getValue();
          return models.length ? (
            <Mono className="whitespace-nowrap text-muted-foreground">
              {models[0]}
              {models.length > 1 ? ` +${models.length - 1}` : ""}
            </Mono>
          ) : (
            <span className="text-muted-foreground/60">—</span>
          );
        },
        meta: { className: "hidden xl:table-cell" },
      }),
      ]),
    [projectId],
  );
}

export function TraceTable({ projectId, items }: { projectId: string; items: TraceSummary[] }) {
  const router = useRouter();
  const columns = useColumns(projectId);
  const table = useTable({ features, columns, data: items, getRowId: (row) => row.id });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-border text-left text-xs text-muted-foreground">
              {hg.headers.map((h) => (
                <th
                  key={h.id}
                  scope="col"
                  className={cn("px-3 py-2 font-medium first:pl-4 last:pr-4", (h.column.columnDef.meta as { className?: string })?.className)}
                >
                  <table.FlexRender header={h} />
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              className="group relative border-b border-border last:border-0 hover:bg-muted/40"
              onMouseEnter={() => router.prefetch(`/p/${projectId}/traces/${encodeURIComponent(row.original.trace_id)}`)}
            >
              {row.getAllCells().map((cell) => (
                <td
                  key={cell.id}
                  className={cn("px-3 py-2.5 align-middle first:pl-4 last:pr-4", (cell.column.columnDef.meta as { className?: string })?.className)}
                >
                  <table.FlexRender cell={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
