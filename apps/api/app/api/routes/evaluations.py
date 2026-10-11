from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, IngestAuth, ProjectContext, project_permission
from app.core.errors import APIError, not_found
from app.core.redaction import bound_payload
from app.models import EvaluationDataset, EvaluationExample, EvaluationResult, EvaluationRun
from app.services.evaluations import compare_runs, record_submitted_results
from app.services.evaluators import PROBABILISTIC, EvaluatorSpec
from app.services.llm import LLMNotConfiguredError, resolve_config
from app.workers.queue import QueueUnavailableError, enqueue

router = APIRouter(prefix="/api/v1", tags=["evaluations"])

ReadCtx = Annotated[ProjectContext, Depends(project_permission("evaluation", "read"))]
CreateCtx = Annotated[ProjectContext, Depends(project_permission("evaluation", "create"))]
RunCtx = Annotated[ProjectContext, Depends(project_permission("evaluation", "run"))]
BASE = "/projects/{project_id}/evaluations"


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ExampleIn(BaseModel):
    input: Any
    expected_output: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _has_input(self) -> ExampleIn:
        if self.input is None:
            raise ValueError("input is required")
        return self


class ExamplesCreate(BaseModel):
    examples: list[ExampleIn] = Field(min_length=1, max_length=500)


class ModelTarget(BaseModel):
    type: Literal["model"] = "model"
    provider: Literal["openai", "anthropic"] | None = None
    model: str | None = Field(default=None, max_length=128)
    system_prompt: str | None = Field(default=None, max_length=8000)
    prompt_template: str = Field(default="{{input}}", min_length=1, max_length=16000)
    json_output: bool = False
    max_tokens: int = Field(default=800, ge=1, le=8000)


class RunCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target: ModelTarget
    evaluators: list[EvaluatorSpec] = Field(min_length=1, max_length=10)
    acknowledge_external_calls: bool = False


class SubmittedResult(BaseModel):
    example_id: uuid.UUID
    output: Any = None
    error: str | None = Field(default=None, max_length=4000)
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    trace_id: str | None = Field(default=None, max_length=128)


class SubmittedRun(BaseModel):
    dataset: str = Field(min_length=1, max_length=120, description="Dataset name")
    name: str = Field(min_length=1, max_length=120)
    evaluators: list[EvaluatorSpec] = Field(min_length=1, max_length=10)
    results: list[SubmittedResult] = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _dataset(db: DB, project_id: uuid.UUID, dataset_id: uuid.UUID) -> EvaluationDataset:
    ds = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.id == dataset_id, EvaluationDataset.project_id == project_id
        )
    )
    if ds is None:
        raise not_found("Dataset")
    return ds


def _run(db: DB, project_id: uuid.UUID, run_id: uuid.UUID) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.project_id == project_id)
    )
    if run is None:
        raise not_found("Evaluation run")
    return run


def _example_out(e: EvaluationExample) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "input": e.input,
        "expected_output": e.expected_output,
        "metadata": e.metadata_,
        "created_at": e.created_at,
    }


def _run_out(r: EvaluationRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "dataset_id": str(r.dataset_id),
        "name": r.name,
        "target_type": r.target_type,
        "target_config": r.target_config,
        "evaluators": r.evaluators,
        "makes_external_calls": r.makes_external_calls,
        "status": r.status,
        "summary": r.summary,
        "error": r.error,
        "created_at": r.created_at,
        "completed_at": r.completed_at,
    }


@router.get(BASE + "/datasets", summary="List datasets")
def list_datasets(ctx: ReadCtx, db: DB) -> list[dict[str, Any]]:
    ex_count = (
        select(EvaluationExample.dataset_id, func.count().label("n"))
        .group_by(EvaluationExample.dataset_id)
        .subquery()
    )
    run_count = (
        select(EvaluationRun.dataset_id, func.count().label("n"))
        .group_by(EvaluationRun.dataset_id)
        .subquery()
    )
    rows = db.execute(
        select(EvaluationDataset, ex_count.c.n, run_count.c.n)
        .outerjoin(ex_count, ex_count.c.dataset_id == EvaluationDataset.id)
        .outerjoin(run_count, run_count.c.dataset_id == EvaluationDataset.id)
        .where(EvaluationDataset.project_id == ctx.project.id)
        .order_by(EvaluationDataset.created_at.desc())
    ).all()
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "description": d.description,
            "created_at": d.created_at,
            "example_count": ne or 0,
            "run_count": nr or 0,
        }
        for d, ne, nr in rows
    ]


@router.post(BASE + "/datasets", status_code=201, summary="Create a dataset")
def create_dataset(body: DatasetCreate, ctx: CreateCtx, db: DB) -> dict[str, Any]:
    ds = EvaluationDataset(
        project_id=ctx.project.id,
        name=body.name.strip(),
        description=body.description,
        created_by=ctx.user_id,
    )
    db.add(ds)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise APIError(409, "conflict", "A dataset with this name already exists") from exc
    db.refresh(ds)
    return {"id": str(ds.id), "name": ds.name, "description": ds.description, "created_at": ds.created_at}


@router.get(BASE + "/datasets/{dataset_id}", summary="Dataset with examples and runs")
def get_dataset(dataset_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    ds = _dataset(db, ctx.project.id, dataset_id)
    examples = db.scalars(
        select(EvaluationExample)
        .where(EvaluationExample.dataset_id == ds.id)
        .order_by(EvaluationExample.created_at)
        .limit(500)
    )
    runs = db.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.dataset_id == ds.id)
        .order_by(EvaluationRun.created_at.desc())
    )
    return {
        "dataset": {
            "id": str(ds.id),
            "name": ds.name,
            "description": ds.description,
            "created_at": ds.created_at,
        },
        "examples": [_example_out(e) for e in examples],
        "runs": [_run_out(r) for r in runs],
    }


@router.delete(BASE + "/datasets/{dataset_id}", status_code=204, summary="Delete a dataset and its runs")
def delete_dataset(dataset_id: uuid.UUID, ctx: CreateCtx, db: DB) -> Response:
    db.delete(_dataset(db, ctx.project.id, dataset_id))
    db.commit()
    return Response(status_code=204)


@router.post(BASE + "/datasets/{dataset_id}/examples", status_code=201, summary="Add examples")
def add_examples(dataset_id: uuid.UUID, body: ExamplesCreate, ctx: CreateCtx, db: DB) -> list[dict[str, Any]]:
    ds = _dataset(db, ctx.project.id, dataset_id)
    count = db.scalar(select(func.count()).where(EvaluationExample.dataset_id == ds.id)) or 0
    if count + len(body.examples) > 5000:
        raise APIError(400, "limit_reached", "A dataset can hold at most 5000 examples")
    rows = [
        EvaluationExample(
            dataset_id=ds.id,
            input=bound_payload(e.input),
            expected_output=bound_payload(e.expected_output),
            metadata_=bound_payload(e.metadata) or {},
        )
        for e in body.examples
    ]
    db.add_all(rows)
    db.commit()
    return [_example_out(r) for r in rows]


@router.delete(BASE + "/datasets/{dataset_id}/examples/{example_id}", status_code=204)
def delete_example(dataset_id: uuid.UUID, example_id: uuid.UUID, ctx: CreateCtx, db: DB) -> Response:
    ds = _dataset(db, ctx.project.id, dataset_id)
    ex = db.scalar(
        select(EvaluationExample).where(
            EvaluationExample.id == example_id, EvaluationExample.dataset_id == ds.id
        )
    )
    if ex is None:
        raise not_found("Example")
    db.delete(ex)
    db.commit()
    return Response(status_code=204)


@router.post(
    BASE + "/datasets/{dataset_id}/runs", status_code=201, summary="Start a model-backed evaluation run"
)
def create_run(dataset_id: uuid.UUID, body: RunCreate, ctx: RunCtx, db: DB) -> dict[str, Any]:
    ds = _dataset(db, ctx.project.id, dataset_id)
    if not body.acknowledge_external_calls:
        raise APIError(
            400,
            "confirmation_required",
            "Model-backed runs call an external provider and may incur cost. Set "
            "acknowledge_external_calls=true to proceed.",
        )
    n = db.scalar(select(func.count()).where(EvaluationExample.dataset_id == ds.id)) or 0
    if n == 0:
        raise APIError(400, "empty_dataset", "Add examples before running an evaluation")
    try:
        config = resolve_config(db, ctx.project.id, body.target.provider, body.target.model)
    except LLMNotConfiguredError as exc:
        raise APIError(400, "llm_not_configured", str(exc)) from exc
    target = body.target.model_dump()
    target.update(provider=config.provider, model=config.model)
    run = EvaluationRun(
        project_id=ctx.project.id,
        dataset_id=ds.id,
        name=body.name.strip(),
        target_type="model",
        target_config=target,
        evaluators=[e.model_dump() for e in body.evaluators],
        makes_external_calls=True,
        status="queued",
        created_by=ctx.user_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        enqueue("run_model_evaluation", str(run.id))
    except QueueUnavailableError as exc:
        run.status = "failed"
        run.error = str(exc)
        db.commit()
        raise APIError(503, "queue_unavailable", str(exc)) from exc
    return _run_out(run)


@router.get(BASE + "/runs/{run_id}", summary="Run with per-example results")
def get_run(run_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    run = _run(db, ctx.project.id, run_id)
    results = db.execute(
        select(EvaluationResult, EvaluationExample)
        .join(EvaluationExample, EvaluationExample.id == EvaluationResult.example_id)
        .where(EvaluationResult.run_id == run.id)
        .order_by(EvaluationExample.created_at)
    ).all()
    return {
        "run": _run_out(run),
        "results": [
            {
                "example_id": str(ex.id),
                "input": ex.input,
                "expected_output": ex.expected_output,
                "output": r.output,
                "passed": r.passed,
                "scores": r.scores,
                "latency_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
                "error": r.error,
                "trace_id": r.trace_id,
            }
            for r, ex in results
        ],
    }


@router.get(BASE + "/compare", summary="Compare two runs on the same dataset")
def compare(base: uuid.UUID, candidate: uuid.UUID, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    a, b = _run(db, ctx.project.id, base), _run(db, ctx.project.id, candidate)
    if a.dataset_id != b.dataset_id:
        raise APIError(400, "dataset_mismatch", "Both runs must use the same dataset")
    return compare_runs(db, a, b)


# --- SDK endpoints (project API key) ------------------------------------------


@router.get("/ingest/evaluations/datasets/{name}", summary="Fetch a dataset's examples for local execution")
def sdk_dataset(name: str, auth: IngestAuth, db: DB) -> dict[str, Any]:
    ds = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.project_id == auth.project.id, EvaluationDataset.name == name
        )
    )
    if ds is None:
        raise not_found("Dataset")
    examples = db.scalars(
        select(EvaluationExample)
        .where(EvaluationExample.dataset_id == ds.id)
        .order_by(EvaluationExample.created_at)
        .limit(5000)
    )
    return {
        "id": str(ds.id),
        "name": ds.name,
        "examples": [
            {"id": str(e.id), "input": e.input, "expected_output": e.expected_output} for e in examples
        ],
    }


@router.post(
    "/ingest/evaluations/runs", status_code=201, summary="Submit outputs produced locally and score them"
)
def sdk_submit_run(body: SubmittedRun, auth: IngestAuth, db: DB) -> dict[str, Any]:
    ds = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.project_id == auth.project.id, EvaluationDataset.name == body.dataset
        )
    )
    if ds is None:
        raise not_found("Dataset")
    run = EvaluationRun(
        project_id=auth.project.id,
        dataset_id=ds.id,
        name=body.name.strip(),
        target_type="sdk",
        target_config={"metadata": bound_payload(body.metadata) or {}},
        evaluators=[e.model_dump() for e in body.evaluators],
        makes_external_calls=any(e.type in PROBABILISTIC for e in body.evaluators),
        status="running",
    )
    db.add(run)
    db.flush()
    record_submitted_results(db, run, auth.project, [r.model_dump() for r in body.results])
    db.refresh(run)
    return _run_out(run)
