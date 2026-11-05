from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import tokens_used_this_month
from app.api.deps import OrgContext, Viewer
from app.db.session import get_db
from app.models import (
    AgentRun,
    AnalyticsSnapshot,
    ApprovalRequest,
    Channel,
    Project,
    PublishJob,
    RenderJob,
    SocialAccount,
)
from app.models.enums import ApprovalStatus, PublishStatus, RunStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> dict:
    org = ctx.org_id

    async def count(model, *where) -> int:  # noqa: ANN001
        return await db.scalar(select(func.count()).select_from(model).where(model.organization_id == org, *where)) or 0

    project_status = dict(
        (
            await db.execute(
                select(Project.status, func.count()).where(Project.organization_id == org).group_by(Project.status)
            )
        ).all()
    )
    since = datetime.now(UTC) - timedelta(days=30)
    upcoming = (
        await db.scalars(
            select(PublishJob)
            .where(
                PublishJob.organization_id == org,
                PublishJob.status.in_([PublishStatus.SCHEDULED, PublishStatus.PENDING_APPROVAL]),
            )
            .order_by(PublishJob.next_attempt_at.asc().nulls_last())
            .limit(5)
        )
    ).all()
    recent_runs = (
        await db.scalars(
            select(AgentRun).where(AgentRun.organization_id == org).order_by(AgentRun.created_at.desc()).limit(5)
        )
    ).all()
    active_renders = (
        await db.scalars(
            select(RenderJob)
            .where(RenderJob.organization_id == org, RenderJob.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]))
            .limit(10)
        )
    ).all()

    # views: latest snapshot per publish job
    latest = (
        select(AnalyticsSnapshot.publish_job_id, func.max(AnalyticsSnapshot.captured_at).label("ts"))
        .where(AnalyticsSnapshot.organization_id == org)
        .group_by(AnalyticsSnapshot.publish_job_id)
        .subquery()
    )
    views = await db.scalar(
        select(func.coalesce(func.sum(AnalyticsSnapshot.views), 0)).join(
            latest,
            (latest.c.publish_job_id == AnalyticsSnapshot.publish_job_id)
            & (latest.c.ts == AnalyticsSnapshot.captured_at),
        )
    )
    usage = await db.execute(
        select(
            func.coalesce(func.sum(AgentRun.prompt_tokens + AgentRun.completion_tokens), 0),
            func.coalesce(func.sum(AgentRun.cost_usd), 0.0),
        ).where(AgentRun.organization_id == org, AgentRun.created_at >= since)
    )
    tokens_30d, cost_30d = usage.one()
    return {
        "counts": {
            "channels": await count(Channel, Channel.is_active.is_(True)),
            "projects": await count(Project),
            "social_accounts": await count(SocialAccount),
            "pending_approvals": await count(ApprovalRequest, ApprovalRequest.status == ApprovalStatus.PENDING),
            "scheduled_posts": await count(PublishJob, PublishJob.status == PublishStatus.SCHEDULED),
            "published_posts": await count(PublishJob, PublishJob.status == PublishStatus.PUBLISHED),
            "failed_posts": await count(PublishJob, PublishJob.status == PublishStatus.FAILED),
            "renders_30d": await count(RenderJob, RenderJob.created_at >= since),
        },
        "project_status": project_status,
        "total_views": int(views or 0),
        "usage": {
            "tokens_30d": int(tokens_30d),
            "cost_usd_30d": round(float(cost_30d), 4),
            "tokens_this_month": await tokens_used_this_month(db, org),
            "monthly_token_budget": ctx.organization.monthly_token_budget,
        },
        "upcoming_posts": [
            {
                "id": str(j.id),
                "title": j.title,
                "platform": j.platform,
                "status": j.status,
                "scheduled_at": (j.next_attempt_at or j.scheduled_at),
            }
            for j in upcoming
        ],
        "recent_agent_runs": [
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "status": r.status,
                "tokens": r.prompt_tokens + r.completion_tokens,
                "created_at": r.created_at,
            }
            for r in recent_runs
        ],
        "active_renders": [
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "progress": r.progress,
                "stage": r.stage,
                "status": r.status,
            }
            for r in active_renders
        ],
    }
