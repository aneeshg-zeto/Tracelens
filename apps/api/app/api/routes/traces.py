from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import DB, ProjectContext, project_permission
from app.core.errors import APIError
from app.services import analytics, audit
from app.services.traces_query import (
    SortField,
    TraceFilters,
    filter_options,
    get_span,
    get_trace_detail,
    get_trace_row,
    list_traces,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["traces"])

ReadCtx = Annotated[ProjectContext, Depends(project_permission("trace", "read"))]


@router.get("/traces", summary="List traces with filters and keyset pagination")
def traces(
    ctx: ReadCtx,
    db: DB,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[list[Literal["ok", "error", "incomplete"]] | None, Query()] = None,
    model: Annotated[str | None, Query(max_length=256)] = None,
    provider: Annotated[str | None, Query(max_length=128)] = None,
    environment: Annotated[str | None, Query(max_length=128)] = None,
    release: Annotated[str | None, Query(max_length=128)] = None,
    user_id: Annotated[str | None, Query(max_length=256)] = None,
    session_id: Annotated[str | None, Query(max_length=256)] = None,
    tag: Annotated[str | None, Query(max_length=64)] = None,
    min_duration_ms: Annotated[float | None, Query(ge=0)] = None,
    max_duration_ms: Annotated[float | None, Query(ge=0)] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    sort: SortField = "start_time",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> dict[str, Any]:
    filters = TraceFilters(
        q=q,
        statuses=list(status or []),
        model=model,
        provider=provider,
        environment=environment,
        release=release,
        user_id=user_id,
        session_id=session_id,
        tag=tag,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        start_from=start,
        start_to=end,
    )
    return list_traces(db, ctx.project.id, filters, sort=sort, order=order, limit=limit, cursor=cursor)


@router.get("/trace-filters", summary="Distinct filter values for this project")
def trace_filters(ctx: ReadCtx, db: DB) -> dict[str, list[str]]:
    return filter_options(db, ctx.project.id)


@router.get("/traces/{trace_id}", summary="Trace detail with span skeletons")
def trace_detail(trace_id: str, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    return get_trace_detail(db, ctx.project.id, trace_id)


@router.get("/traces/{trace_id}/spans/{span_id}", summary="Full span detail including payloads")
def span_detail(trace_id: str, span_id: str, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    return get_span(db, ctx.project.id, trace_id, span_id)


@router.delete("/traces/{trace_id}", status_code=204, summary="Delete a trace immediately")
def delete_trace(
    trace_id: str,
    ctx: Annotated[ProjectContext, Depends(project_permission("trace", "delete"))],
    db: DB,
) -> Response:
    trace = get_trace_row(db, ctx.project.id, trace_id)
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="trace.deleted",
        target_type="trace",
        target_id=trace.trace_id,
        project_id=ctx.project.id,
    )
    db.delete(trace)
    db.commit()
    return Response(status_code=204)


@router.get("/analytics/overview", summary="Dashboard metrics for a time range")
def analytics_overview(
    ctx: ReadCtx,
    db: DB,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    end = (end or datetime.now(UTC)).astimezone(UTC)
    start = (start or end - timedelta(hours=24)).astimezone(UTC)
    if start >= end:
        raise APIError(400, "invalid_range", "start must be before end")
    if end - start > timedelta(days=90):
        raise APIError(400, "invalid_range", "time range may not exceed 90 days")
    return analytics.overview(db, ctx.project.id, start, end)
