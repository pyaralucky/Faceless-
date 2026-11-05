from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Editor, OrgContext, Viewer
from app.db.session import get_db
from app.models import AnalyticsSnapshot, PublishJob
from app.schemas.common import Message
from app.schemas.social import AnalyticsSnapshotOut, PerformanceReport
from app.services.analytics import performance_report
from app.services.queue import get_queue
from app.services.scoping import get_scoped

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/report", response_model=PerformanceReport)
async def report(
    days: int = Query(30, ge=1, le=365),
    channel_id: uuid.UUID | None = None,
    ctx: OrgContext = Viewer,
    db: AsyncSession = Depends(get_db),
) -> PerformanceReport:
    end = datetime.now(UTC)
    return await performance_report(db, ctx.org_id, end - timedelta(days=days), end, channel_id)


@router.get("/jobs/{job_id}/snapshots", response_model=list[AnalyticsSnapshotOut])
async def job_snapshots(
    job_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)
) -> list[AnalyticsSnapshot]:
    await get_scoped(db, PublishJob, job_id, ctx.org_id, label="Publish job")
    return list(
        (
            await db.scalars(
                select(AnalyticsSnapshot)
                .where(AnalyticsSnapshot.publish_job_id == job_id)
                .order_by(AnalyticsSnapshot.captured_at)
            )
        ).all()
    )


@router.post("/collect", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
async def collect_now(ctx: OrgContext = Editor) -> Message:
    await get_queue().enqueue(
        "collect_analytics", str(ctx.org_id), job_id=f"analytics:{ctx.org_id}:{datetime.now(UTC):%Y%m%d%H%M}"
    )
    return Message(message="Analytics collection queued")
