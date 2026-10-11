"use client";

import * as React from "react";
import { SpanPanel, TraceSummaryPanel } from "@/components/traces/span-panel";
import { useSpanSelection } from "@/components/traces/use-span-selection";
import { computeTiming, Waterfall } from "@/components/traces/waterfall";
import { Alert, Panel } from "@/components/ui/primitives";
import type { TraceDetail } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

export function TraceExplorer({
  projectId,
  detail,
  capturePayloads,
}: {
  projectId: string;
  detail: TraceDetail;
  capturePayloads: boolean;
}) {
  const [selected, select] = useSpanSelection();
  const timing = React.useMemo(() => computeTiming(detail.spans), [detail.spans]);
  const span = selected ? detail.spans.find((s) => s.span_id === selected) : undefined;

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
      <Panel className="min-w-0 overflow-hidden">
        {detail.spans_truncated ? (
          <Alert tone="warn" className="m-3">
            Showing the first {formatNumber(detail.spans.length)} spans. This trace has more.
          </Alert>
        ) : null}
        {detail.spans.length ? (
          <Waterfall spans={detail.spans} timing={timing} selected={span ? selected : null} onSelect={select} />
        ) : (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            This trace has no spans yet. Spans sent in a later batch will appear here.
          </p>
        )}
      </Panel>
      <Panel className="min-w-0 overflow-hidden xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto">
        {span ? (
          <SpanPanel
            key={span.span_id}
            projectId={projectId}
            traceId={detail.trace.trace_id}
            span={span}
            offsetMs={Date.parse(span.start_time) - timing.t0}
            capturePayloads={capturePayloads}
            onClose={() => select(null)}
          />
        ) : (
          <TraceSummaryPanel
            input={detail.trace.input}
            output={detail.trace.output}
            metadata={detail.trace.metadata}
            capturePayloads={capturePayloads}
          />
        )}
      </Panel>
    </div>
  );
}
