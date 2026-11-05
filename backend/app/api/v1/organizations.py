"""Organizations (tenants), team membership and audit log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Admin, OrgContext, Viewer, client_ip, get_current_user
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.db.session import get_db
from app.models import AuditLog, Membership, Organization, User
from app.models.enums import ROLE_RANK, Role
from app.schemas.common import Message, Page
from app.schemas.identity import (
    AuditLogOut,
    MemberAdd,
    MemberOut,
    MemberUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.services.audit import record_audit
from app.services.auth import create_organization

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
async def my_organizations(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Organization]:
    stmt = select(Organization).join(Membership).where(Membership.user_id == user.id).order_by(Organization.name)
    return list((await db.scalars(stmt)).all())


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_org(
    data: OrganizationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Organization:
    org = await create_organization(db, data.name, user)
    record_audit(
        db, action="organization.created", org_id=org.id, actor_id=user.id, entity_type="organization", entity_id=org.id
    )
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/current", response_model=OrganizationOut)
async def current_org(ctx: OrgContext = Viewer) -> Organization:
    return ctx.organization


@router.patch("/current", response_model=OrganizationOut)
async def update_org(
    data: OrganizationUpdate, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> Organization:
    org = await db.get(Organization, ctx.org_id)
    assert org is not None
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(org, k, v)
    record_audit(
        db,
        action="organization.updated",
        org_id=org.id,
        actor_id=ctx.user.id,
        entity_type="organization",
        entity_id=org.id,
        data=changes,
    )
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/current/members", response_model=list[MemberOut])
async def list_members(ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> list[MemberOut]:
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == ctx.org_id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, joined_at=m.created_at)
        for m, u in rows
    ]


def _guard_role_change(ctx: OrgContext, target_role: Role) -> None:
    # Only owners may grant owner; admins can manage up to admin.
    if ROLE_RANK[target_role] > ROLE_RANK[ctx.role]:
        raise PermissionDeniedError("You cannot grant a role higher than your own")


@router.post("/current/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(
    data: MemberAdd, request: Request, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> MemberOut:
    _guard_role_change(ctx, data.role)
    user = await db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None:
        raise NotFoundError("No user with that email. Ask them to register first.", code="user_not_found")
    if await db.scalar(
        select(Membership.id).where(Membership.organization_id == ctx.org_id, Membership.user_id == user.id)
    ):
        raise ConflictError("User is already a member")
    m = Membership(organization_id=ctx.org_id, user_id=user.id, role=data.role)
    db.add(m)
    record_audit(
        db,
        action="member.added",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="user",
        entity_id=user.id,
        data={"role": data.role},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(m)
    return MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=m.role, joined_at=m.created_at)


async def _owner_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.scalar(select(func.count()).where(Membership.organization_id == org_id, Membership.role == Role.OWNER))
        or 0
    )


@router.patch("/current/members/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: uuid.UUID, data: MemberUpdate, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> MemberOut:
    _guard_role_change(ctx, data.role)
    m = await db.scalar(
        select(Membership).where(Membership.organization_id == ctx.org_id, Membership.user_id == user_id)
    )
    if m is None:
        raise NotFoundError("Member not found")
    if ROLE_RANK[Role(m.role)] > ROLE_RANK[ctx.role]:
        raise PermissionDeniedError("You cannot modify a member with a higher role")
    if m.role == Role.OWNER and data.role != Role.OWNER and await _owner_count(db, ctx.org_id) <= 1:
        raise ValidationFailedError("An organization must keep at least one owner")
    m.role = data.role
    record_audit(
        db,
        action="member.role_changed",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="user",
        entity_id=user_id,
        data={"role": data.role},
    )
    await db.commit()
    user = await db.get(User, user_id)
    assert user is not None
    return MemberOut(user_id=user.id, email=user.email, full_name=user.full_name, role=m.role, joined_at=m.created_at)


@router.delete("/current/members/{user_id}", response_model=Message)
async def remove_member(user_id: uuid.UUID, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)) -> Message:
    m = await db.scalar(
        select(Membership).where(Membership.organization_id == ctx.org_id, Membership.user_id == user_id)
    )
    if m is None:
        raise NotFoundError("Member not found")
    if ROLE_RANK[Role(m.role)] > ROLE_RANK[ctx.role]:
        raise PermissionDeniedError("You cannot remove a member with a higher role")
    if m.role == Role.OWNER and await _owner_count(db, ctx.org_id) <= 1:
        raise ValidationFailedError("An organization must keep at least one owner")
    await db.delete(m)
    record_audit(
        db, action="member.removed", org_id=ctx.org_id, actor_id=ctx.user.id, entity_type="user", entity_id=user_id
    )
    await db.commit()
    return Message(message="Member removed")


@router.get("/current/audit-logs", response_model=Page[AuditLogOut])
async def audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Admin,
    db: AsyncSession = Depends(get_db),
) -> Page[AuditLogOut]:
    base = select(AuditLog).where(AuditLog.organization_id == ctx.org_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(base.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[AuditLogOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)
