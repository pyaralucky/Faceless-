from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Editor, OrgContext, Viewer
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import Asset, Channel, Project
from app.models.enums import AssetKind, ProjectStatus
from app.schemas.common import Message, Page
from app.schemas.content import AssetOut, ProjectCreate, ProjectOut, ProjectSummary, ProjectUpdate
from app.services import storage
from app.services.audit import record_audit
from app.services.media import probe_media
from app.services.scoping import get_scoped

router = APIRouter(prefix="/projects", tags=["projects"])

UPLOADABLE = {AssetKind.IMAGE, AssetKind.VIDEO, AssetKind.NARRATION, AssetKind.MUSIC, AssetKind.SUBTITLE}


@router.get("", response_model=Page[ProjectSummary])
async def list_projects(
    channel_id: uuid.UUID | None = None,
    status_: ProjectStatus | None = Query(None, alias="status"),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: OrgContext = Viewer,
    db: AsyncSession = Depends(get_db),
) -> Page[ProjectSummary]:
    stmt = select(Project).where(Project.organization_id == ctx.org_id)
    if channel_id:
        stmt = stmt.where(Project.channel_id == channel_id)
    if status_:
        stmt = stmt.where(Project.status == status_)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Project.title).like(like), func.lower(Project.topic).like(like)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(Project.updated_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[ProjectSummary.model_validate(p) for p in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)) -> Project:
    channel = await get_scoped(db, Channel, data.channel_id, ctx.org_id)
    p = Project(
        organization_id=ctx.org_id,
        channel_id=channel.id,
        created_by_id=ctx.user.id,
        title=data.title,
        topic=data.topic or data.title,
        format=data.format or channel.default_format,
        target_duration_sec=data.target_duration_sec,
        brief=data.brief,
    )
    db.add(p)
    await db.flush()
    record_audit(
        db, action="project.created", org_id=ctx.org_id, actor_id=ctx.user.id, entity_type="project", entity_id=p.id
    )
    await db.commit()
    await db.refresh(p)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> Project:
    return await get_scoped(db, Project, project_id, ctx.org_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> Project:
    p = await get_scoped(db, Project, project_id, ctx.org_id)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    record_audit(
        db,
        action="project.updated",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="project",
        entity_id=p.id,
        data={"fields": list(changes)},
    )
    await db.commit()
    await db.refresh(p)
    return p


@router.delete("/{project_id}", response_model=Message)
async def delete_project(
    project_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> Message:
    p = await get_scoped(db, Project, project_id, ctx.org_id)
    await db.delete(p)
    record_audit(
        db,
        action="project.deleted",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="project",
        entity_id=project_id,
        data={"title": p.title},
    )
    await db.commit()
    storage.delete_path(storage.relative(storage.org_dir(ctx.org_id, "projects", str(project_id))))
    return Message(message="Project deleted")


# ------------------------------------------------------------------ assets


@router.get("/{project_id}/assets", response_model=list[AssetOut])
async def list_assets(
    project_id: uuid.UUID, kind: AssetKind | None = None, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)
) -> list[Asset]:
    await get_scoped(db, Project, project_id, ctx.org_id)
    stmt = select(Asset).where(Asset.organization_id == ctx.org_id, Asset.project_id == project_id)
    if kind:
        stmt = stmt.where(Asset.kind == kind)
    return list((await db.scalars(stmt.order_by(Asset.created_at))).all())


@router.post("/{project_id}/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    project_id: uuid.UUID,
    kind: AssetKind = Form(...),
    file: UploadFile = File(...),
    ctx: OrgContext = Editor,
    db: AsyncSession = Depends(get_db),
) -> Asset:
    await get_scoped(db, Project, project_id, ctx.org_id)
    if kind not in UPLOADABLE:
        raise NotFoundError("Unsupported asset kind for upload", code="invalid_kind")
    path, size, sha, mime = await storage.save_upload(file, ctx.org_id, project_id, kind)
    info = await probe_media(storage.resolve(path)) if kind != AssetKind.SUBTITLE else None
    asset = Asset(
        organization_id=ctx.org_id,
        project_id=project_id,
        kind=kind,
        filename=storage.safe_filename(file.filename or "upload"),
        storage_path=path,
        mime_type=mime,
        size_bytes=size,
        checksum_sha256=sha,
        duration_sec=info.duration if info else None,
        width=info.width if info else None,
        height=info.height if info else None,
        meta={"has_audio": info.has_audio} if info else {},
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


@router.get("/{project_id}/assets/{asset_id}/file")
async def download_asset(
    project_id: uuid.UUID, asset_id: uuid.UUID, ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    asset = await get_scoped(db, Asset, asset_id, ctx.org_id, label="Asset")
    if asset.project_id != project_id:
        raise NotFoundError("Asset not found")
    path = storage.resolve(asset.storage_path)
    if not path.exists():
        raise NotFoundError("Asset file missing from storage")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.filename)


@router.delete("/{project_id}/assets/{asset_id}", response_model=Message)
async def delete_asset(
    project_id: uuid.UUID, asset_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> Message:
    asset = await get_scoped(db, Asset, asset_id, ctx.org_id, label="Asset")
    if asset.project_id != project_id:
        raise NotFoundError("Asset not found")
    storage.delete_path(asset.storage_path)
    await db.delete(asset)
    await db.commit()
    return Message(message="Asset deleted")
