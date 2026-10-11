from __future__ import annotations

import logging

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.rate_limit import get_redis
from app.db.session import get_engine

router = APIRouter(tags=["health"])
logger = logging.getLogger("tracelens.health")


@router.get("/health/live", summary="Liveness probe")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe (database and Redis)")
def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        checks["database"] = "ok"
        checks["migration"] = str(revision)
    except SQLAlchemyError as exc:
        logger.error("database readiness failed", extra={"error": type(exc).__name__})
        checks["database"] = "unavailable"
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except redis.RedisError as exc:
        logger.error("redis readiness failed", extra={"error": type(exc).__name__})
        checks["redis"] = "unavailable"
    healthy = checks.get("database") == "ok" and checks.get("redis") == "ok"
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503
    )
