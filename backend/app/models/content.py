"""Channels, projects, assets and API configuration (LLM provider credentials + model routes)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import ProjectStatus, VideoFormat


class Channel(UUIDPk, Timestamps, Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_channel_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    niche: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    tone: Mapped[str] = mapped_column(String(200), default="informative, engaging")
    target_audience: Mapped[str] = mapped_column(String(300), default="")
    default_format: Mapped[str] = mapped_column(String(20), default=VideoFormat.VERTICAL)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Brand kit: colors, subtitle style, intro/outro, watermark, etc.
    branding: Mapped[dict[str, Any]] = mapped_column(default=dict)

    projects: Mapped[list[Project]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class Project(UUIDPk, Timestamps, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_project_org_status", "organization_id", "status"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    topic: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default=ProjectStatus.DRAFT)
    format: Mapped[str] = mapped_column(String(20), default=VideoFormat.VERTICAL)
    target_duration_sec: Mapped[int] = mapped_column(Integer, default=60)
    brief: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Outputs of the agent pipeline (latest accepted versions)
    research: Mapped[dict[str, Any]] = mapped_column(default=dict)
    strategy: Mapped[dict[str, Any]] = mapped_column(default=dict)
    script: Mapped[dict[str, Any]] = mapped_column(default=dict)
    fact_check: Mapped[dict[str, Any]] = mapped_column(default=dict)
    storyboard: Mapped[dict[str, Any]] = mapped_column(default=dict)
    optimization: Mapped[dict[str, Any]] = mapped_column(default=dict)

    channel: Mapped[Channel] = relationship(back_populates="projects")


class Asset(UUIDPk, Timestamps, Base):
    __tablename__ = "assets"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(300))
    storage_path: Mapped[str] = mapped_column(String(600))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ProviderCredential(UUIDPk, Timestamps, Base):
    """Encrypted API keys for LLM (and other) providers, scoped to an organization."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("organization_id", "provider", "label", name="uq_cred_org_provider_label"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80), default="default")
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(20), default="")
    base_url: Mapped[str | None] = mapped_column(String(400))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ModelRoute(UUIDPk, Timestamps, Base):
    """Which provider/model each agent uses. agent_name='*' is the organization default."""

    __tablename__ = "model_routes"
    __table_args__ = (UniqueConstraint("organization_id", "agent_name", name="uq_route_org_agent"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    # [{"provider": "...", "model": "..."}] tried in order when the primary fails
    fallbacks: Mapped[list[Any]] = mapped_column(default=list)
