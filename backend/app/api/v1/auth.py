from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import client_ip, get_current_user
from app.core.config import settings
from app.core.errors import AuthenticationError
from app.core.rate_limit import enforce_rate_limit
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models import Membership, User
from app.schemas.common import Message
from app.schemas.identity import (
    ChangePasswordRequest,
    LoginRequest,
    MembershipOut,
    MeOut,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services import auth as auth_service
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


async def build_me(db: AsyncSession, user: User) -> MeOut:
    rows = (
        await db.scalars(
            select(Membership).where(Membership.user_id == user.id).options(selectinload(Membership.organization))
        )
    ).all()
    me = MeOut(**UserOut.model_validate(user).model_dump(), memberships=[])
    me.memberships = [
        MembershipOut(
            organization_id=m.organization_id,
            organization_name=m.organization.name,
            organization_slug=m.organization.slug,
            role=m.role,
        )
        for m in rows
    ]
    return me


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenPair:
    ip = client_ip(request)
    await enforce_rate_limit(f"register:{ip}", settings.login_rate_limit_per_minute)
    user, org = await auth_service.register_user(db, data)
    record_audit(
        db, action="user.registered", org_id=org.id, actor_id=user.id, entity_type="user", entity_id=user.id, ip=ip
    )
    return await auth_service.issue_tokens(db, user, user_agent=request.headers.get("user-agent"), ip=ip)


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenPair:
    ip = client_ip(request)
    await enforce_rate_limit(f"login:{ip}", settings.login_rate_limit_per_minute)
    await enforce_rate_limit(f"login:{data.email.lower()}", settings.login_rate_limit_per_minute)
    user = await auth_service.authenticate(db, data.email, data.password)
    return await auth_service.issue_tokens(db, user, user_agent=request.headers.get("user-agent"), ip=ip)


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenPair:
    return await auth_service.rotate_refresh_token(
        db, data.refresh_token, request.headers.get("user-agent"), client_ip(request)
    )


@router.post("/logout", response_model=Message)
async def logout(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> Message:
    await auth_service.revoke_refresh_token(db, data.refresh_token)
    return Message(message="Signed out")


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeOut:
    return await build_me(db, user)


@router.post("/change-password", response_model=Message)
async def change_password(
    data: ChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Message:
    if not verify_password(data.current_password, user.hashed_password):
        raise AuthenticationError("Current password is incorrect", code="invalid_credentials")
    user.hashed_password = hash_password(data.new_password)
    record_audit(
        db, action="user.password_changed", org_id=None, actor_id=user.id, entity_type="user", entity_id=user.id
    )
    await db.commit()
    return Message(message="Password updated")
