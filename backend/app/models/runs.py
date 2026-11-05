"""Agent runs/steps (execution logs + token tracking) and render jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import RunStatus


class AgentRun(UUIDPk, Timestamps, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_run_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    triggered_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED)
    agents: Mapped[list[Any]] = mapped_column(default=list)  # requested subset; empty = full pipeline
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.created_at"
    )


class AgentStep(UUIDPk, Timestamps, Base):
    """One LLM call attempt by one agent. This is the agent execution log."""

    __tablename__ = "agent_steps"

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class RenderJob(UUIDPk, Timestamps, Base):
    __tablename__ = "render_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED)
    format: Mapped[str] = mapped_column(String(20))
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    spec: Mapped[dict[str, Any]] = mapped_column(default=dict)
    manifest: Mapped[dict[str, Any]] = mapped_column(default=dict)  # resumable checkpoints
    qc_report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assets.id", ondelete="SET NULL"))
    thumbnail_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assets.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
