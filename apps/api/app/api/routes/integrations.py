from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import DB, ProjectContext, project_permission

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["integrations"])

# Implementation status is declared here, next to the code it describes. "tested" means an automated test in
# this repository exercises the integration path (see docs/integrations.md for the exact test files).
CATALOG: list[dict[str, Any]] = [
    {
        "id": "python-sdk",
        "name": "Python SDK",
        "status": "implemented",
        "tested": True,
        "evidence": "source",
        "evidence_value": "sdk",
        "install": "pip install ./packages/python-sdk",
        "docs": "docs/sdk.md",
    },
    {
        "id": "opentelemetry",
        "name": "OpenTelemetry (OTLP/HTTP)",
        "status": "implemented",
        "tested": True,
        "evidence": "source",
        "evidence_value": "otlp",
        "install": "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http",
        "docs": "docs/integrations.md#opentelemetry",
        "notes": "Protobuf and JSON encodings. gzip, span links, and non-exception events are not supported.",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "status": "implemented",
        "tested": True,
        "evidence": "integration",
        "evidence_value": "openai",
        "install": "pip install './packages/python-sdk[openai]'",
        "docs": "docs/integrations.md#openai",
        "notes": "Wraps chat.completions.create and responses.create (sync and async). Tested against a mocked "
        "HTTP transport; a live call requires your own OPENAI_API_KEY.",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "status": "implemented",
        "tested": True,
        "evidence": "integration",
        "evidence_value": "anthropic",
        "install": "pip install './packages/python-sdk[anthropic]'",
        "docs": "docs/integrations.md#anthropic",
        "notes": "Wraps messages.create (sync and async). Tested against a mocked HTTP transport.",
    },
    {
        "id": "langchain",
        "name": "LangChain",
        "status": "implemented",
        "tested": True,
        "evidence": "integration",
        "evidence_value": "langchain",
        "install": "pip install './packages/python-sdk[langchain]'",
        "docs": "docs/integrations.md#langchain",
        "notes": "Callback handler for chains, chat models/LLMs, tools, and retrievers.",
    },
    {
        "id": "langgraph",
        "name": "LangGraph",
        "status": "implemented",
        "tested": True,
        "evidence": "integration",
        "evidence_value": "langgraph",
        "install": "pip install './packages/python-sdk[langgraph]'",
        "docs": "docs/integrations.md#langgraph",
        "notes": "Uses the LangChain callback system; graph nodes become agent spans.",
    },
    {
        "id": "decorator",
        "name": "@observe decorator",
        "status": "implemented",
        "tested": True,
        "evidence": "source",
        "evidence_value": "sdk",
        "install": "pip install ./packages/python-sdk",
        "docs": "docs/sdk.md#decorator",
    },
    {
        "id": "langfuse",
        "name": "Langfuse import",
        "status": "not_implemented",
        "tested": False,
        "evidence": None,
        "evidence_value": None,
        "install": None,
        "docs": "docs/integrations.md#not-implemented",
        "notes": "Not implemented. Use OTLP export from your application instead.",
    },
]


@router.get("/integrations", summary="Integration catalog with data-derived connection evidence")
def integrations(
    ctx: Annotated[ProjectContext, Depends(project_permission("integration", "read"))], db: DB
) -> dict[str, Any]:
    by_source = {
        r["source"]: r
        for r in db.execute(
            text(
                "SELECT source, count(*) AS traces, max(start_time) AS last_seen FROM traces "
                "WHERE project_id = :pid GROUP BY source"
            ),
            {"pid": ctx.project.id},
        ).mappings()
    }
    by_integration = {
        r["integration"]: r
        for r in db.execute(
            text(
                "SELECT attributes->>'tracelens.integration' AS integration, count(*) AS spans, "
                "max(start_time) AS last_seen FROM spans WHERE project_id = :pid "
                "AND attributes ? 'tracelens.integration' GROUP BY 1"
            ),
            {"pid": ctx.project.id},
        ).mappings()
    }
    items = []
    for entry in CATALOG:
        seen = None
        if entry["evidence"] == "source":
            row = by_source.get(entry["evidence_value"])
            seen = {"count": row["traces"], "unit": "traces", "last_seen": row["last_seen"]} if row else None
        elif entry["evidence"] == "integration":
            row = by_integration.get(entry["evidence_value"])
            seen = {"count": row["spans"], "unit": "spans", "last_seen": row["last_seen"]} if row else None
        items.append(
            {
                **{k: v for k, v in entry.items() if not k.startswith("evidence")},
                "receiving_data": seen is not None,
                "data": seen,
            }
        )
    return {"items": items}
