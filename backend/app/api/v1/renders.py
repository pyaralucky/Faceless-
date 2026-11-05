from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Editor, OrgContext, Viewer
from app.core.errors import ConflictError
from app.db.session import SessionLocal, get_db
from app.models import Project, RenderJob
from app.models.enums import RunStatus
from app.schemas.common import Page
from app.schemas.runs import RenderCreate, RenderJobOut
from app.services.audit import record_audit
from app.services.queue import get_queue
from app.services.renders import build_render_spec
from app.services.scoping import get_scoped

router = APIRouter(tags=["rendering"])


@router.post("/projects/{project_id}/renders", response_model=RenderJobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_render(
    project_id: uuid.UUID, data: RenderCreate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> RenderJob:
    project = await get_scoped(db, Project, project_id, ctx.org_id)
    spec = await build_render_spec(db, ctx.org_id, project, data)
    job = RenderJob(
        organization_id=ctx.org_id,
        project_id=project.id,
        requested_by_id=ctx.user.id,
        format=spec.format,
        spec=spec.model_dump(mode="json"),
    )
    db.add(job)
    await db.flush()
    record_audit(
        db,
        action="render.requested",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="render_job",
        entity_id=job.id,
        data={"format": spec.format, "scenes": len(spec.scenes)},
    )
    await db.commit()
    await db.refresh(job)
    await get_queue().enqueue("render_video", str(job.id), job_id=f"render:{job.id}:{job.attempts}")
    return job


@router.get("/renders", response_model=Page[RenderJobOut])
async def list_renders(
    project_id: uuid.UUID | None = None,
    status_: RunStatus | None = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Viewer,
    db: AsyncSession = Depends(get_db),
) -> Page[RenderJobOut]:
    stmt = select(RenderJob).where(RenderJob.organization_id == ctx.org_id)
    if project_id:
        stmt = stmt.where(RenderJob.project_id == project_id)
    if status_:
        stmt = stmt.where(RenderJob.status == status_)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(RenderJob.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[RenderJobOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/renders/{job_id}", response_model=RenderJobOut)
async def get_render(job_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> RenderJob:
    return await get_scoped(db, RenderJob, job_id, ctx.org_id, label="Render job")


@router.post("/renders/{job_id}/resume", response_model=RenderJobOut, status_code=status.HTTP_202_ACCEPTED)
async def resume_render(job_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> RenderJob:
    """Re-queue a failed/cancelled render. Completed stages are reused from the checkpoint manifest."""
    job = await get_scoped(db, RenderJob, job_id, ctx.org_id, label="Render job")
    if job.status not in (RunStatus.FAILED, RunStatus.CANCELLED):
        raise ConflictError(f"Only failed or cancelled renders can be resumed (status: {job.status})")
    job.status, job.stage, job.error = RunStatus.QUEUED, "queued", None
    await db.commit()
    await db.refresh(job)
    await get_queue().enqueue("render_video", str(job.id), job_id=f"render:{job.id}:{job.attempts}")
    return job


@router.post("/renders/{job_id}/cancel", response_model=RenderJobOut)
async def cancel_render(job_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> RenderJob:
    job = await get_scoped(db, RenderJob, job_id, ctx.org_id, label="Render job")
    if job.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise ConflictError(f"Render is already {job.status}")
    job.status = RunStatus.CANCELLED
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/renders/{job_id}/events")
async def render_events(
    job_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    """Server-Sent Events stream of render progress (polls the DB; works behind any proxy)."""
    import asyncio

    await get_scoped(db, RenderJob, job_id, ctx.org_id, label="Render job")

    async def stream() -> AsyncIterator[str]:
        last = None
        for _ in range(3600):
            async with SessionLocal() as s:
                job = await s.get(RenderJob, job_id)
            if job is None:
                break
            payload = {"status": job.status, "stage": job.stage, "progress": job.progress, "error": job.error}
            if payload != last:
                yield f"data: {json.dumps(payload)}\n\n"
                last = payload
            if job.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
