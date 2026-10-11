"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import type { Overview } from "@/lib/types";
import { formatCost, formatDuration, formatNumber } from "@/lib/utils";

type Series = Overview["series"];

const AXIS = { fontSize: 11, fill: "var(--muted-foreground)" } as const;

function bucketLabel(iso: string, bucket: string) {
  const d = new Date(iso);
  return bucket === "1 day"
    ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function ChartTooltip({
  active,
  payload,
  label,
  format,
}: Pick<Partial<TooltipContentProps<ValueType, NameType>>, "active" | "payload" | "label"> & {
  format: (name: string, v: number | null) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border-strong bg-surface-2 px-2.5 py-1.5 text-xs shadow-popover">
      <p className="mb-1 font-mono text-muted-foreground">{new Date(String(label)).toLocaleString()}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="size-2 rounded-[2px]" style={{ background: p.color }} aria-hidden />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto font-mono tabular">
            {format(String(p.dataKey), typeof p.value === "number" ? p.value : null)}
          </span>
        </p>
      ))}
    </div>
  );
}

function Frame({ children, height = 180 }: { children: React.ReactElement; height?: number }) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

export function VolumeChart({ series, bucket }: { series: Series; bucket: string }) {
  const data = series.map((s) => ({ ...s, ok: s.traces - s.errors }));
  return (
    <Frame>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="bucket" tickFormatter={(v) => bucketLabel(v, bucket)} tick={AXIS} tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} width={44} />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          content={(p) => <ChartTooltip {...p} format={(_, v) => formatNumber(v)} />}
        />
        <Bar dataKey="ok" name="OK" stackId="t" fill="var(--kind-chain)" isAnimationActive={false} />
        <Bar dataKey="errors" name="Errors" stackId="t" fill="var(--error)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </Frame>
  );
}

export function LatencyChart({ series, bucket }: { series: Series; bucket: string }) {
  return (
    <Frame>
      <LineChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="bucket" tickFormatter={(v) => bucketLabel(v, bucket)} tick={AXIS} tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v) => (v ? formatDuration(v) : "0")} width={56} />
        <Tooltip content={(p) => <ChartTooltip {...p} format={(_, v) => formatDuration(v)} />} />
        <Line
          dataKey="p95_ms"
          name="p95 latency"
          stroke="var(--accent)"
          strokeWidth={1.75}
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </Frame>
  );
}

export function CostChart({ series, bucket }: { series: Series; bucket: string }) {
  return (
    <Frame>
      <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="bucket" tickFormatter={(v) => bucketLabel(v, bucket)} tick={AXIS} tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v) => (v ? formatCost(v) : "$0")} width={64} />
        <Tooltip
          content={(p) => (
            <ChartTooltip {...p} format={(k, v) => (k === "cost_usd" ? formatCost(v) : formatNumber(v))} />
          )}
        />
        <Area
          dataKey="cost_usd"
          name="Cost"
          stroke="var(--kind-retrieval)"
          fill="var(--kind-retrieval)"
          fillOpacity={0.14}
          strokeWidth={1.5}
          connectNulls
          isAnimationActive={false}
        />
      </AreaChart>
    </Frame>
  );
}

/** Buckets are half-decades (10^(i/2) ms); the API omits empty ones, so fill a contiguous range. */
function fillHistogram(buckets: Overview["latency_histogram"]) {
  const index = (upper: number) => Math.round(Math.log10(Math.max(upper, 1)) * 2);
  const counts = new Map(buckets.map((b) => [index(b.upper_ms), b.count]));
  const present = [...counts.keys()];
  if (!present.length) return [];
  const lo = Math.max(1, Math.min(...present) - 1);
  const hi = Math.min(13, Math.max(Math.max(...present) + 1, lo + 7));
  return Array.from({ length: hi - lo + 1 }, (_, k) => {
    const i = lo + k;
    const lower = i <= 1 ? 0 : Math.round(10 ** ((i - 1) / 2));
    const upper = Math.round(10 ** (i / 2));
    return { lower_ms: lower, upper_ms: upper, count: counts.get(i) ?? 0 };
  });
}

export function LatencyHistogram({ buckets }: { buckets: Overview["latency_histogram"] }) {
  const data = fillHistogram(buckets).map((b) => ({
    ...b,
    label: `${formatDuration(b.lower_ms)}–${formatDuration(b.upper_ms)}`,
  }));
  return (
    <Frame height={150}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap={1}>
        <XAxis dataKey="upper_ms" tickFormatter={(v) => `<${formatDuration(v)}`} tick={AXIS} tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} width={48} />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <div className="rounded-md border border-border-strong bg-surface-2 px-2.5 py-1.5 text-xs shadow-popover">
                <p className="font-mono text-muted-foreground">{payload[0].payload.label}</p>
                <p className="font-mono tabular">{formatNumber(payload[0].value as number)} traces</p>
              </div>
            ) : null
          }
        />
        <Bar dataKey="count" fill="var(--kind-http)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </Frame>
  );
}
