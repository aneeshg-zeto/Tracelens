"use client";

import { ChevronRight, CircleAlert, RotateCcw } from "lucide-react";
import * as React from "react";
import { KIND_COLOR, KIND_LABEL } from "@/components/traces/status";
import { Button } from "@/components/ui/button";
import type { SpanKind, SpanSkeleton } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

export type Timing = { t0: number; total: number };

type Row = { span: SpanSkeleton; depth: number; hasChildren: boolean; offset: number; duration: number; open: boolean };

export function computeTiming(spans: SpanSkeleton[]): Timing {
  let t0 = Infinity;
  let t1 = -Infinity;
  for (const s of spans) {
    const start = Date.parse(s.start_time);
    const end = s.end_time ? Date.parse(s.end_time) : start + (s.duration_ms ?? 0);
    t0 = Math.min(t0, start);
    t1 = Math.max(t1, end);
  }
  if (!Number.isFinite(t0)) return { t0: 0, total: 1 };
  return { t0, total: Math.max(1, t1 - t0) };
}

function useTree(spans: SpanSkeleton[]) {
  return React.useMemo(() => {
    const ids = new Set(spans.map((s) => s.span_id));
    const children = new Map<string | null, SpanSkeleton[]>();
    const parent = new Map<string, string | null>();
    for (const s of spans) {
      const p = s.parent_span_id && ids.has(s.parent_span_id) && s.parent_span_id !== s.span_id ? s.parent_span_id : null;
      parent.set(s.span_id, p);
      const list = children.get(p);
      if (list) list.push(s);
      else children.set(p, [s]);
    }
    for (const list of children.values()) list.sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time));
    return { children, parent };
  }, [spans]);
}

export function Waterfall({
  spans,
  timing,
  selected,
  onSelect,
}: {
  spans: SpanSkeleton[];
  timing: Timing;
  selected: string | null;
  onSelect: (spanId: string | null) => void;
}) {
  const { children, parent } = useTree(spans);
  const [collapsed, setCollapsed] = React.useState<Set<string>>(() => new Set());
  const treeRef = React.useRef<HTMLDivElement>(null);

  const ancestors = React.useMemo(() => {
    const out = new Set<string>();
    let p = selected ? (parent.get(selected) ?? null) : null;
    while (p && !out.has(p)) {
      out.add(p);
      p = parent.get(p) ?? null;
    }
    return out;
  }, [selected, parent]);

  const rows = React.useMemo(() => {
    const out: Row[] = [];
    const seen = new Set<string>();
    const walk = (p: string | null, depth: number) => {
      for (const s of children.get(p) ?? []) {
        if (seen.has(s.span_id)) continue;
        seen.add(s.span_id);
        const start = Date.parse(s.start_time);
        const duration =
          s.duration_ms ?? (s.end_time ? Date.parse(s.end_time) - start : timing.t0 + timing.total - start);
        const kids = children.get(s.span_id)?.length ?? 0;
        // Ancestors of the selected span stay open so a selection made elsewhere is always visible.
        const open = !collapsed.has(s.span_id) || ancestors.has(s.span_id);
        out.push({ span: s, depth, hasChildren: kids > 0, offset: start - timing.t0, duration, open });
        if (kids && open) walk(s.span_id, depth + 1);
      }
    };
    walk(null, 0);
    return out;
  }, [children, collapsed, ancestors, timing]);

  React.useEffect(() => {
    if (!selected) return;
    const frame = requestAnimationFrame(() =>
      document.getElementById(`span-row-${selected}`)?.scrollIntoView({ block: "nearest" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [selected]);

  const toggle = (id: string) => {
    const closing = !collapsed.has(id) || ancestors.has(id);
    if (closing && ancestors.has(id)) onSelect(id);
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (closing) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  function onKeyDown(e: React.KeyboardEvent) {
    const i = rows.findIndex((r) => r.span.span_id === selected);
    const row = rows[i];
    if (e.key === "ArrowDown" || e.key === "j") {
      e.preventDefault();
      onSelect(rows[Math.min(rows.length - 1, i + 1)]?.span.span_id ?? null);
    } else if (e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      onSelect(rows[Math.max(0, i - 1)]?.span.span_id ?? rows[0]?.span.span_id ?? null);
    } else if (e.key === "ArrowRight" && row?.hasChildren) {
      e.preventDefault();
      if (!row.open) toggle(row.span.span_id);
      else onSelect(rows[i + 1]?.span.span_id ?? null);
    } else if (e.key === "ArrowLeft" && row) {
      e.preventDefault();
      if (row.hasChildren && row.open) toggle(row.span.span_id);
      else {
        const p = parent.get(row.span.span_id);
        if (p) onSelect(p);
      }
    } else if (e.key === "Escape") {
      onSelect(null);
    }
  }

  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const kinds = Array.from(new Set(spans.map((s) => s.kind))) as SpanKind[];
  const firstError = spans
    .filter((s) => s.status === "error")
    .sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time))[0];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2">
        <ul className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Span kinds">
          {kinds.map((k) => (
            <li key={k} className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className={cn("size-2 rounded-[2px]", KIND_COLOR[k])} aria-hidden />
              {KIND_LABEL[k] ?? k}
            </li>
          ))}
        </ul>
        <div className="ml-auto flex items-center gap-1">
          {firstError ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-error hover:text-error"
              onClick={() => onSelect(firstError.span_id)}
            >
              <CircleAlert /> First error
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setCollapsed((prev) =>
                prev.size ? new Set() : new Set(spans.filter((s) => children.get(s.span_id)?.length).map((s) => s.span_id)),
              )
            }
          >
            {collapsed.size ? "Expand all" : "Collapse all"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-[minmax(180px,40%)_minmax(0,1fr)]">
        <div className="hidden border-b border-border px-4 py-1.5 text-[11px] text-muted-foreground sm:block">Span</div>
        <div className="relative hidden h-7 border-b border-border sm:block" aria-hidden>
          {ticks.map((t) => (
            <span
              key={t}
              className={cn(
                "absolute top-1.5 font-mono text-[10px] text-muted-foreground",
                t === 0 ? "translate-x-1" : t === 1 ? "-translate-x-full pr-3" : "-translate-x-1/2",
              )}
              style={{ left: `${t * 100}%` }}
            >
              {formatDuration(timing.total * t)}
            </span>
          ))}
        </div>
      </div>

      <div
        ref={treeRef}
        role="tree"
        aria-label="Spans"
        tabIndex={0}
        aria-activedescendant={selected ? `span-row-${selected}` : undefined}
        onKeyDown={onKeyDown}
        onFocus={() => {
          if (!selected && rows[0]) onSelect(rows[0].span.span_id);
        }}
        className="max-h-[min(70vh,900px)] overflow-y-auto focus-visible:outline-offset-[-2px]"
      >
        {rows.map((r) => {
          const s = r.span;
          const isSel = s.span_id === selected;
          const left = (r.offset / timing.total) * 100;
          const width = Math.max(0.35, (r.duration / timing.total) * 100);
          const labelRight = left + width > 78;
          return (
            <div
              key={s.span_id}
              id={`span-row-${s.span_id}`}
              role="treeitem"
              aria-level={r.depth + 1}
              aria-selected={isSel}
              aria-expanded={r.hasChildren ? r.open : undefined}
              onClick={() => onSelect(s.span_id)}
              className={cn(
                "grid cursor-pointer grid-cols-[minmax(0,1fr)] border-l-2 border-transparent sm:grid-cols-[minmax(180px,40%)_minmax(0,1fr)]",
                isSel ? "border-l-accent bg-accent-soft/40" : "hover:bg-muted/50",
              )}
            >
              <div className="flex h-8 min-w-0 items-center gap-1.5 pr-2" style={{ paddingLeft: 10 + r.depth * 14 }}>
                {r.hasChildren ? (
                  <button
                    type="button"
                    tabIndex={-1}
                    aria-label={r.open ? "Collapse" : "Expand"}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(s.span_id);
                    }}
                    className="grid size-4 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <ChevronRight className={cn("size-3.5 transition-transform", r.open && "rotate-90")} />
                  </button>
                ) : (
                  <span className="size-4 shrink-0" />
                )}
                <span className={cn("size-2 shrink-0 rounded-[2px]", KIND_COLOR[s.kind] ?? "bg-kind-other")} aria-hidden />
                <span className={cn("truncate text-[13px]", s.status === "error" ? "text-error" : "text-foreground")}>
                  {s.name}
                </span>
                {s.retry_count ? (
                  <span className="inline-flex shrink-0 items-center gap-0.5 font-mono text-[10px] text-warn" title={`${s.retry_count} retries`}>
                    <RotateCcw className="size-3" />
                    {s.retry_count}
                  </span>
                ) : null}
                {s.model ? (
                  <span className="hidden shrink-0 truncate font-mono text-[11px] text-muted-foreground lg:inline">{s.model}</span>
                ) : null}
                <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground sm:hidden">
                  {formatDuration(r.duration)}
                </span>
              </div>
              <div className="relative hidden h-8 sm:block">
                {ticks.slice(1, -1).map((t) => (
                  <span key={t} className="absolute inset-y-0 w-px bg-border/60" style={{ left: `${t * 100}%` }} aria-hidden />
                ))}
                <span
                  className={cn(
                    "absolute top-1/2 h-3 -translate-y-1/2 rounded-[2px]",
                    s.status === "error" ? "bg-error" : (KIND_COLOR[s.kind] ?? "bg-kind-other"),
                    !s.end_time && "opacity-60 [background-image:repeating-linear-gradient(135deg,transparent_0_4px,rgb(0_0_0/0.25)_4px_6px)]",
                  )}
                  style={{ left: `${left}%`, width: `${width}%` }}
                />
                <span
                  className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap px-1.5 font-mono text-[10.5px] text-muted-foreground"
                  style={labelRight ? { right: `${100 - left}%` } : { left: `${left + width}%` }}
                >
                  {formatDuration(r.duration)}
                  {!s.end_time ? " (open)" : ""}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
