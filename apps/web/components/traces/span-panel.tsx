"use client";

import { X } from "lucide-react";
import * as React from "react";
import { Payload } from "@/components/traces/payload";
import { KindTag, StatusBadge } from "@/components/traces/status";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/code-block";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Alert, Badge, Mono, Skeleton } from "@/components/ui/primitives";
import type { SpanDetail, SpanSkeleton } from "@/lib/types";
import { formatCost, formatDateTime, formatDuration, formatNumber } from "@/lib/utils";

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: SpanDetail };

const cache = new Map<string, SpanDetail>();

function useSpanDetail(projectId: string, traceId: string, spanId: string) {
  const key = `${projectId}/${traceId}/${spanId}`;
  const [state, setState] = React.useState<Load>(() =>
    cache.has(key) ? { status: "ready", data: cache.get(key)! } : { status: "loading" },
  );
  const [attempt, setAttempt] = React.useState(0);

  // Callers remount this per span (via `key`), so initial state already reflects the cache.
  React.useEffect(() => {
    if (cache.has(key)) return;
    const ctrl = new AbortController();
    fetch(
      `/api/backend/projects/${encodeURIComponent(projectId)}/traces/${encodeURIComponent(traceId)}/spans/${encodeURIComponent(spanId)}`,
      { signal: ctrl.signal, cache: "no-store" },
    )
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok) throw new Error(body?.error?.message ?? `Request failed (${res.status})`);
        cache.set(key, body as SpanDetail);
        setState({ status: "ready", data: body as SpanDetail });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "Could not load span" });
      });
    return () => ctrl.abort();
  }, [key, projectId, traceId, spanId, attempt]);

  return {
    state,
    retry: () => {
      setState({ status: "loading" });
      setAttempt((a) => a + 1);
    },
  };
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px]">{children}</dd>
    </div>
  );
}

export function SpanPanel({
  projectId,
  traceId,
  span,
  offsetMs,
  capturePayloads,
  onClose,
}: {
  projectId: string;
  traceId: string;
  span: SpanSkeleton;
  offsetMs: number;
  capturePayloads: boolean;
  onClose: () => void;
}) {
  const { state, retry } = useSpanDetail(projectId, traceId, span.span_id);
  const empty = capturePayloads ? "Nothing recorded" : "Payload capture is off for this project";
  const isLlm = span.kind === "llm" || span.model;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <KindTag kind={span.kind} />
            <StatusBadge status={span.status} />
            {span.retry_count ? <Badge tone="warn">{span.retry_count} retries</Badge> : null}
          </div>
          <h2 className="mt-1 break-words text-sm font-semibold">{span.name}</h2>
          <div className="mt-0.5 flex items-center gap-1">
            <Mono className="truncate text-[11px] text-muted-foreground">{span.span_id}</Mono>
            <CopyButton value={span.span_id} label="Copy span ID" className="[&>span]:sr-only" />
          </div>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close span details">
          <X />
        </Button>
      </header>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-border px-4 py-3 sm:grid-cols-3">
        <Fact label="Duration">
          <Mono>{formatDuration(span.duration_ms)}</Mono>
        </Fact>
        <Fact label="Starts at">
          <Mono>+{formatDuration(offsetMs)}</Mono>
        </Fact>
        <Fact label="Started">
          <span title={span.start_time}>{formatDateTime(span.start_time)}</span>
        </Fact>
        {isLlm ? (
          <>
            <Fact label="Model">
              <Mono>{span.model ?? "—"}</Mono>
              {span.provider ? <span className="ml-1 text-xs text-muted-foreground">{span.provider}</span> : null}
            </Fact>
            <Fact label="Tokens in / out">
              <Mono>
                {formatNumber(span.input_tokens)} / {formatNumber(span.output_tokens)}
              </Mono>
              {span.usage_source === "estimated" ? <span className="ml-1 text-[11px] text-warn">est.</span> : null}
            </Fact>
            <Fact label="Cost">
              {span.cost_status === "unavailable" ? (
                <span className="text-xs text-muted-foreground">No pricing for model</span>
              ) : (
                <Mono>{formatCost(span.cost_usd)}</Mono>
              )}
            </Fact>
            {span.cached_tokens ? (
              <Fact label="Cached tokens">
                <Mono>{formatNumber(span.cached_tokens)}</Mono>
              </Fact>
            ) : null}
          </>
        ) : null}
      </dl>

      {span.status === "error" ? (
        <div className="border-b border-border px-4 py-3">
          <Alert tone="error" title={span.error_type ?? "Error"}>
            <span className="break-words">{span.error_message ?? "The span reported an error without a message."}</span>
          </Alert>
          {state.status === "ready" && state.data.error_stacktrace ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">Stack trace</summary>
              <pre className="mt-1 max-h-64 overflow-auto rounded-md border border-border bg-background p-2 font-mono text-[11px] leading-4">
                {state.data.error_stacktrace}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}

      <Tabs defaultValue="input" className="min-h-0 flex-1 px-4 pt-2">
        <TabsList>
          <TabsTrigger value="input">Input</TabsTrigger>
          <TabsTrigger value="output">Output</TabsTrigger>
          <TabsTrigger value="attributes">Attributes</TabsTrigger>
        </TabsList>
        {state.status === "loading" ? (
          <div className="space-y-2 py-4" aria-label="Loading span">
            <Skeleton className="h-3.5 w-3/4" />
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3.5 w-2/3" />
          </div>
        ) : state.status === "error" ? (
          <div className="py-4">
            <Alert tone="error" title="Could not load span details">
              {state.message}{" "}
              <button type="button" onClick={retry} className="text-accent hover:underline">
                Retry
              </button>
            </Alert>
          </div>
        ) : (
          <>
            <TabsContent value="input" className="pb-4">
              <Payload value={state.data.input} empty={empty} />
            </TabsContent>
            <TabsContent value="output" className="pb-4">
              <Payload value={state.data.output} empty={empty} />
            </TabsContent>
            <TabsContent value="attributes" className="pb-4">
              {Object.keys(state.data.attributes ?? {}).length ? (
                <dl className="divide-y divide-border rounded-md border border-border">
                  {Object.entries(state.data.attributes).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3 px-3 py-1.5">
                      <dt className="truncate font-mono text-[11px] text-muted-foreground" title={k}>
                        {k}
                      </dt>
                      <dd className="break-words font-mono text-[11px]">
                        {typeof v === "string" ? v : JSON.stringify(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">No attributes recorded</p>
              )}
              {state.data.pricing_version ? (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Priced with table <Mono>{state.data.pricing_version}</Mono>
                </p>
              ) : null}
            </TabsContent>
          </>
        )}
      </Tabs>
    </div>
  );
}

export function TraceSummaryPanel({
  input,
  output,
  metadata,
  capturePayloads,
}: {
  input: unknown;
  output: unknown;
  metadata: Record<string, unknown>;
  capturePayloads: boolean;
}) {
  const empty = capturePayloads ? "Nothing recorded" : "Payload capture is off for this project";
  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Trace input and output</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">Select a span to inspect it. Use ↑ ↓ ← → in the span list.</p>
      </header>
      <Tabs defaultValue="input" className="px-4 pt-2">
        <TabsList>
          <TabsTrigger value="input">Input</TabsTrigger>
          <TabsTrigger value="output">Output</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>
        <TabsContent value="input" className="pb-4">
          <Payload value={input} empty={empty} />
        </TabsContent>
        <TabsContent value="output" className="pb-4">
          <Payload value={output} empty={empty} />
        </TabsContent>
        <TabsContent value="metadata" className="pb-4">
          <Payload value={Object.keys(metadata ?? {}).length ? metadata : null} empty="No metadata" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
