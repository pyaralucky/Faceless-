"""Social platform accounts, publishing queue, approvals and analytics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import ApprovalStatus, PublishStatus, SocialAccountStatus


class SocialAccount(UUIDPk, Timestamps, Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "platform", "external_id", name="uq_social_org_platform_ext"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    avatar_url: Mapped[str | None] = mapped_column(String(600))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default=SocialAccountStatus.ACTIVE)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class PublishJob(UUIDPk, Timestamps, Base):
    __tablename__ = "publish_jobs"
    __table_args__ = (Index("ix_publish_due", "status", "next_attempt_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    social_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("social_accounts.id", ondelete="CASCADE"), index=True
    )
    render_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("render_jobs.id", ondelete="CASCADE"))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default=PublishStatus.DRAFT)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[Any]] = mapped_column(default=list)
    privacy: Mapped[str] = mapped_column(String(20), default="private")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    upload_progress: Mapped[float] = mapped_column(Float, default=0.0)
    last_error: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(120))
    external_url: Mapped[str | None] = mapped_column(String(600))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # platform-specific resumable state (e.g. YouTube upload session URI, IG container id)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    history: Mapped[list[Any]] = mapped_column(default=list)


class ApprovalRequest(UUIDPk, Timestamps, Base):
    __tablename__ = "approval_requests"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    publish_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("publish_jobs.id", ondelete="CASCADE"), index=True
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default=ApprovalStatus.PENDING)
    request_note: Mapped[str] = mapped_column(Text, default="")
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsSnapshot(UUIDPk, Timestamps, Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (Index("ix_analytics_job_captured", "publish_job_id", "captured_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    publish_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("publish_jobs.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(120))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    watch_time_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
