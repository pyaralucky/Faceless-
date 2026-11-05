from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.config import settings
from app.models.enums import Role
from app.schemas.common import Entity, ORMModel


def _check_password(v: str) -> str:
    if len(v) < settings.password_min_length:
        raise ValueError(f"Password must be at least {settings.password_min_length} characters")
    if v.isalpha() or v.isdigit():
        raise ValueError("Password must mix letters with digits or symbols")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    full_name: str = Field(default="", max_length=200)
    organization_name: str = Field(default="", max_length=200)

    _pw = field_validator("password")(_check_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(max_length=256)

    _pw = field_validator("new_password")(_check_password)


class MembershipOut(ORMModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: Role


class UserOut(Entity):
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    email_verified: bool
    last_login_at: datetime | None


class MeOut(UserOut):
    memberships: list[MembershipOut] = []


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)


class AdminUserUpdate(UserUpdate):
    is_active: bool | None = None
    is_superuser: bool | None = None


class OrganizationOut(Entity):
    name: str
    slug: str
    plan: str
    monthly_token_budget: int | None
    settings: dict


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    monthly_token_budget: int | None = Field(default=None, ge=0)
    settings: dict | None = None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    joined_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role = Role.VIEWER


class MemberUpdate(BaseModel):
    role: Role


class AuditLogOut(Entity):
    actor_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    data: dict
