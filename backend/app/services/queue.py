"""Thin abstraction over the arq job queue so API code stays testable."""

from __future__ import annotations

from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class JobQueue(Protocol):
    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None: ...


class ArqQueue:
    def __init__(self) -> None:
        self._pool: ArqRedis | None = None

    async def _get(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        return self._pool

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        pool = await self._get()
        await pool.enqueue_job(function, *args, _job_id=job_id)
        log.info("job_enqueued", extra={"function": function, "job_id": job_id})


class InMemoryQueue:
    """Records jobs instead of dispatching them (tests / local scripts)."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        self.jobs.append((function, args, job_id))


_queue: JobQueue = ArqQueue()


def get_queue() -> JobQueue:
    return _queue


def set_queue(q: JobQueue) -> None:
    global _queue
    _queue = q
