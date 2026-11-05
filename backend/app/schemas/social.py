from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ApprovalStatus, Platform, PublishStatus, SocialAccountStatus
from app.schemas.common import Entity


class SocialAccountOut(Entity):
    channel_id: uuid.UUID | None
    platform: Platform
    external_id: str
    display_name: str
    avatar_url: str | None
    token_expires_at: datetime | None
    scopes: list[str]
    status: SocialAccountStatus
    meta: dict[str, Any]


class SocialAccountUpdate(BaseModel):
    channel_id: uuid.UUID | None = None


class OAuthStartOut(BaseModel):
    authorization_url: str


class PublishJobCreate(BaseModel):
    project_id: uuid.UUID
    social_account_id: uuid.UUID
    render_job_id: uuid.UUID | None = Field(default=None, description="Omitted = latest successful render")
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    privacy: Literal["private", "unlisted", "public"] = "private"
    scheduled_at: datetime | None = Field(default=None, description="UTC; omitted = publish as soon as approved")


class PublishJobUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    privacy: Literal["private", "unlisted", "public"] | None = None
    scheduled_at: datetime | None = None


class PublishJobOut(Entity):
    project_id: uuid.UUID
    social_account_id: uuid.UUID
    render_job_id: uuid.UUID
    platform: Platform
    status: PublishStatus
    title: str
    description: str
    tags: list[str]
    privacy: str
    scheduled_at: datetime | None
    next_attempt_at: datetime | None
    attempts: int
    max_attempts: int
    upload_progress: float
    last_error: str | None
    external_id: str | None
    external_url: str | None
    published_at: datetime | None
    history: list[dict[str, Any]]


class ApprovalCreate(BaseModel):
    project_id: uuid.UUID
    publish_job_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=2000)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


class ApprovalOut(Entity):
    project_id: uuid.UUID
    publish_job_id: uuid.UUID | None
    requested_by_id: uuid.UUID | None
    reviewer_id: uuid.UUID | None
    status: ApprovalStatus
    request_note: str
    decision_note: str | None
    decided_at: datetime | None


class AnalyticsSnapshotOut(Entity):
    publish_job_id: uuid.UUID
    platform: Platform
    external_id: str
    captured_at: datetime
    views: int
    likes: int
    comments: int
    shares: int
    saves: int
    impressions: int
    reach: int
    watch_time_minutes: float
    avg_view_duration_sec: float


class PerformanceRow(BaseModel):
    publish_job_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    platform: Platform
    external_url: str | None
    published_at: datetime | None
    views: int
    likes: int
    comments: int
    shares: int
    engagement_rate: float
    watch_time_minutes: float


class PerformanceReport(BaseModel):
    period_start: datetime
    period_end: datetime
    totals: dict[str, float]
    by_platform: dict[str, dict[str, float]]
    by_channel: list[dict[str, Any]]
    top_posts: list[PerformanceRow]
    daily: list[dict[str, Any]]
