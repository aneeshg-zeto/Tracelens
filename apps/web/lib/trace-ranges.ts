export const TRACE_RANGES = ["1h", "24h", "7d", "30d", "all"] as const;
export type TraceRange = (typeof TRACE_RANGES)[number];
export const RANGE_HOURS: Record<Exclude<TraceRange, "all">, number> = { "1h": 1, "24h": 24, "7d": 168, "30d": 720 };

export function isTraceRange(value: string | undefined): value is TraceRange {
  return !!value && (TRACE_RANGES as readonly string[]).includes(value);
}
