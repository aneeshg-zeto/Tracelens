"""Idempotent trace/span persistence shared by the native, OTLP, and test paths.

Semantics
---------
* Spans are upserted on (project_id, trace_id, span_id); re-sending a batch
  produces the same rows (last write wins).
* A trace row is upserted on (project_id, trace_id). If spans arrive before
  their trace (the normal case: spans finish first, or the process crashed
  before the trace ended), a placeholder trace with status "incomplete" is
  created and completed when the trace record arrives.
* Per-trace aggregates (span counts, tokens, cost, models) are recomputed from
  the stored spans after every batch, so totals stay correct under retries.
  Token and cost totals only sum spans of kind "llm" to avoid double counting
  when wrapper spans repeat their children's usage.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.redaction import bound_payload, redact, redact_string, summarize_payload
from app.models import Project, Span, Trace
from app.schemas.ingest import IngestBatch, SpanIn, TraceIn
from app.services.pricing import compute_cost

logger = logging.getLogger("tracelens.ingest")


@dataclass(frozen=True)
class IngestResult:
    accepted_traces: int
    accepted_spans: int
    trace_ids: list[str]


def _payload(project: Project, value: Any) -> Any:
    if value is None:
        return None
    return bound_payload(value) if project.capture_payloads else summarize_payload(value)


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return redact_string(value)[:limit]


def _duration_ms(start: Any, end: Any) -> float | None:
    if end is None:
        return None
    return round((end - start).total_seconds() * 1000.0, 3)


def _trace_row(project: Project, t: TraceIn, source: str) -> dict[str, Any]:
    status = t.status
    if t.end_time is None and status != "error":
        status = "incomplete"
    return {
        "project_id": project.id,
        "trace_id": t.trace_id,
        "name": t.name,
        "status": status,
        "start_time": t.start_time,
        "end_time": t.end_time,
        "duration_ms": _duration_ms(t.start_time, t.end_time),
        "environment": t.environment,
        "release": t.release,
        "user_id": t.user_id,
        "session_id": t.session_id,
        "input": _payload(project, t.input),
        "output": _payload(project, t.output),
        "error_type": _text(t.error.type, 256) if t.error else None,
        "error_message": _text(t.error.message, 4000) if t.error else None,
        "tags": t.tags,
        "metadata": redact(t.metadata),
        "source": source,
    }


def _span_row(project: Project, trace_pk: uuid.UUID, s: SpanIn) -> dict[str, Any]:
    usage = s.usage
    input_tokens = usage.input_tokens if usage else None
    output_tokens = usage.output_tokens if usage else None
    cached_tokens = usage.cached_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    cost = compute_cost(
        provider=s.provider,
        model=s.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        reported_cost=s.cost_usd,
    )
    status = s.status
    if s.error is not None and status == "ok":
        status = "error"
    return {
        "project_id": project.id,
        "trace_pk": trace_pk,
        "trace_id": s.trace_id,
        "span_id": s.span_id,
        "parent_span_id": s.parent_span_id,
        "name": s.name,
        "kind": s.kind,
        "status": status,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "duration_ms": _duration_ms(s.start_time, s.end_time),
        "provider": s.provider.lower() if s.provider else None,
        "model": s.model,
        "input": _payload(project, s.input),
        "output": _payload(project, s.output),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "usage_source": usage.source if usage and total_tokens is not None else None,
        "cost_usd": cost.cost_usd,
        "cost_status": cost.status,
        "pricing_version": cost.pricing_version,
        "error_type": _text(s.error.type, 256) if s.error else None,
        "error_message": _text(s.error.message, 4000) if s.error else None,
        "error_stacktrace": (
            _text(s.error.stacktrace, 16000) if s.error and project.capture_payloads else None
        ),
        "attributes": bound_payload(s.attributes) or {},
        "retry_count": s.retry_count,
    }


_RECOMPUTE_SQL = text(
    """
    WITH agg AS (
        SELECT
            s.trace_pk,
            count(*) AS span_count,
            count(*) FILTER (WHERE s.status = 'error') AS error_span_count,
            min(s.start_time) AS min_start,
            max(s.end_time) AS max_end,
            sum(s.input_tokens) FILTER (WHERE s.kind = 'llm') AS input_tokens,
            sum(s.output_tokens) FILTER (WHERE s.kind = 'llm') AS output_tokens,
            sum(s.total_tokens) FILTER (WHERE s.kind = 'llm') AS total_tokens,
            sum(s.cost_usd) FILTER (WHERE s.kind = 'llm') AS cost_usd,
            count(*) FILTER (WHERE s.kind = 'llm' AND s.cost_status IS NOT NULL) AS priced_candidates,
            count(*) FILTER (WHERE s.kind = 'llm' AND s.cost_status = 'unavailable') AS unpriced,
            coalesce(array_agg(DISTINCT s.model) FILTER (WHERE s.model IS NOT NULL), '{}') AS models,
            coalesce(array_agg(DISTINCT s.provider) FILTER (WHERE s.provider IS NOT NULL), '{}') AS providers,
            (array_agg(s.span_id ORDER BY s.start_time) FILTER (WHERE s.parent_span_id IS NULL))[1] AS root_span_id,
            (array_agg(s.name ORDER BY s.start_time) FILTER (WHERE s.parent_span_id IS NULL))[1] AS root_name,
            (array_agg(s.error_type ORDER BY s.start_time) FILTER (WHERE s.status = 'error'))[1] AS first_error_type,
            (array_agg(s.error_message ORDER BY s.start_time) FILTER (WHERE s.status = 'error'))[1] AS first_error_message
        FROM spans s
        WHERE s.trace_pk = ANY(:trace_pks)
        GROUP BY s.trace_pk
    )
    UPDATE traces t SET
        span_count = agg.span_count,
        error_span_count = agg.error_span_count,
        start_time = LEAST(t.start_time, agg.min_start),
        input_tokens = agg.input_tokens,
        output_tokens = agg.output_tokens,
        total_tokens = agg.total_tokens,
        cost_usd = agg.cost_usd,
        cost_status = CASE
            WHEN agg.priced_candidates = 0 THEN NULL
            WHEN agg.unpriced = 0 THEN 'calculated'
            WHEN agg.unpriced = agg.priced_candidates THEN 'unavailable'
            ELSE 'partial'
        END,
        models = agg.models,
        providers = agg.providers,
        root_span_id = coalesce(t.root_span_id, agg.root_span_id),
        name = CASE WHEN t.status = 'incomplete' AND agg.root_name IS NOT NULL THEN agg.root_name ELSE t.name END,
        error_type = coalesce(t.error_type, CASE WHEN t.status = 'error' THEN agg.first_error_type END),
        error_message = coalesce(t.error_message, CASE WHEN t.status = 'error' THEN agg.first_error_message END),
        updated_at = now()
    FROM agg
    WHERE t.id = agg.trace_pk
    """
)


def ingest_batch(db: Session, project: Project, batch: IngestBatch, source: str = "sdk") -> IngestResult:
    traces_by_id: dict[str, TraceIn] = {t.trace_id: t for t in batch.traces}
    spans_by_trace: dict[str, list[SpanIn]] = defaultdict(list)
    for span in batch.spans:
        spans_by_trace[span.trace_id].append(span)

    if traces_by_id:
        rows = [_trace_row(project, t, source) for t in traces_by_id.values()]
        stmt = insert(Trace.__table__).values(rows)
        update_cols = {
            c: stmt.excluded[c]
            for c in (
                "name",
                "status",
                "start_time",
                "end_time",
                "duration_ms",
                "environment",
                "release",
                "user_id",
                "session_id",
                "input",
                "output",
                "error_type",
                "error_message",
                "tags",
                "metadata",
                "source",
            )
        }
        update_cols["updated_at"] = text("now()")
        db.execute(stmt.on_conflict_do_update(constraint="uq_traces_project_trace_id", set_=update_cols))

    placeholder_ids = [tid for tid in spans_by_trace if tid not in traces_by_id]
    if placeholder_ids:
        placeholders = []
        for tid in placeholder_ids:
            spans = spans_by_trace[tid]
            root = next((s for s in spans if s.parent_span_id is None), None)
            placeholders.append(
                {
                    "project_id": project.id,
                    "trace_id": tid,
                    "name": (root or min(spans, key=lambda s: s.start_time)).name,
                    "status": "incomplete",
                    "start_time": min(s.start_time for s in spans),
                    "source": source,
                }
            )
        db.execute(
            insert(Trace.__table__)
            .values(placeholders)
            .on_conflict_do_nothing(constraint="uq_traces_project_trace_id")
        )

    all_ids = list(traces_by_id.keys() | spans_by_trace.keys())
    pk_by_trace = dict(
        db.execute(
            select(Trace.trace_id, Trace.id).where(
                Trace.project_id == project.id, Trace.trace_id.in_(all_ids)
            )
        ).all()
    )

    if batch.spans:
        span_rows = [_span_row(project, pk_by_trace[s.trace_id], s) for s in batch.spans]
        # Deduplicate within the batch so ON CONFLICT never sees the same key twice.
        unique_rows = list({(r["trace_id"], r["span_id"]): r for r in span_rows}.values())
        for start in range(0, len(unique_rows), 500):
            chunk = unique_rows[start : start + 500]
            stmt = insert(Span.__table__).values(chunk)
            excluded_cols = [c for c in chunk[0] if c not in ("project_id", "trace_id", "span_id")]
            db.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_spans_project_trace_span",
                    set_={c: stmt.excluded[c] for c in excluded_cols},
                )
            )

    db.execute(_RECOMPUTE_SQL, {"trace_pks": list(pk_by_trace.values())})
    db.commit()
    logger.info(
        "ingested batch",
        extra={
            "project_id": str(project.id),
            "traces": len(traces_by_id),
            "spans": len(batch.spans),
            "source": source,
        },
    )
    return IngestResult(len(traces_by_id), len(batch.spans), sorted(all_ids))
