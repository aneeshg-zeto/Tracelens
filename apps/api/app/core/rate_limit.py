from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import redis

from app.core.config import get_settings

logger = logging.getLogger("tracelens.ratelimit")


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5, decode_responses=True
    )


class RateLimiter:
    """Fixed one-minute window counter in Redis.

    If Redis is unreachable the request is allowed and an error is logged:
    ingestion availability is preferred over strict limiting, and /health/ready
    reports Redis as down so operators notice.
    """

    def __init__(self, client: redis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> redis.Redis:
        return self._client or get_redis()

    def hit(self, bucket: str, limit: int, window_seconds: int = 60) -> RateLimitResult:
        now = int(time.time())
        window = now // window_seconds
        key = f"tl:rl:{bucket}:{window}"
        reset = window_seconds - (now % window_seconds)
        try:
            pipe = self.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds + 5)
            count, _ = pipe.execute()
        except redis.RedisError as exc:
            logger.error("rate limiter unavailable; allowing request", extra={"error": type(exc).__name__})
            return RateLimitResult(True, limit, limit, reset)
        count = int(count)
        return RateLimitResult(count <= limit, limit, max(0, limit - count), reset)


_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _limiter
