from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, ProjectContext, project_permission
from app.core.errors import APIError, not_found
from app.models import Investigation
from app.services import diagnosis
from app.services.investigator import load_trace
from app.services.llm import LLMNotConfiguredError, resolve_config
from app.services.traces_query import get_trace_row
from app.workers.queue import QueueUnavailableError, enqueue

router = APIRouter(prefix="/api/v1/projects/{project_id}/traces/{trace_id}", tags=["investigations"])

ReadCtx = Annotated[ProjectContext, Depends(project_permission("investigation", "read"))]
RunCtx = Annotated[ProjectContext, Depends(project_permission("investigation", "run"))]


class InvestigationCreate(BaseModel):
    mode: Literal["deterministic", "ai"] = "deterministic"
    provider: Literal["openai", "anthropic"] | None = None


def _out(inv: Investigation) -> dict[str, Any]:
    return {
        "id": str(inv.id),
        "kind": inv.kind,
        "status": inv.status,
        "summary": inv.summary,
        "findings": inv.findings,
        "provider": inv.provider,
        "model": inv.model,
        "error": inv.error,
        "created_at": inv.created_at,
        "completed_at": inv.completed_at,
    }


@router.get("/diagnosis", summary="Run deterministic diagnostics (not persisted)")
def deterministic(trace_id: str, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    row = get_trace_row(db, ctx.project.id, trace_id)
    trace, spans = load_trace(db, row.id)
    return {"kind": "deterministic", "findings": diagnosis.diagnose(db, ctx.project, trace, spans)}


@router.get("/investigations", summary="List stored investigations for a trace")
def list_investigations(trace_id: str, ctx: ReadCtx, db: DB) -> list[dict[str, Any]]:
    row = get_trace_row(db, ctx.project.id, trace_id)
    rows = db.scalars(
        select(Investigation)
        .where(Investigation.trace_pk == row.id, Investigation.project_id == ctx.project.id)
        .order_by(Investigation.created_at.desc())
        .limit(20)
    )
    return [_out(i) for i in rows]


@router.get("/investigations/{investigation_id}", summary="Get one investigation (poll while queued)")
def get_investigation(trace_id: str, investigation_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    row = get_trace_row(db, ctx.project.id, trace_id)
    inv = db.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.trace_pk == row.id,
            Investigation.project_id == ctx.project.id,
        )
    )
    if inv is None:
        raise not_found("Investigation")
    return _out(inv)


@router.post("/investigations", status_code=201, summary="Start an investigation")
def create_investigation(trace_id: str, body: InvestigationCreate, ctx: RunCtx, db: DB) -> dict[str, Any]:
    row = get_trace_row(db, ctx.project.id, trace_id)
    if body.mode == "deterministic":
        trace, spans = load_trace(db, row.id)
        findings = diagnosis.diagnose(db, ctx.project, trace, spans)
        inv = Investigation(
            project_id=ctx.project.id,
            trace_pk=row.id,
            kind="deterministic",
            status="completed",
            findings={"deterministic": findings},
            summary=f"{len(findings)} deterministic finding(s)",
            created_by=ctx.user_id,
            completed_at=datetime.now(UTC),
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)
        return _out(inv)

    try:
        config = resolve_config(db, ctx.project.id, body.provider)
    except LLMNotConfiguredError as exc:
        raise APIError(400, "llm_not_configured", str(exc)) from exc
    inv = Investigation(
        project_id=ctx.project.id,
        trace_pk=row.id,
        kind="llm",
        status="queued",
        provider=config.provider,
        model=config.model,
        created_by=ctx.user_id,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    try:
        enqueue("run_investigation", str(inv.id))
    except QueueUnavailableError as exc:
        inv.status = "failed"
        inv.error = str(exc)
        inv.completed_at = datetime.now(UTC)
        db.commit()
        raise APIError(503, "queue_unavailable", str(exc)) from exc
    return _out(inv)
