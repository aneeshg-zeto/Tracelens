from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB, IngestAuth
from app.core.errors import APIError, not_found
from app.integrations import otlp
from app.models import Prompt, PromptVersion
from app.schemas.ingest import IngestBatch, IngestResponse, TraceIn
from app.services.ingest import ingest_batch as run_ingest

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


def _rate_headers(request: Request, response: Response) -> None:
    rl = getattr(request.state, "rate_limit", None)
    if rl is not None:
        response.headers["X-RateLimit-Limit"] = str(rl.limit)
        response.headers["X-RateLimit-Remaining"] = str(rl.remaining)


@router.post(
    "/ingest/batch",
    response_model=IngestResponse,
    status_code=202,
    summary="Ingest a batch of traces and spans",
    description=(
        "Authenticate with `Authorization: Bearer tl_live_...`. Upserts are idempotent on "
        "(trace_id) and (trace_id, span_id), so clients may safely retry."
    ),
)
def ingest_batch(batch: IngestBatch, auth: IngestAuth, db: DB, request: Request, response: Response) -> Any:
    result = run_ingest(db, auth.project, batch, source="sdk")
    _rate_headers(request, response)
    return IngestResponse(**result.__dict__)


@router.post("/traces", response_model=IngestResponse, status_code=202, summary="Ingest a single trace")
def ingest_single(trace: TraceIn, auth: IngestAuth, db: DB, request: Request, response: Response) -> Any:
    result = run_ingest(db, auth.project, IngestBatch(traces=[trace]), source="sdk")
    _rate_headers(request, response)
    return IngestResponse(**result.__dict__)


@router.post(
    "/otlp/v1/traces",
    status_code=200,
    summary="OTLP/HTTP trace export",
    description=(
        "Accepts ExportTraceServiceRequest as application/x-protobuf or application/json. Set "
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT to this URL and pass the API key via "
        "OTEL_EXPORTER_OTLP_HEADERS='Authorization=Bearer tl_live_...'."
    ),
)
async def otlp_traces(request: Request, auth: IngestAuth, db: DB) -> Response:
    if request.headers.get("content-encoding", "identity").lower() not in ("identity", ""):
        raise APIError(
            415, "unsupported_encoding", "Compressed OTLP bodies are not supported; disable compression"
        )
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    try:
        batch = otlp.to_batch(otlp.decode(body, content_type))
    except otlp.OTLPDecodeError as exc:
        raise APIError(400, "invalid_otlp", str(exc)) from exc
    await run_in_threadpool(run_ingest, db, auth.project, batch, "otlp")
    if content_type.startswith("application/x-protobuf"):
        return Response(ExportTraceServiceResponse().SerializeToString(), media_type="application/x-protobuf")
    return Response("{}", media_type="application/json")


@router.get("/ingest/whoami", summary="Validate an API key and return its project")
def whoami(auth: IngestAuth) -> dict[str, Any]:
    return {
        "project_id": str(auth.project.id),
        "project_name": auth.project.name,
        "key_prefix": auth.api_key.key_prefix,
        "capture_payloads": auth.project.capture_payloads,
    }


@router.get("/ingest/prompts/{name}", summary="Fetch the active (or a specific) published prompt version")
def fetch_prompt(name: str, auth: IngestAuth, db: DB, version: int | None = None) -> dict[str, Any]:
    prompt = db.scalar(select(Prompt).where(Prompt.project_id == auth.project.id, Prompt.name == name))
    if prompt is None:
        raise not_found("Prompt")
    stmt = select(PromptVersion).where(
        PromptVersion.prompt_id == prompt.id, PromptVersion.status == "published"
    )
    if version is not None:
        pv = db.scalar(stmt.where(PromptVersion.version == version))
    elif prompt.active_version_id is not None:
        pv = db.scalar(stmt.where(PromptVersion.id == prompt.active_version_id))
    else:
        pv = None
    if pv is None:
        raise not_found("Published prompt version")
    return {"name": prompt.name, "version": pv.version, "content": pv.content, "variables": pv.variables}
