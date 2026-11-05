from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Editor, OrgContext, Reviewer, Viewer
from app.core.errors import ConflictError
from app.db.session import get_db
from app.models import ApprovalRequest, Project, PublishJob
from app.models.enums import ApprovalStatus, ProjectStatus
from app.schemas.common import Page
from app.schemas.social import ApprovalCreate, ApprovalDecision, ApprovalOut
from app.services import publishing as svc
from app.services.audit import record_audit
from app.services.scoping import get_scoped

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=Page[ApprovalOut])
async def list_approvals(
    status_: ApprovalStatus | None = Query(None, alias="status"),
    decided: bool | None = Query(None, description="true = approved/rejected/cancelled only; false = pending only"),
    project_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Viewer,
    db: AsyncSession = Depends(get_db),
) -> Page[ApprovalOut]:
    stmt = select(ApprovalRequest).where(ApprovalRequest.organization_id == ctx.org_id)
    if status_:
        stmt = stmt.where(ApprovalRequest.status == status_)
    if decided is not None:
        stmt = stmt.where(
            ApprovalRequest.status != ApprovalStatus.PENDING
            if decided
            else ApprovalRequest.status == ApprovalStatus.PENDING
        )
    if project_id:
        stmt = stmt.where(ApprovalRequest.project_id == project_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = ApprovalRequest.decided_at.desc() if decided else ApprovalRequest.created_at.desc()
    rows = (
        await db.execute(
            stmt.add_columns(Project.title)
            .join(Project, Project.id == ApprovalRequest.project_id)
            .order_by(order, ApprovalRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [ApprovalOut.model_validate(a).model_copy(update={"project_title": title}) for a, title in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED)
async def request_approval(
    data: ApprovalCreate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> ApprovalRequest:
    project = await get_scoped(db, Project, data.project_id, ctx.org_id)
    if data.publish_job_id:
        await get_scoped(db, PublishJob, data.publish_job_id, ctx.org_id, label="Publish job")
    pending = await db.scalar(
        select(ApprovalRequest.id).where(
            ApprovalRequest.project_id == project.id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
            ApprovalRequest.publish_job_id == data.publish_job_id,
        )
    )
    if pending:
        raise ConflictError("A pending approval already exists")
    ar = ApprovalRequest(
        organization_id=ctx.org_id,
        project_id=project.id,
        publish_job_id=data.publish_job_id,
        requested_by_id=ctx.user.id,
        request_note=data.note,
    )
    db.add(ar)
    project.status = ProjectStatus.PENDING_APPROVAL
    await db.commit()
    await db.refresh(ar)
    return ar


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
async def decide(
    approval_id: uuid.UUID, data: ApprovalDecision, ctx: OrgContext = Reviewer, db: AsyncSession = Depends(get_db)
) -> ApprovalRequest:
    ar = await get_scoped(db, ApprovalRequest, approval_id, ctx.org_id, label="Approval")
    result = await svc.decide_approval(db, ar, ctx.user.id, data.decision == "approve", data.note)
    record_audit(
        db,
        action=f"approval.{data.decision}",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="approval",
        entity_id=ar.id,
        data={"note": data.note},
    )
    await db.commit()
    return result
