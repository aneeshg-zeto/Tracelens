import { Badge } from "@/components/ui/primitives";
import type { SpanKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS: Record<string, { label: string; tone: "ok" | "error" | "warn" | "neutral" }> = {
  ok: { label: "OK", tone: "ok" },
  error: { label: "Error", tone: "error" },
  incomplete: { label: "Incomplete", tone: "warn" },
  unset: { label: "Unset", tone: "neutral" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as const };
  return (
    <Badge tone={s.tone} className={className}>
      {s.label}
    </Badge>
  );
}

export const KIND_COLOR: Record<SpanKind, string> = {
  llm: "bg-kind-llm",
  tool: "bg-kind-tool",
  retrieval: "bg-kind-retrieval",
  agent: "bg-kind-agent",
  chain: "bg-kind-chain",
  http: "bg-kind-http",
  custom: "bg-kind-other",
  other: "bg-kind-other",
};

export const KIND_LABEL: Record<SpanKind, string> = {
  llm: "LLM",
  tool: "Tool",
  retrieval: "Retrieval",
  agent: "Agent",
  chain: "Chain",
  http: "HTTP",
  custom: "Custom",
  other: "Other",
};

export function KindTag({ kind, className }: { kind: SpanKind; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[11px] text-muted-foreground", className)}>
      <span className={cn("size-2 shrink-0 rounded-[2px]", KIND_COLOR[kind] ?? "bg-kind-other")} aria-hidden />
      {KIND_LABEL[kind] ?? kind}
    </span>
  );
}
