"""Fixed-window rate limiter backed by Redis. Fails open if Redis is unavailable."""

from __future__ import annotations

import time

from redis.exceptions import RedisError

from app.core.errors import RateLimitedError
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger(__name__)


async def enforce_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
    try:
        r = get_redis()
        count = await r.incr(bucket)
        if count == 1:
            await r.expire(bucket, window_seconds)
    except (RedisError, OSError) as exc:  # pragma: no cover - availability over strictness
        log.warning("rate_limit_unavailable", extra={"error": str(exc)})
        return
    if count > limit:
        raise RateLimitedError("Too many requests, please slow down", details={"retry_after": window_seconds})
