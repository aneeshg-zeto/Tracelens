from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, and_, any_, func, literal, or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models import Span, Trace

SortField = Literal["start_time", "duration_ms", "cost_usd", "total_tokens"]
MAX_SPANS_PER_TRACE = 5000
COUNT_CAP = 10_000


@dataclass
class TraceFilters:
    q: str | None = None
    statuses: list[str] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    environment: str | None = None
    release: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    tag: str | None = None
    min_duration_ms: float | None = None
    max_duration_ms: float | None = None
    start_from: datetime | None = None
    start_to: datetime | None = None


_SENTINEL = {"duration_ms": -1.0, "cost_usd": -1.0, "total_tokens": -1}


def _sort_expr(sort: SortField) -> Any:
    col = getattr(Trace, sort)
    if sort == "start_time":
        return col
    return func.coalesce(col, _SENTINEL[sort])


def _encode_cursor(value: Any, row_id: uuid.UUID) -> str:
    raw = json.dumps({"v": value.isoformat() if isinstance(value, datetime) else value, "id": str(row_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str, sort: SortField) -> tuple[Any, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        value = data["v"]
        if sort == "start_time":
            value = datetime.fromisoformat(value)
        elif value is not None:
            value = float(value)
        return value, uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise APIError(400, "invalid_cursor", "Pagination cursor is invalid") from exc


def apply_filters(stmt: Select[Any], project_id: uuid.UUID, f: TraceFilters) -> Select[Any]:
    conds = [Trace.project_id == project_id]
    if f.q:
        q = f.q.strip()
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds.append(or_(Trace.name.ilike(like, escape="\\"), Trace.trace_id == q))
    if f.statuses:
        conds.append(Trace.status.in_(f.statuses))
    if f.model:
        conds.append(literal(f.model) == any_(Trace.models))
    if f.provider:
        conds.append(literal(f.provider.lower()) == any_(Trace.providers))
    if f.environment:
        conds.append(Trace.environment == f.environment)
    if f.release:
        conds.append(Trace.release == f.release)
    if f.user_id:
        conds.append(Trace.user_id == f.user_id)
    if f.session_id:
        conds.append(Trace.session_id == f.session_id)
    if f.tag:
        conds.append(literal(f.tag) == any_(Trace.tags))
    if f.min_duration_ms is not None:
        conds.append(Trace.duration_ms >= f.min_duration_ms)
    if f.max_duration_ms is not None:
        conds.append(Trace.duration_ms <= f.max_duration_ms)
    if f.start_from is not None:
        conds.append(Trace.start_time >= f.start_from)
    if f.start_to is not None:
        conds.append(Trace.start_time < f.start_to)
    return stmt.where(and_(*conds))


def list_traces(
    db: Session,
    project_id: uuid.UUID,
    filters: TraceFilters,
    *,
    sort: SortField = "start_time",
    order: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    expr = _sort_expr(sort)
    stmt = apply_filters(select(Trace), project_id, filters)
    if cursor:
        value, row_id = _decode_cursor(cursor, sort)
        if value is None:
            value = _SENTINEL.get(sort)
        cmp = (
            tuple_(expr, Trace.id) < tuple_(value, row_id)
            if order == "desc"
            else (tuple_(expr, Trace.id) > tuple_(value, row_id))
        )
        stmt = stmt.where(cmp)
    ordering = [expr.desc(), Trace.id.desc()] if order == "desc" else [expr.asc(), Trace.id.asc()]
    rows = list(db.scalars(stmt.order_by(*ordering).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        raw_value = getattr(last, sort)
        value = raw_value if raw_value is not None else _SENTINEL.get(sort)
        if sort == "cost_usd" and value is not None:
            value = float(value)
        next_cursor = _encode_cursor(value, last.id)

    count_stmt = apply_filters(select(Trace.id), project_id, filters).limit(COUNT_CAP + 1).subquery()
    total = db.scalar(select(func.count()).select_from(count_stmt)) or 0
    return {
        "items": [trace_summary(t) for t in rows],
        "next_cursor": next_cursor,
        "total": min(total, COUNT_CAP),
        "total_capped": total > COUNT_CAP,
    }


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def trace_summary(t: Trace) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "trace_id": t.trace_id,
        "name": t.name,
        "status": t.status,
        "start_time": t.start_time,
        "end_time": t.end_time,
        "duration_ms": t.duration_ms,
        "environment": t.environment,
        "release": t.release,
        "user_id": t.user_id,
        "session_id": t.session_id,
        "models": t.models,
        "providers": t.providers,
        "input_tokens": t.input_tokens,
        "output_tokens": t.output_tokens,
        "total_tokens": t.total_tokens,
        "cost_usd": _num(t.cost_usd),
        "cost_status": t.cost_status,
        "span_count": t.span_count,
        "error_span_count": t.error_span_count,
        "error_type": t.error_type,
        "error_message": t.error_message,
        "tags": t.tags,
        "source": t.source,
    }


def span_skeleton(s: Span) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "span_id": s.span_id,
        "parent_span_id": s.parent_span_id,
        "name": s.name,
        "kind": s.kind,
        "status": s.status,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "duration_ms": s.duration_ms,
        "provider": s.provider,
        "model": s.model,
        "input_tokens": s.input_tokens,
        "output_tokens": s.output_tokens,
        "cached_tokens": s.cached_tokens,
        "total_tokens": s.total_tokens,
        "usage_source": s.usage_source,
        "cost_usd": _num(s.cost_usd),
        "cost_status": s.cost_status,
        "error_type": s.error_type,
        "error_message": s.error_message,
        "retry_count": s.retry_count,
    }


def span_detail(s: Span) -> dict[str, Any]:
    return {
        **span_skeleton(s),
        "trace_id": s.trace_id,
        "input": s.input,
        "output": s.output,
        "attributes": s.attributes,
        "error_stacktrace": s.error_stacktrace,
        "pricing_version": s.pricing_version,
    }


def get_trace_row(db: Session, project_id: uuid.UUID, trace_id: str) -> Trace:
    trace = db.scalar(select(Trace).where(Trace.project_id == project_id, Trace.trace_id == trace_id))
    if trace is None:
        raise APIError(404, "not_found", "Trace not found")
    return trace


def get_trace_detail(db: Session, project_id: uuid.UUID, trace_id: str) -> dict[str, Any]:
    trace = get_trace_row(db, project_id, trace_id)
    spans = list(
        db.scalars(
            select(Span)
            .where(Span.trace_pk == trace.id)
            .order_by(Span.start_time, Span.span_id)
            .limit(MAX_SPANS_PER_TRACE + 1)
        )
    )
    truncated = len(spans) > MAX_SPANS_PER_TRACE
    return {
        "trace": {
            **trace_summary(trace),
            "root_span_id": trace.root_span_id,
            "input": trace.input,
            "output": trace.output,
            "metadata": trace.metadata_,
        },
        "spans": [span_skeleton(s) for s in spans[:MAX_SPANS_PER_TRACE]],
        "spans_truncated": truncated,
    }


def get_span(db: Session, project_id: uuid.UUID, trace_id: str, span_id: str) -> dict[str, Any]:
    span = db.scalar(
        select(Span).where(Span.project_id == project_id, Span.trace_id == trace_id, Span.span_id == span_id)
    )
    if span is None:
        raise APIError(404, "not_found", "Span not found")
    return span_detail(span)


def filter_options(db: Session, project_id: uuid.UUID) -> dict[str, list[str]]:
    """Distinct values for filter dropdowns, bounded to recent data."""
    envs = db.scalars(
        select(Trace.environment)
        .where(Trace.project_id == project_id, Trace.environment.is_not(None))
        .distinct()
        .limit(50)
    ).all()
    models = db.scalars(
        select(Span.model).where(Span.project_id == project_id, Span.model.is_not(None)).distinct().limit(100)
    ).all()
    providers = db.scalars(
        select(Span.provider)
        .where(Span.project_id == project_id, Span.provider.is_not(None))
        .distinct()
        .limit(50)
    ).all()
    return {
        "environments": sorted(e for e in envs if e),
        "models": sorted(m for m in models if m),
        "providers": sorted(p for p in providers if p),
    }
