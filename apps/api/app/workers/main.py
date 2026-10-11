"""ARQ worker: `arq app.workers.main.WorkerSettings`.

Jobs are thin wrappers around synchronous services, executed in a thread so the
event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from arq import cron

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.services.evaluations import execute_model_run
from app.services.investigator import run_ai_investigation
from app.services.retention import purge_expired
from app.workers.queue import redis_settings


def _with_session(fn: Any, *args: Any) -> Any:
    session = get_sessionmaker()()
    try:
        return fn(session, *args)
    finally:
        session.close()


async def run_investigation(ctx: dict[str, Any], investigation_id: str) -> None:
    await asyncio.to_thread(_with_session, run_ai_investigation, uuid.UUID(investigation_id))


async def run_model_evaluation(ctx: dict[str, Any], run_id: str) -> None:
    await asyncio.to_thread(_with_session, execute_model_run, uuid.UUID(run_id))


async def retention_job(ctx: dict[str, Any]) -> int:
    return await asyncio.to_thread(_with_session, purge_expired)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)


class WorkerSettings:
    functions = [run_investigation, run_model_evaluation]
    cron_jobs = [cron(retention_job, minute={17}, run_at_startup=True)]
    on_startup = startup
    redis_settings = redis_settings()
    max_jobs = 4
    job_timeout = 30 * 60
