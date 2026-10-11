from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    evaluations,
    health,
    ingest,
    integrations,
    investigations,
    onboarding,
    projects,
    prompts,
    traces,
)
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware

DESCRIPTION = """
TraceLens ingestion and query API.

* **Ingestion** endpoints (`/api/v1/ingest/*`, `/api/v1/traces`, `/api/v1/otlp/v1/traces`) authenticate with
  a project API key: `Authorization: Bearer tl_live_...`.
* **Dashboard** endpoints authenticate with a short-lived JWT minted by the TraceLens web server in the
  `X-TraceLens-Internal-Token` header. They are not intended for direct use.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="TraceLens API",
        version="0.1.0",
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-TraceLens-Api-Key"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)
    for module in (
        health,
        ingest,
        projects,
        traces,
        onboarding,
        investigations,
        evaluations,
        prompts,
        integrations,
    ):
        app.include_router(module.router)
    return app


app = create_app()
