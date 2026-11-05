"""Analytics collection from platform APIs and performance reporting."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.integrations.base import PlatformError
from app.models import AnalyticsSnapshot, Channel, Project, PublishJob, SocialAccount
from app.models.enums import Platform, PublishStatus
from app.schemas.social import PerformanceReport, PerformanceRow
from app.services.social import get_access_token, get_client

log = get_logger(__name__)


async def collect_for_job(db: AsyncSession, job: PublishJob) -> AnalyticsSnapshot | None:
    account = await db.get(SocialAccount, job.social_account_id)
    if account is None or not job.external_id:
        return None
    token = await get_access_token(db, account)
    client = get_client(job.platform)
    if job.platform == Platform.YOUTUBE:
        m = await client.fetch_metrics(token, job.external_id, job.published_at)
    else:
        m = await client.fetch_metrics(token, job.external_id)
    snap = AnalyticsSnapshot(
        organization_id=job.organization_id,
        publish_job_id=job.id,
        platform=job.platform,
        external_id=job.external_id,
        captured_at=datetime.now(UTC),
        views=m.views,
        likes=m.likes,
        comments=m.comments,
        shares=m.shares,
        saves=m.saves,
        impressions=m.impressions,
        reach=m.reach,
        watch_time_minutes=m.watch_time_minutes,
        avg_view_duration_sec=m.avg_view_duration_sec,
        raw=m.raw,
    )
    db.add(snap)
    await db.commit()
    return snap


async def collect_all(
    session_factory: async_sessionmaker[AsyncSession], org_id: uuid.UUID | None = None, max_age_days: int = 90
) -> int:
    count = 0
    async with session_factory() as db:
        stmt = select(PublishJob.id).where(
            PublishJob.status == PublishStatus.PUBLISHED,
            PublishJob.published_at >= datetime.now(UTC) - timedelta(days=max_age_days),
        )
        if org_id:
            stmt = stmt.where(PublishJob.organization_id == org_id)
        ids = list((await db.scalars(stmt)).all())
    for job_id in ids:
        async with session_factory() as db:
            job = await db.get(PublishJob, job_id)
            if job is None:
                continue
            try:
                if await collect_for_job(db, job):
                    count += 1
            except PlatformError as exc:
                log.warning("analytics_collect_failed", extra={"job_id": str(job_id), "error": str(exc)[:300]})
    log.info("analytics_collected", extra={"snapshots": count})
    return count


def _engagement(views: int, likes: int, comments: int, shares: int) -> float:
    return round((likes + comments + shares) / views * 100, 2) if views else 0.0


async def performance_report(
    db: AsyncSession, org_id: uuid.UUID, start: datetime, end: datetime, channel_id: uuid.UUID | None = None
) -> PerformanceReport:
    jobs_stmt = (
        select(PublishJob, Project)
        .join(Project, Project.id == PublishJob.project_id)
        .where(PublishJob.organization_id == org_id, PublishJob.status == PublishStatus.PUBLISHED)
    )
    if channel_id:
        jobs_stmt = jobs_stmt.where(Project.channel_id == channel_id)
    rows = (await db.execute(jobs_stmt)).all()
    job_ids = [j.id for j, _ in rows]

    latest: dict[uuid.UUID, AnalyticsSnapshot] = {}
    daily: dict[str, dict[uuid.UUID, int]] = defaultdict(dict)
    if job_ids:
        snaps = (
            await db.scalars(
                select(AnalyticsSnapshot)
                .where(
                    AnalyticsSnapshot.publish_job_id.in_(job_ids),
                    AnalyticsSnapshot.captured_at >= start,
                    AnalyticsSnapshot.captured_at <= end,
                )
                .order_by(AnalyticsSnapshot.captured_at)
            )
        ).all()
        for s in snaps:
            latest[s.publish_job_id] = s
            day = s.captured_at.date().isoformat()
            daily[day][s.publish_job_id] = max(daily[day].get(s.publish_job_id, 0), s.views)

    channel_names = {
        c.id: c.name for c in (await db.scalars(select(Channel).where(Channel.organization_id == org_id))).all()
    }
    totals: dict[str, float] = defaultdict(float)
    by_platform: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_channel: dict[uuid.UUID, dict[str, Any]] = {}
    perf: list[PerformanceRow] = []
    for job, project in rows:
        s = latest.get(job.id)
        views, likes, comments, shares = (s.views, s.likes, s.comments, s.shares) if s else (0, 0, 0, 0)
        watch = s.watch_time_minutes if s else 0.0
        for k, v in (
            ("views", views),
            ("likes", likes),
            ("comments", comments),
            ("shares", shares),
            ("watch_time_minutes", watch),
        ):
            totals[k] += v
            by_platform[job.platform][k] += v
        totals["posts"] += 1
        by_platform[job.platform]["posts"] += 1
        ch = by_channel.setdefault(
            project.channel_id,
            {
                "channel_id": str(project.channel_id),
                "name": channel_names.get(project.channel_id, "?"),
                "posts": 0,
                "views": 0,
                "likes": 0,
            },
        )
        ch["posts"] += 1
        ch["views"] += views
        ch["likes"] += likes
        perf.append(
            PerformanceRow(
                publish_job_id=job.id,
                project_id=project.id,
                title=job.title,
                platform=job.platform,
                external_url=job.external_url,
                published_at=job.published_at,
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=_engagement(views, likes, comments, shares),
                watch_time_minutes=watch,
            )
        )
    totals["engagement_rate"] = _engagement(
        int(totals["views"]), int(totals["likes"]), int(totals["comments"]), int(totals["shares"])
    )
    for p in by_platform.values():
        p["engagement_rate"] = _engagement(int(p["views"]), int(p["likes"]), int(p["comments"]), int(p["shares"]))
    perf.sort(key=lambda r: r.views, reverse=True)
    return PerformanceReport(
        period_start=start,
        period_end=end,
        totals=dict(totals),
        by_platform={k: dict(v) for k, v in by_platform.items()},
        by_channel=sorted(by_channel.values(), key=lambda c: c["views"], reverse=True),
        top_posts=perf[:10],
        daily=[{"date": d, "cumulative_views": sum(v.values())} for d, v in sorted(daily.items())],
    )


async def snapshot_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return await db.scalar(select(func.count()).where(AnalyticsSnapshot.organization_id == org_id)) or 0
