"""Request dependencies: authentication, tenant context and role-based access control."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, NotFoundError, PermissionDeniedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Membership, Organization, User
from app.models.enums import ROLE_RANK, Role

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationError("Missing bearer token")
    payload = decode_token(creds.credentials, "access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token subject") from exc
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User inactive or not found")
    return user


async def get_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise PermissionDeniedError("Platform administrator privileges required")
    return user


@dataclass(slots=True)
class OrgContext:
    user: User
    organization: Organization
    role: Role

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id

    def has_role(self, minimum: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]

    def require(self, minimum: Role) -> None:
        if not self.has_role(minimum):
            raise PermissionDeniedError(f"Requires role '{minimum}' or higher")


async def get_org_context(
    x_org_id: uuid.UUID = Header(..., alias="X-Org-Id", description="Active organization (tenant) id"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgContext:
    org = await db.get(Organization, x_org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    membership = await db.scalar(
        select(Membership).where(Membership.organization_id == org.id, Membership.user_id == user.id)
    )
    if membership is None:
        if user.is_superuser:
            return OrgContext(user=user, organization=org, role=Role.OWNER)
        raise NotFoundError("Organization not found")  # don't leak existence
    return OrgContext(user=user, organization=org, role=Role(membership.role))


def require_role(minimum: Role):
    async def _dep(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        ctx.require(minimum)
        return ctx

    return _dep


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


Viewer = Depends(require_role(Role.VIEWER))
Reviewer = Depends(require_role(Role.REVIEWER))
Editor = Depends(require_role(Role.EDITOR))
Admin = Depends(require_role(Role.ADMIN))
Owner = Depends(require_role(Role.OWNER))
