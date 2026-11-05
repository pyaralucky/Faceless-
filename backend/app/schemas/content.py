from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.models.enums import LLMProvider, ProjectStatus, VideoFormat
from app.schemas.common import Entity


class ChannelBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    niche: str = Field(default="", max_length=200)
    description: str = ""
    language: str = Field(default="en", max_length=10)
    tone: str = Field(default="informative, engaging", max_length=200)
    target_audience: str = Field(default="", max_length=300)
    default_format: VideoFormat = VideoFormat.VERTICAL
    require_approval: bool = True
    branding: dict[str, Any] = Field(default_factory=dict)


class ChannelCreate(ChannelBase):
    pass


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    niche: str | None = None
    description: str | None = None
    language: str | None = None
    tone: str | None = None
    target_audience: str | None = None
    default_format: VideoFormat | None = None
    require_approval: bool | None = None
    is_active: bool | None = None
    branding: dict[str, Any] | None = None


class ChannelOut(ChannelBase, Entity):
    organization_id: uuid.UUID
    is_active: bool
    project_count: int = 0


class ProjectCreate(BaseModel):
    channel_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    topic: str = ""
    format: VideoFormat | None = None
    target_duration_sec: int = Field(default=60, ge=10, le=3600)
    brief: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    topic: str | None = None
    format: VideoFormat | None = None
    target_duration_sec: int | None = Field(default=None, ge=10, le=3600)
    brief: dict[str, Any] | None = None
    status: ProjectStatus | None = None
    script: dict[str, Any] | None = None
    storyboard: dict[str, Any] | None = None
    optimization: dict[str, Any] | None = None


class ProjectSummary(Entity):
    organization_id: uuid.UUID
    channel_id: uuid.UUID
    title: str
    topic: str
    status: ProjectStatus
    format: VideoFormat
    target_duration_sec: int


class ProjectOut(ProjectSummary):
    brief: dict[str, Any]
    research: dict[str, Any]
    strategy: dict[str, Any]
    script: dict[str, Any]
    fact_check: dict[str, Any]
    storyboard: dict[str, Any]
    optimization: dict[str, Any]


class AssetOut(Entity):
    project_id: uuid.UUID | None
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    duration_sec: float | None
    width: int | None
    height: int | None
    meta: dict[str, Any]


# --------------------------------------------------------------- API configuration


class CredentialCreate(BaseModel):
    provider: LLMProvider
    label: str = Field(default="default", max_length=80)
    api_key: str = Field(min_length=1, max_length=4000)
    base_url: HttpUrl | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class CredentialUpdate(BaseModel):
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)
    base_url: HttpUrl | None = None
    is_active: bool | None = None
    config: dict[str, Any] | None = None


class CredentialOut(Entity):
    provider: str
    label: str
    key_hint: str
    base_url: str | None
    is_active: bool
    config: dict[str, Any]


class ModelTarget(BaseModel):
    provider: LLMProvider
    model: str = Field(min_length=1, max_length=120)


class ModelRouteUpsert(BaseModel):
    provider: LLMProvider
    model: str = Field(min_length=1, max_length=120)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=64, le=200_000)
    fallbacks: list[ModelTarget] = Field(default_factory=list)


class ModelRouteOut(Entity):
    agent_name: str
    provider: str
    model: str
    temperature: float
    max_tokens: int
    fallbacks: list[dict[str, Any]]
