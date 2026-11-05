from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.definitions import AGENT_ORDER
from app.agents.graph import missing_prerequisites
from app.agents.runner import project_state
from app.api.deps import Editor, OrgContext, Viewer
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db.session import get_db
from app.models import AgentRun, Channel, Project
from app.models.enums import RunStatus
from app.schemas.common import Page
from app.schemas.runs import AgentRunCreate, AgentRunDetail, AgentRunOut
from app.services.audit import record_audit
from app.services.queue import get_queue
from app.services.scoping import get_scoped

router = APIRouter(tags=["agents"])


@router.post("/projects/{project_id}/agent-runs", response_model=AgentRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    project_id: uuid.UUID, data: AgentRunCreate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> AgentRun:
    project = await get_scoped(db, Project, project_id, ctx.org_id)
    active = await db.scalar(
        select(AgentRun.id).where(
            AgentRun.project_id == project.id, AgentRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING])
        )
    )
    if active:
        raise ConflictError("An agent run is already in progress for this project", details={"run_id": str(active)})
    channel = await db.get(Channel, project.channel_id)
    assert channel is not None
    missing = missing_prerequisites(project_state(project, channel), list(data.agents))
    if missing:
        raise ValidationFailedError("Missing prerequisite agent outputs", details={"missing": missing})
    run = AgentRun(
        organization_id=ctx.org_id,
        project_id=project.id,
        triggered_by_id=ctx.user.id,
        agents=[a for a in AGENT_ORDER if a in data.agents],
        input={"instructions": data.instructions},
    )
    db.add(run)
    await db.flush()
    record_audit(
        db,
        action="agent_run.started",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="agent_run",
        entity_id=run.id,
        data={"agents": run.agents},
    )
    await db.commit()
    await db.refresh(run)
    await get_queue().enqueue("run_agents", str(run.id), job_id=f"agents:{run.id}")
    return run


@router.get("/agent-runs", response_model=Page[AgentRunOut])
async def list_runs(
    project_id: uuid.UUID | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Viewer,
    db: AsyncSession = Depends(get_db),
) -> Page[AgentRunOut]:
    stmt = select(AgentRun).where(AgentRun.organization_id == ctx.org_id)
    if project_id:
        stmt = stmt.where(AgentRun.project_id == project_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(AgentRun.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[AgentRunOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail)
async def get_run(run_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> AgentRun:
    run = await db.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.organization_id == ctx.org_id)
        .options(selectinload(AgentRun.steps))
    )
    if run is None:
        raise NotFoundError("Agent run not found")
    return run


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRunOut)
async def cancel_run(run_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> AgentRun:
    run = await get_scoped(db, AgentRun, run_id, ctx.org_id, label="Agent run")
    if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise ConflictError(f"Run is already {run.status}")
    run.status = RunStatus.CANCELLED
    await db.commit()
    await db.refresh(run)
    return run
