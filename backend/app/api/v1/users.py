"""Self-service profile + platform-level user administration (superusers)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_superuser
from app.core.errors import NotFoundError, ValidationFailedError
from app.db.session import get_db
from app.models import User
from app.schemas.common import Page
from app.schemas.identity import AdminUserUpdate, UserOut, UserUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
async def update_me(
    data: UserUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("", response_model=Page[UserOut])
async def list_users(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(get_superuser),
    db: AsyncSession = Depends(get_db),
) -> Page[UserOut]:
    stmt = select(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.full_name).like(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = (await db.scalars(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[UserOut.model_validate(u) for u in items], total=total, limit=limit, offset=offset)


@router.patch("/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    admin: User = Depends(get_superuser),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if user.id == admin.id and (data.is_active is False or data.is_superuser is False):
        raise ValidationFailedError("You cannot deactivate or demote yourself")
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(user, k, v)
    record_audit(
        db,
        action="admin.user_updated",
        org_id=None,
        actor_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        data=changes,
    )
    await db.commit()
    await db.refresh(user)
    return user
