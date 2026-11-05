"""Publishing queue: approval gating, scheduling, upload execution and retries with backoff."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.errors import ConflictError, ValidationFailedError
from app.core.logging import get_logger
from app.core.security import create_signed_token
from app.integrations.base import PlatformError, PublishRequest
from app.models import ApprovalRequest, Asset, Channel, Project, PublishJob, RenderJob, SocialAccount
from app.models.enums import ApprovalStatus, Platform, ProjectStatus, PublishStatus, RunStatus, SocialAccountStatus
from app.schemas.social import PublishJobCreate
from app.services import storage
from app.services.scoping import get_scoped
from app.services.social import get_access_token, get_client

log = get_logger(__name__)

ACTIVE_STATES = {PublishStatus.SCHEDULED, PublishStatus.UPLOADING, PublishStatus.PROCESSING}


def now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


def add_history(job: PublishJob, event: str, **data: Any) -> None:
    job.history = [*(job.history or []), {"at": now().isoformat(), "event": event, **data}][-50:]


async def create_publish_job(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: PublishJobCreate
) -> PublishJob:
    project = await get_scoped(db, Project, data.project_id, org_id)
    account = await get_scoped(db, SocialAccount, data.social_account_id, org_id, label="Social account")
    if account.status != SocialAccountStatus.ACTIVE:
        raise ValidationFailedError(f"Social account is {account.status}; reconnect it first")
    if data.render_job_id:
        render = await get_scoped(db, RenderJob, data.render_job_id, org_id, label="Render job")
        if render.project_id != project.id:
            raise ValidationFailedError("Render job belongs to another project")
    else:
        render = await db.scalar(
            select(RenderJob)
            .where(RenderJob.project_id == project.id, RenderJob.status == RunStatus.SUCCEEDED)
            .order_by(RenderJob.finished_at.desc())
        )
    if render is None or render.status != RunStatus.SUCCEEDED:
        raise ValidationFailedError("A successful render is required before publishing")
    if not (render.qc_report or {}).get("passed"):
        raise ValidationFailedError("Render did not pass quality checks")
    if account.platform == Platform.INSTAGRAM and render.format != "vertical":
        raise ValidationFailedError("Instagram Reels require a vertical (1080x1920) render")
    if data.scheduled_at and _aware(data.scheduled_at) < now() - timedelta(minutes=1):
        raise ValidationFailedError("scheduled_at must be in the future")

    channel = await db.get(Channel, project.channel_id)
    opt = project.optimization or {}
    job = PublishJob(
        organization_id=org_id,
        project_id=project.id,
        social_account_id=account.id,
        render_job_id=render.id,
        created_by_id=user_id,
        platform=account.platform,
        title=data.title or (opt.get("titles") or [project.title])[0],
        description=data.description if data.description is not None else opt.get("description", ""),
        tags=data.tags
        if data.tags is not None
        else (opt.get("tags") if account.platform == Platform.YOUTUBE else opt.get("hashtags")) or [],
        privacy=data.privacy,
        scheduled_at=data.scheduled_at,
        max_attempts=settings.publish_max_attempts,
    )
    db.add(job)
    await db.flush()
    if channel and channel.require_approval:
        job.status = PublishStatus.PENDING_APPROVAL
        db.add(
            ApprovalRequest(
                organization_id=org_id, project_id=project.id, publish_job_id=job.id, requested_by_id=user_id
            )
        )
        project.status = ProjectStatus.PENDING_APPROVAL
        add_history(job, "approval_requested")
    else:
        schedule(job)
        project.status = ProjectStatus.SCHEDULED
    await db.commit()
    await db.refresh(job)
    return job


def schedule(job: PublishJob) -> None:
    job.status = PublishStatus.SCHEDULED
    job.next_attempt_at = max(_aware(job.scheduled_at) or now(), now())
    add_history(job, "scheduled", at_time=job.next_attempt_at.isoformat())


async def decide_approval(
    db: AsyncSession, approval: ApprovalRequest, reviewer_id: uuid.UUID, approve: bool, note: str
) -> ApprovalRequest:
    if approval.status != ApprovalStatus.PENDING:
        raise ConflictError(f"Approval already {approval.status}")
    if approval.requested_by_id == reviewer_id and not settings.allow_self_approval:
        # four-eyes principle: reviewers must differ from requesters unless explicitly allowed
        raise ValidationFailedError("Requesters cannot approve their own content")
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.reviewer_id = reviewer_id
    approval.decision_note = note
    approval.decided_at = now()
    project = await db.get(Project, approval.project_id)
    job = await db.get(PublishJob, approval.publish_job_id) if approval.publish_job_id else None
    if approve:
        if job and job.status == PublishStatus.PENDING_APPROVAL:
            add_history(job, "approved", by=str(reviewer_id))
            schedule(job)
            if project:
                project.status = ProjectStatus.SCHEDULED
        elif project:
            project.status = ProjectStatus.APPROVED
    else:
        if job and job.status == PublishStatus.PENDING_APPROVAL:
            job.status = PublishStatus.REJECTED
            add_history(job, "rejected", by=str(reviewer_id), note=note)
        if project:
            project.status = ProjectStatus.RENDERED
    await db.commit()
    await db.refresh(approval)
    return approval


async def claim_due_jobs(db: AsyncSession, limit: int = 20) -> list[uuid.UUID]:
    """Atomically move due jobs to UPLOADING. Uses SKIP LOCKED on PostgreSQL so multiple schedulers are safe."""
    stmt = (
        select(PublishJob)
        .where(PublishJob.status == PublishStatus.SCHEDULED, PublishJob.next_attempt_at <= now())
        .order_by(PublishJob.next_attempt_at)
        .limit(limit)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    jobs = list((await db.scalars(stmt)).all())
    for job in jobs:
        job.status = PublishStatus.UPLOADING
        add_history(job, "claimed", attempt=job.attempts + 1)
    await db.commit()
    return [j.id for j in jobs]


def public_media_url(asset_id: uuid.UUID, ttl_hours: int = 6) -> str | None:
    base = settings.media_public_base_url or settings.public_api_url
    if not base:
        return None
    token = create_signed_token("media", {"asset": str(asset_id)}, timedelta(hours=ttl_hours))
    return f"{base.rstrip('/')}{settings.api_prefix}/media/{token}"


def retry_delay(attempt: int) -> timedelta:
    base = settings.publish_retry_base_seconds * (2 ** max(0, attempt - 1))
    return timedelta(seconds=min(base, 6 * 3600) * (0.8 + random.random() * 0.4))


async def execute_publish(session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> str:
    async with session_factory() as db:
        job = await db.get(PublishJob, job_id)
        if job is None or job.status not in (PublishStatus.UPLOADING, PublishStatus.SCHEDULED):
            return job.status if job else "missing"
        account = await db.get(SocialAccount, job.social_account_id)
        render = await db.get(RenderJob, job.render_job_id)
        project = await db.get(Project, job.project_id)
        assert account and render and project
        video = await db.get(Asset, render.output_asset_id) if render.output_asset_id else None
        thumb = await db.get(Asset, render.thumbnail_asset_id) if render.thumbnail_asset_id else None
        job.status = PublishStatus.UPLOADING
        job.attempts += 1
        await db.commit()

        async def progress(frac: float) -> None:
            job.upload_progress = round(frac * 100, 1)
            job.status = PublishStatus.UPLOADING if frac < 1 else PublishStatus.PROCESSING
            await db.commit()

        try:
            if video is None:
                raise PlatformError("Rendered video asset missing", retryable=False)
            token = await get_access_token(db, account)
            req = PublishRequest(
                video_path=str(storage.resolve(video.storage_path)),
                thumbnail_path=str(storage.resolve(thumb.storage_path)) if thumb else None,
                title=job.title,
                description=job.description,
                tags=list(job.tags or []),
                privacy=job.privacy,
                public_video_url=public_media_url(video.id),
                public_thumbnail_url=public_media_url(thumb.id) if thumb else None,
                state=dict(job.state or {}),
            )
            client = get_client(account.platform)
            try:
                if account.platform == Platform.YOUTUBE:
                    result = await client.publish(token, req, progress)
                else:
                    result = await client.publish(token, account.external_id, req, progress)
            finally:
                job.state = dict(req.state)  # persist resumable state (upload session / container id)
            job.status = PublishStatus.PUBLISHED
            job.external_id, job.external_url = result.external_id, result.url
            job.published_at = now()
            job.upload_progress = 100.0
            job.last_error = None
            job.next_attempt_at = None
            add_history(job, "published", external_id=result.external_id)
            project.status = ProjectStatus.PUBLISHED
            await db.commit()
            log.info(
                "publish_succeeded",
                extra={"job_id": str(job.id), "platform": job.platform, "external_id": result.external_id},
            )
            return PublishStatus.PUBLISHED
        except PlatformError as exc:
            return await _handle_failure(db, job, account, str(exc), exc.retryable, exc.auth_error)
        except Exception as exc:  # noqa: BLE001
            log.exception("publish_crashed", extra={"job_id": str(job_id)})
            return await _handle_failure(db, job, account, f"{type(exc).__name__}: {exc}", True, False)


async def _handle_failure(
    db: AsyncSession, job: PublishJob, account: SocialAccount, error: str, retryable: bool, auth_error: bool
) -> str:
    job.last_error = error[:4000]
    if auth_error:
        account.status = SocialAccountStatus.EXPIRED
    if retryable and job.attempts < job.max_attempts:
        job.status = PublishStatus.SCHEDULED
        job.next_attempt_at = now() + retry_delay(job.attempts)
        add_history(
            job,
            "retry_scheduled",
            attempt=job.attempts,
            error=error[:300],
            next_attempt_at=job.next_attempt_at.isoformat(),
        )
        log.warning("publish_retry", extra={"job_id": str(job.id), "attempt": job.attempts, "error": error[:300]})
    else:
        job.status = PublishStatus.FAILED
        job.next_attempt_at = None
        add_history(job, "failed", attempt=job.attempts, error=error[:300])
        log.error("publish_failed", extra={"job_id": str(job.id), "error": error[:300]})
    await db.commit()
    return job.status
