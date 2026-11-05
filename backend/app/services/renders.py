"""Render job orchestration: builds a resolved RenderSpec and executes it with progress + resume."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.errors import ValidationFailedError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models import Asset, Channel, Project, RenderJob
from app.models.enums import AssetKind, ProjectStatus, RunStatus
from app.schemas.runs import RenderCreate
from app.services import storage
from app.services.scoping import get_scoped
from app.video.pipeline import RenderCancelledError, RenderPipeline
from app.video.spec import RenderSpec, SceneSpec

log = get_logger(__name__)


async def _asset_path(
    db: AsyncSession, org_id: uuid.UUID, asset_id: uuid.UUID | None, kinds: set[str]
) -> tuple[str | None, str | None]:
    if asset_id is None:
        return None, None
    asset = await get_scoped(db, Asset, asset_id, org_id, label="Asset")
    if asset.kind not in kinds:
        raise ValidationFailedError(f"Asset {asset_id} has kind '{asset.kind}', expected one of {sorted(kinds)}")
    return str(storage.resolve(asset.storage_path)), asset.kind


async def build_render_spec(db: AsyncSession, org_id: uuid.UUID, project: Project, req: RenderCreate) -> RenderSpec:
    channel = await db.get(Channel, project.channel_id)
    branding = (channel.branding if channel else {}) or {}
    scenes: list[SceneSpec] = []
    if req.scenes:
        for sc in req.scenes:
            path, kind = await _asset_path(db, org_id, sc.asset_id, {AssetKind.IMAGE, AssetKind.VIDEO})
            scenes.append(
                SceneSpec(
                    source_path=path,
                    source_kind=kind or "color",  # type: ignore[arg-type]
                    duration=sc.duration,
                    text=sc.text,
                    overlay_text=sc.overlay_text,
                    transition=sc.transition,
                    transition_duration=sc.transition_duration,
                    motion=sc.motion,
                    background_color=sc.background_color,
                )
            )
    else:
        board = (project.storyboard or {}).get("scenes") or []
        if not board:
            raise ValidationFailedError("Project has no storyboard; run the storyboard agent or pass scenes explicitly")
        visuals = (
            await db.scalars(
                select(Asset)
                .where(
                    Asset.organization_id == org_id,
                    Asset.project_id == project.id,
                    Asset.kind.in_([AssetKind.IMAGE, AssetKind.VIDEO]),
                )
                .order_by(Asset.created_at)
            )
        ).all()
        palette = branding.get("scene_colors") or ["#14213D", "#1B263B", "#2B2D42", "#3D405B"]
        for i, sc in enumerate(board):
            visual = visuals[i % len(visuals)] if visuals else None
            scenes.append(
                SceneSpec(
                    source_path=str(storage.resolve(visual.storage_path)) if visual else None,
                    source_kind=visual.kind if visual else "color",  # type: ignore[arg-type]
                    duration=float(sc.get("duration_sec", 4)),
                    text=sc.get("narration", ""),
                    # Text-only cards show the narration as a headline unless captions already carry it.
                    overlay_text=sc.get("overlay_text", "")
                    or ("" if visual or req.burn_subtitles else sc.get("narration", "")[:90]),
                    transition=sc.get("transition", "fade"),
                    motion=sc.get("motion", "zoom_in"),
                    background_color=palette[i % len(palette)],
                )
            )

    narration, _ = await _asset_path(db, org_id, req.narration_asset_id, {AssetKind.NARRATION})
    music, _ = await _asset_path(db, org_id, req.music_asset_id, {AssetKind.MUSIC})
    subs, _ = await _asset_path(db, org_id, req.subtitle_asset_id, {AssetKind.SUBTITLE})
    style = {**(branding.get("subtitle_style") or {}), **req.subtitle_style.model_dump(exclude_none=True)}
    thumb_text = (
        req.thumbnail_text
        if req.thumbnail_text is not None
        else (project.optimization or {}).get("thumbnail_text") or project.title[:40]
    )
    return RenderSpec(
        format=req.format or project.format,  # type: ignore[arg-type]
        fps=settings.render_fps,
        title=(project.script or {}).get("title") or project.title,
        scenes=scenes,
        narration_path=narration,
        music_path=music,
        subtitle_path=subs,
        burn_subtitles=req.burn_subtitles,
        subtitle_style=style,
        music_volume=req.music_volume,
        duck_music=req.duck_music,
        target_lufs=req.target_lufs,
        thumbnail_text=thumb_text,
        preset=settings.render_preset,
        crf=settings.render_crf,
        font_file=settings.render_font_file if Path(settings.render_font_file).exists() else "",
        font_name=settings.render_font_name,
    )


def render_workdir(job: RenderJob) -> Path:
    return storage.org_dir(job.organization_id, "projects", str(job.project_id), "renders", str(job.id))


async def execute_render_job(session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> RunStatus:
    async with session_factory() as db:
        job = await db.get(RenderJob, job_id)
        if job is None:
            return RunStatus.FAILED
        if job.status in (RunStatus.SUCCEEDED, RunStatus.CANCELLED):
            return RunStatus(job.status)
        project = await db.get(Project, job.project_id)
        assert project is not None
        job.status = RunStatus.RUNNING
        job.attempts += 1
        job.error = None
        job.started_at = job.started_at or datetime.now(UTC)
        project.status = ProjectStatus.RENDERING
        await db.commit()

        spec = RenderSpec.model_validate(job.spec)
        workdir = render_workdir(job)
        state = {"last_write": 0.0, "stage": None, "last_cancel_check": 0.0}
        channel = f"render:{job.id}"

        async def on_progress(stage: str, pct: float, info: dict) -> None:
            now = time.monotonic()
            try:
                await get_redis().publish(channel, json.dumps({"stage": stage, "progress": pct, **info}))
            except Exception:  # noqa: BLE001 - progress fan-out is best effort
                pass
            if stage != state["stage"] or now - state["last_write"] >= 1.5 or pct >= 100:
                state.update(last_write=now, stage=stage)
                job.stage, job.progress = stage, pct
                await db.commit()

        async def should_cancel() -> bool:
            now = time.monotonic()
            if now - state["last_cancel_check"] < 2:
                return False
            state["last_cancel_check"] = now
            async with session_factory() as check:
                current = await check.scalar(select(RenderJob.status).where(RenderJob.id == job.id))
            return current == RunStatus.CANCELLED

        pipeline = RenderPipeline(spec, workdir, on_progress=on_progress, should_cancel=should_cancel)
        try:
            result = await pipeline.run()
        except RenderCancelledError:
            job.status, job.stage = RunStatus.CANCELLED, "cancelled"
            job.manifest = pipeline.manifest
            project.status = ProjectStatus.SCRIPTED if project.script else ProjectStatus.DRAFT
            job.finished_at = datetime.now(UTC)
            await db.commit()
            return RunStatus.CANCELLED
        except Exception as exc:  # noqa: BLE001
            log.exception("render_failed", extra={"job_id": str(job_id)})
            job.status, job.error = RunStatus.FAILED, f"{type(exc).__name__}: {exc}"[:4000]
            job.manifest = pipeline.manifest
            job.qc_report = pipeline.manifest.get("qc", {})
            project.status = ProjectStatus.FAILED
            job.finished_at = datetime.now(UTC)
            await db.commit()
            return RunStatus.FAILED

        w, h = spec.size
        video = Asset(
            organization_id=job.organization_id,
            project_id=job.project_id,
            kind=AssetKind.RENDER,
            filename=f"{storage.safe_filename(project.title)[:60]}_{spec.format}.mp4",
            storage_path=storage.relative(result.video_path),
            mime_type="video/mp4",
            size_bytes=result.video_path.stat().st_size,
            checksum_sha256=storage.file_sha256(result.video_path),
            duration_sec=result.duration,
            width=w,
            height=h,
            meta={"render_job_id": str(job.id)},
        )
        thumb = Asset(
            organization_id=job.organization_id,
            project_id=job.project_id,
            kind=AssetKind.THUMBNAIL,
            filename=f"{storage.safe_filename(project.title)[:60]}_thumbnail.jpg",
            storage_path=storage.relative(result.thumbnail_path),
            mime_type="image/jpeg",
            size_bytes=result.thumbnail_path.stat().st_size,
            meta={"render_job_id": str(job.id)},
        )
        db.add_all([video, thumb])
        await db.flush()
        job.output_asset_id, job.thumbnail_asset_id = video.id, thumb.id
        job.status, job.stage, job.progress = RunStatus.SUCCEEDED, "completed", 100.0
        job.qc_report, job.manifest = result.qc_report, result.manifest
        job.finished_at = datetime.now(UTC)
        project.status = ProjectStatus.RENDERED
        await db.commit()
        log.info("render_succeeded", extra={"job_id": str(job_id), "duration": result.duration})
        return RunStatus.SUCCEEDED
