import json
import uuid
from pathlib import Path

import pytest

from app.video.pipeline import RenderCancelledError, RenderPipeline, fit_text
from app.video.probe import probe_media
from app.video.spec import RenderSpec, SceneSpec
from app.video.subtitles import build_ass, cues_from_scenes, parse_srt
from tests.conftest import make_channel, make_png, make_project, make_wav, requires_ffmpeg

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def test_srt_parsing_and_ass():
    srt = "1\n00:00:00,000 --> 00:00:01,500\nHello <b>world</b>\n\n2\n00:00:01.500 --> 00:00:03,000\nSecond line\ncontinues\n"
    cues = parse_srt(srt)
    assert [(c.start, c.end, c.text) for c in cues] == [(0.0, 1.5, "Hello world"), (1.5, 3.0, "Second line continues")]
    ass = build_ass(cues, 1080, 1920, {"primary_color": "#FF0000", "position": "top", "uppercase": True}, "DejaVu Sans")
    assert "PlayResY: 1920" in ass and "&H000000FF" in ass and "HELLO WORLD" in ass
    assert ",8," in ass.split("Style: Default")[1].split("\n")[0]  # top alignment


def test_cues_from_scenes_timing():
    cues = cues_from_scenes([(0.0, 4.0, "one two three four five six seven eight")], max_words=4)
    assert len(cues) == 2 and cues[0].end == pytest.approx(2.0) and cues[1].end == pytest.approx(4.0)


def test_fit_text_wraps_and_shrinks():
    text, size = fit_text("A very long overlay headline that certainly will not fit on one line", 90, 900)
    assert "\n" in text and size <= 90
    assert all(len(line) * size * 0.62 <= 900 for line in text.split("\n"))


def _spec(media: Path, fmt: str = "vertical", **kw) -> RenderSpec:
    img = make_png(media / "a.png", "1200x900")
    return RenderSpec(
        format=fmt,
        preset="ultrafast",
        crf=32,
        font_file=FONT if Path(FONT).exists() else "",
        scenes=[
            SceneSpec(
                source_path=str(img),
                source_kind="image",
                duration=1.6,
                text="First scene words here",
                overlay_text="Hook: 100% real",
                motion="zoom_in",
            ),
            SceneSpec(duration=1.4, text="Second card", transition="wipeleft", transition_duration=0.4),
        ],
        thumbnail_text="Big Reveal",
        **kw,
    )


@requires_ffmpeg
@pytest.mark.parametrize("fmt,size", [("vertical", (1080, 1920)), ("horizontal", (1920, 1080))])
async def test_render_formats_and_qc(tmp_media, fmt, size):
    narration = make_wav(tmp_media / "n.wav", 2.4)
    events = []

    async def prog(stage, pct, info):
        events.append((stage, pct))

    spec = _spec(tmp_media, fmt, narration_path=str(narration))
    result = await RenderPipeline(spec, tmp_media / "work", on_progress=prog).run()
    info = await probe_media(result.video_path)
    assert (info.width, info.height) == size
    assert info.video_codec == "h264" and info.audio_codec == "aac"
    assert result.duration == pytest.approx(2.4 + 0.6, abs=0.05)  # fitted to narration
    assert result.qc_report["passed"]
    assert result.thumbnail_path.exists() and result.subtitles_path.exists()
    pcts = [p for _, p in events]
    assert pcts == sorted(pcts) and pcts[-1] == 100
    thumb = await probe_media(result.thumbnail_path)
    assert (thumb.width, thumb.height) == ((1280, 720) if fmt == "horizontal" else (1080, 1920))


@requires_ffmpeg
async def test_render_resumes_from_checkpoints(tmp_media):
    spec = _spec(tmp_media)
    work = tmp_media / "work"
    await RenderPipeline(spec, work).run()
    seg = work / "segments" / "seg_0000.mp4"
    mtime = seg.stat().st_mtime_ns
    final_mtime = (work / "final.mp4").stat().st_mtime_ns
    resumed = []

    async def prog(stage, pct, info):
        if info.get("resumed"):
            resumed.append(stage)

    await RenderPipeline(spec, work, on_progress=prog).run()
    assert seg.stat().st_mtime_ns == mtime and (work / "final.mp4").stat().st_mtime_ns == final_mtime
    assert {"scenes", "assemble", "audio", "compose"} <= set(resumed)

    # simulate crash after scenes: delete later outputs -> only those are rebuilt
    (work / "final.mp4").unlink()
    manifest = json.loads((work / "manifest.json").read_text())
    assert "compose" in manifest["stages"]
    await RenderPipeline(spec, work).run()
    assert seg.stat().st_mtime_ns == mtime and (work / "final.mp4").exists()

    # changing a scene re-renders only that segment
    spec2 = spec.model_copy(deep=True)
    spec2.scenes[1].text = "Changed narration"
    spec2.scenes[1].background_color = "#AA0000"
    await RenderPipeline(spec2, work).run()
    assert seg.stat().st_mtime_ns == mtime


@requires_ffmpeg
async def test_render_cancellation(tmp_media):
    async def cancel():
        return True

    with pytest.raises(RenderCancelledError):
        await RenderPipeline(_spec(tmp_media), tmp_media / "w", should_cancel=cancel).run()


@requires_ffmpeg
async def test_render_via_api_and_worker(owner, queue, session_factory, tmp_media):
    from app.services.renders import execute_render_job

    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"], target_duration_sec=10)
    # no storyboard yet -> validation error
    assert (await owner.post(f"/projects/{p['id']}/renders", json={})).status_code == 422
    await owner.patch(
        f"/projects/{p['id']}",
        json={
            "storyboard": {
                "scenes": [
                    {
                        "index": 0,
                        "duration_sec": 1.5,
                        "narration": "Atlantis was first described by Plato.",
                        "visual_prompt": "x",
                        "transition": "fade",
                    },
                    {
                        "index": 1,
                        "duration_sec": 1.5,
                        "narration": "Nobody has ever found it.",
                        "visual_prompt": "y",
                        "transition": "dissolve",
                    },
                ]
            }
        },
    )
    img = make_png(tmp_media / "bg.png")
    with img.open("rb") as fh:
        asset = (
            await owner.post(
                f"/projects/{p['id']}/assets", data={"kind": "image"}, files={"file": ("bg.png", fh, "image/png")}
            )
        ).json()
    wav = make_wav(tmp_media / "voice.wav", 2.0)
    with wav.open("rb") as fh:
        narr = (
            await owner.post(
                f"/projects/{p['id']}/assets",
                data={"kind": "narration"},
                files={"file": ("voice.wav", fh, "audio/wav")},
            )
        ).json()
    # wrong asset kind is rejected
    r = await owner.post(f"/projects/{p['id']}/renders", json={"narration_asset_id": asset["id"]})
    assert r.status_code == 422
    r = await owner.post(
        f"/projects/{p['id']}/renders",
        json={"format": "vertical", "narration_asset_id": narr["id"], "subtitle_style": {"position": "center"}},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert queue.jobs[-1][0] == "render_video"
    assert await execute_render_job(session_factory, uuid.UUID(job["id"])) == "succeeded"
    done = (await owner.get(f"/renders/{job['id']}")).json()
    assert done["status"] == "succeeded" and done["progress"] == 100 and done["qc_report"]["passed"]
    assets = (await owner.get(f"/projects/{p['id']}/assets?kind=render")).json()
    assert assets[0]["width"] == 1080 and assets[0]["height"] == 1920
    proj = (await owner.get(f"/projects/{p['id']}")).json()
    assert proj["status"] == "rendered"
    assert (await owner.post(f"/renders/{job['id']}/resume")).status_code == 409


@requires_ffmpeg
async def test_failed_render_can_resume(owner, session_factory, tmp_media, db):
    from app.models import RenderJob
    from app.services.renders import execute_render_job

    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"])
    r = await owner.post(f"/projects/{p['id']}/renders", json={"scenes": [{"duration": 1.2, "text": "hi"}]})
    job_id = uuid.UUID(r.json()["id"])
    # corrupt the spec so the run fails, then fix it and resume
    job = await db.get(RenderJob, job_id)
    good = dict(job.spec)
    job.spec = {**good, "narration_path": str(tmp_media / "missing.wav")}
    await db.commit()
    assert await execute_render_job(session_factory, job_id) == "failed"
    failed = (await owner.get(f"/renders/{job_id}")).json()
    assert failed["status"] == "failed" and "Narration" in failed["error"]
    await db.refresh(job)
    job.spec = good
    await db.commit()
    assert (await owner.post(f"/renders/{job_id}/resume")).status_code == 202
    assert await execute_render_job(session_factory, job_id) == "succeeded"
    assert (await owner.get(f"/renders/{job_id}")).json()["attempts"] == 2
