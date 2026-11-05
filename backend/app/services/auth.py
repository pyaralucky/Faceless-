"""Authentication service: registration, login and refresh-token rotation with reuse detection."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models import Membership, Organization, RefreshToken, User
from app.models.enums import Role
from app.schemas.identity import RegisterRequest, TokenPair

log = get_logger(__name__)

# Constant-time-ish dummy hash so unknown emails take as long as wrong passwords.
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug or "workspace"


async def unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    slug = base
    while await db.scalar(select(Organization.id).where(Organization.slug == slug)):
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


async def create_organization(db: AsyncSession, name: str, owner: User) -> Organization:
    org = Organization(name=name, slug=await unique_slug(db, name))
    db.add(org)
    await db.flush()
    db.add(Membership(organization_id=org.id, user_id=owner.id, role=Role.OWNER))
    return org


async def register_user(db: AsyncSession, data: RegisterRequest) -> tuple[User, Organization]:
    email = data.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("An account with this email already exists", code="email_taken")
    first_user = (await db.scalar(select(User.id).limit(1))) is None
    user = User(
        email=email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        is_superuser=first_user,  # bootstrap: first account administers the platform
    )
    db.add(user)
    await db.flush()
    org_name = data.organization_name or f"{data.full_name or email.split('@')[0]}'s Studio"
    org = await create_organization(db, org_name, user)
    await db.commit()
    log.info("user_registered", extra={"user_id": str(user.id), "org_id": str(org.id)})
    return user, org


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password", code="invalid_credentials")
    if not verify_password(password, user.hashed_password):
        raise AuthenticationError("Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise AuthenticationError("Account disabled", code="account_disabled")
    return user


async def issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> TokenPair:
    raw, digest = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
            user_agent=(user_agent or "")[:400] or None,
            ip_address=ip,
        )
    )
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def rotate_refresh_token(db: AsyncSession, raw: str, user_agent: str | None, ip: str | None) -> TokenPair:
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if token is None:
        raise AuthenticationError("Invalid refresh token", code="invalid_token")
    if token.revoked_at is not None:
        # Reuse of a rotated token => likely theft. Revoke the whole family.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
        log.warning("refresh_token_reuse_detected", extra={"user_id": str(token.user_id)})
        raise AuthenticationError("Refresh token reuse detected; please sign in again", code="token_reused")
    if _aware(token.expires_at) < datetime.now(UTC):
        raise AuthenticationError("Refresh token expired", code="token_expired")
    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User inactive", code="account_disabled")
    token.revoked_at = datetime.now(UTC)
    return await issue_tokens(db, user, family_id=token.family_id, user_agent=user_agent, ip=ip)


async def revoke_refresh_token(db: AsyncSession, raw: str) -> None:
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if token and token.revoked_at is None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
