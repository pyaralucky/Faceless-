"""Async SQLAlchemy engine/session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def build_engine(url: str | None = None) -> AsyncEngine:
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow)
    return create_async_engine(url, **kwargs)


engine = build_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
