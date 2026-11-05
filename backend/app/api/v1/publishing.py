from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Editor, OrgContext, Viewer
from app.core.errors import ConflictError
from app.db.session import get_db
from app.models import ApprovalRequest, PublishJob
from app.models.enums import ApprovalStatus, PublishStatus
from app.schemas.common import Page
from app.schemas.social import PublishJobCreate, PublishJobOut, PublishJobUpdate
from app.services import publishing as svc
from app.services.audit import record_audit
from app.services.queue import get_queue
from app.services.scoping import get_scoped

router = APIRouter(prefix="/publishing", tags=["publishing"])

EDITABLE = {PublishStatus.DRAFT, PublishStatus.PENDING_APPROVAL, PublishStatus.SCHEDULED, PublishStatus.FAILED}


@router.post("/jobs", response_model=PublishJobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: PublishJobCreate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> PublishJob:
    job = await svc.create_publish_job(db, ctx.org_id, ctx.user.id, data)
    record_audit(
        db,
        action="publish.created",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="publish_job",
        entity_id=job.id,
        data={"platform": job.platform, "status": job.status},
    )
    await db.commit()
    return job


@router.get("/jobs", response_model=Page[PublishJobOut])
async def list_jobs(
    project_id: uuid.UUID | None = None,
    status_: PublishStatus | None = Query(None, alias="status"),
    platform: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Viewer,
    db: AsyncSession = Depends(get_db),
) -> Page[PublishJobOut]:
    stmt = select(PublishJob).where(PublishJob.organization_id == ctx.org_id)
    if project_id:
        stmt = stmt.where(PublishJob.project_id == project_id)
    if status_:
        stmt = stmt.where(PublishJob.status == status_)
    if platform:
        stmt = stmt.where(PublishJob.platform == platform)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(
            stmt.order_by(func.coalesce(PublishJob.scheduled_at, PublishJob.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page(items=[PublishJobOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/jobs/{job_id}", response_model=PublishJobOut)
async def get_job(job_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> PublishJob:
    return await get_scoped(db, PublishJob, job_id, ctx.org_id, label="Publish job")


@router.patch("/jobs/{job_id}", response_model=PublishJobOut)
async def update_job(
    job_id: uuid.UUID, data: PublishJobUpdate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> PublishJob:
    job = await get_scoped(db, PublishJob, job_id, ctx.org_id, label="Publish job")
    if job.status not in EDITABLE:
        raise ConflictError(f"Cannot edit a job in status '{job.status}'")
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(job, k, v)
    if job.status == PublishStatus.SCHEDULED and "scheduled_at" in changes:
        svc.schedule(job)
    svc.add_history(job, "edited", fields=list(changes))
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=PublishJobOut)
async def cancel_job(job_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> PublishJob:
    job = await get_scoped(db, PublishJob, job_id, ctx.org_id, label="Publish job")
    if job.status in (
        PublishStatus.PUBLISHED,
        PublishStatus.UPLOADING,
        PublishStatus.PROCESSING,
        PublishStatus.CANCELLED,
    ):
        raise ConflictError(f"Cannot cancel a job in status '{job.status}'")
    job.status = PublishStatus.CANCELLED
    job.next_attempt_at = None
    svc.add_history(job, "cancelled", by=str(ctx.user.id))
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.publish_job_id == job.id, ApprovalRequest.status == ApprovalStatus.PENDING)
        .values(status=ApprovalStatus.CANCELLED)
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/retry", response_model=PublishJobOut)
async def retry_job(job_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> PublishJob:
    job = await get_scoped(db, PublishJob, job_id, ctx.org_id, label="Publish job")
    if job.status != PublishStatus.FAILED:
        raise ConflictError("Only failed jobs can be retried")
    job.attempts = 0
    job.last_error = None
    svc.schedule(job)
    svc.add_history(job, "manual_retry", by=str(ctx.user.id))
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/publish-now", response_model=PublishJobOut, status_code=status.HTTP_202_ACCEPTED)
async def publish_now(job_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> PublishJob:
    job = await get_scoped(db, PublishJob, job_id, ctx.org_id, label="Publish job")
    if job.status != PublishStatus.SCHEDULED:
        raise ConflictError("Only scheduled (approved) jobs can be published immediately")
    job.status = PublishStatus.UPLOADING
    svc.add_history(job, "publish_now", by=str(ctx.user.id))
    await db.commit()
    await db.refresh(job)
    await get_queue().enqueue("publish_video", str(job.id), job_id=f"publish:{job.id}:{job.attempts}")
    return job
