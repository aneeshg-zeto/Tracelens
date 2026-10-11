from __future__ import annotations

import asyncio
import logging
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings

logger = logging.getLogger("tracelens.queue")


class QueueUnavailableError(Exception):
    pass


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def _enqueue(function: str, *args: Any) -> str:
    pool = await create_pool(redis_settings())
    try:
        job = await pool.enqueue_job(function, *args)
        return job.job_id if job else ""
    finally:
        await pool.aclose()


def enqueue(function: str, *args: Any) -> str:
    """Enqueue an ARQ job from synchronous request handlers (which run in worker threads)."""
    try:
        return asyncio.run(_enqueue(function, *args))
    except (OSError, ConnectionError, TimeoutError) as exc:
        logger.error("failed to enqueue job", extra={"function": function, "error": type(exc).__name__})
        raise QueueUnavailableError("Background queue (Redis) is unavailable") from exc
    except Exception as exc:
        if exc.__class__.__module__.startswith("redis"):
            logger.error("failed to enqueue job", extra={"function": function, "error": type(exc).__name__})
            raise QueueUnavailableError("Background queue (Redis) is unavailable") from exc
        raise
