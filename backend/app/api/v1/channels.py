from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Admin, Editor, OrgContext, Viewer
from app.core.errors import ConflictError
from app.db.session import get_db
from app.models import Channel, Project
from app.schemas.common import Message
from app.schemas.content import ChannelCreate, ChannelOut, ChannelUpdate
from app.services.audit import record_audit
from app.services.scoping import get_scoped

router = APIRouter(prefix="/channels", tags=["channels"])


async def _out(db: AsyncSession, ch: Channel) -> ChannelOut:
    count = await db.scalar(select(func.count()).where(Project.channel_id == ch.id)) or 0
    out = ChannelOut.model_validate(ch, from_attributes=True)
    out.project_count = count
    return out


async def _name_taken(db: AsyncSession, org_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Channel.id).where(Channel.organization_id == org_id, func.lower(Channel.name) == name.lower())
    if exclude:
        stmt = stmt.where(Channel.id != exclude)
    return (await db.scalar(stmt)) is not None


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    include_inactive: bool = False, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)
) -> list[ChannelOut]:
    counts = (
        select(Project.channel_id, func.count().label("n"))
        .where(Project.organization_id == ctx.org_id)
        .group_by(Project.channel_id)
        .subquery()
    )
    stmt = (
        select(Channel, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.channel_id == Channel.id)
        .where(Channel.organization_id == ctx.org_id)
        .order_by(Channel.name)
    )
    if not include_inactive:
        stmt = stmt.where(Channel.is_active.is_(True))
    result = []
    for ch, n in (await db.execute(stmt)).all():
        o = ChannelOut.model_validate(ch, from_attributes=True)
        o.project_count = n
        result.append(o)
    return result


@router.post("", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    data: ChannelCreate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> ChannelOut:
    if await _name_taken(db, ctx.org_id, data.name):
        raise ConflictError("A channel with this name already exists")
    ch = Channel(organization_id=ctx.org_id, **data.model_dump())
    db.add(ch)
    await db.flush()
    record_audit(
        db, action="channel.created", org_id=ctx.org_id, actor_id=ctx.user.id, entity_type="channel", entity_id=ch.id
    )
    await db.commit()
    await db.refresh(ch)
    return await _out(db, ch)


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)
) -> ChannelOut:
    return await _out(db, await get_scoped(db, Channel, channel_id, ctx.org_id))


@router.patch("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: uuid.UUID, data: ChannelUpdate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> ChannelOut:
    ch = await get_scoped(db, Channel, channel_id, ctx.org_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and await _name_taken(db, ctx.org_id, changes["name"], exclude=ch.id):
        raise ConflictError("A channel with this name already exists")
    for k, v in changes.items():
        setattr(ch, k, v)
    record_audit(
        db,
        action="channel.updated",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="channel",
        entity_id=ch.id,
        data={"fields": list(changes)},
    )
    await db.commit()
    await db.refresh(ch)
    return await _out(db, ch)


@router.delete("/{channel_id}", response_model=Message)
async def delete_channel(channel_id: uuid.UUID, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)) -> Message:
    ch = await get_scoped(db, Channel, channel_id, ctx.org_id)
    await db.delete(ch)
    record_audit(
        db,
        action="channel.deleted",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="channel",
        entity_id=channel_id,
        data={"name": ch.name},
    )
    await db.commit()
    return Message(message="Channel deleted")
