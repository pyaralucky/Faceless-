"""Tenant-scoped lookups. Every fetch by id goes through here so cross-tenant access is impossible."""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError

M = TypeVar("M")


async def get_scoped(
    db: AsyncSession, model: type[M], obj_id: uuid.UUID, org_id: uuid.UUID, *, label: str | None = None
) -> M:
    obj = await db.scalar(select(model).where(model.id == obj_id, model.organization_id == org_id))  # type: ignore[attr-defined]
    if obj is None:
        raise NotFoundError(f"{label or model.__name__} not found")
    return obj
