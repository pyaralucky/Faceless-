"""Shared Redis client (rate limiting, progress pub/sub, job queue)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def set_redis(client: Redis | None) -> None:
    """Used by tests to inject a fake client."""
    global _client
    _client = client
