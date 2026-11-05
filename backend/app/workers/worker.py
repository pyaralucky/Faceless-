"""arq worker: agent runs, renders, publishing and periodic scheduling/analytics jobs.

Run with:  arq app.workers.worker.WorkerSettings
"""

from __future__ import annotations

import uuid
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select, update

from app.agents.runner import execute_agent_run
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models import AgentRun, PublishJob, RenderJob
from app.models.enums import PublishStatus, RunStatus
from app.services.analytics import collect_all
from app.services.publishing import claim_due_jobs, execute_publish
from app.services.renders import execute_render_job

log = get_logger("app.worker")


async def run_agents(ctx: dict[str, Any], run_id: str) -> str:
    return await execute_agent_run(SessionLocal, uuid.UUID(run_id))


async def render_video(ctx: dict[str, Any], job_id: str) -> str:
    return await execute_render_job(SessionLocal, uuid.UUID(job_id))


async def publish_video(ctx: dict[str, Any], job_id: str) -> str:
    return await execute_publish(SessionLocal, uuid.UUID(job_id))


async def collect_analytics(ctx: dict[str, Any], org_id: str | None = None) -> int:
    return await collect_all(SessionLocal, uuid.UUID(org_id) if org_id else None)


async def dispatch_due_publications(ctx: dict[str, Any]) -> int:
    """Cron: move due scheduled posts into the upload queue."""
    async with SessionLocal() as db:
        ids = await claim_due_jobs(db)
    for job_id in ids:
        await ctx["redis"].enqueue_job("publish_video", str(job_id), _job_id=f"publish:{job_id}:{uuid.uuid4().hex[:6]}")
    if ids:
        log.info("publications_dispatched", extra={"count": len(ids)})
    return len(ids)


async def periodic_analytics(ctx: dict[str, Any]) -> int:
    return await collect_all(SessionLocal)


async def startup(ctx: dict[str, Any]) -> None:
    """Recover work interrupted by a crash/redeploy. Renders resume from their checkpoints."""
    configure_logging(settings.log_level, settings.log_json)
    async with SessionLocal() as db:
        stuck_renders = list(
            (await db.scalars(select(RenderJob.id).where(RenderJob.status == RunStatus.RUNNING))).all()
        )
        if stuck_renders:
            await db.execute(
                update(RenderJob)
                .where(RenderJob.id.in_(stuck_renders))
                .values(status=RunStatus.QUEUED, stage="requeued")
            )
        stuck_runs = list((await db.scalars(select(AgentRun.id).where(AgentRun.status == RunStatus.RUNNING))).all())
        if stuck_runs:
            await db.execute(update(AgentRun).where(AgentRun.id.in_(stuck_runs)).values(status=RunStatus.QUEUED))
        # Uploads interrupted mid-flight go back to the schedule; resumable state lives on the job.
        await db.execute(
            update(PublishJob)
            .where(PublishJob.status.in_([PublishStatus.UPLOADING, PublishStatus.PROCESSING]))
            .values(status=PublishStatus.SCHEDULED)
        )
        await db.commit()
    for rid in stuck_renders:
        await ctx["redis"].enqueue_job("render_video", str(rid), _job_id=f"render:{rid}:recover:{uuid.uuid4().hex[:6]}")
    for rid in stuck_runs:
        await ctx["redis"].enqueue_job("run_agents", str(rid), _job_id=f"agents:{rid}:recover:{uuid.uuid4().hex[:6]}")
    log.info("worker_started", extra={"recovered_renders": len(stuck_renders), "recovered_runs": len(stuck_runs)})


class WorkerSettings:
    functions = [run_agents, render_video, publish_video, collect_analytics]
    cron_jobs = [
        cron(dispatch_due_publications, second={0, 30}, run_at_startup=True, unique=True),
        cron(periodic_analytics, minute={7}, unique=True),  # hourly
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 4 * 3600
    keep_result = 3600
    max_tries = 3
    health_check_interval = 30
