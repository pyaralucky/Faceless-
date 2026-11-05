"""Asynchronous, resumable FFmpeg rendering pipeline.

Stages (each checkpointed in ``manifest.json`` inside the job work directory):

    plan -> scenes (one segment per scene) -> assemble (xfade transitions) -> audio (mix/duck/loudnorm)
         -> subtitles (styled ASS) -> compose (burn subs + mux, faststart) -> thumbnail -> qc

A stage is skipped on resume when its fingerprint (hash of its inputs) matches and its output still
exists, so a crashed or cancelled render continues where it stopped instead of starting over.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import textwrap
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.video.ffmpeg import FFmpegError, run_ffmpeg
from app.video.probe import probe_media
from app.video.spec import RenderSpec, SceneSpec
from app.video.subtitles import Cue, build_ass, cues_from_scenes, parse_srt, write_srt

log = get_logger(__name__)

# stage -> share of overall progress
STAGE_WEIGHTS = {
    "plan": 1,
    "scenes": 45,
    "assemble": 15,
    "audio": 12,
    "subtitles": 2,
    "compose": 20,
    "thumbnail": 2,
    "qc": 3,
}
STAGES = list(STAGE_WEIGHTS)

ProgressCallback = Callable[[str, float, dict[str, Any]], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]


class RenderCancelledError(Exception):
    pass


class RenderFailedError(Exception):
    pass


@dataclass(slots=True)
class RenderResult:
    video_path: Path
    thumbnail_path: Path
    subtitles_path: Path | None
    duration: float
    qc_report: dict[str, Any]
    manifest: dict[str, Any]


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _file_sig(path: str | None) -> Any:
    if not path:
        return None
    try:
        st = os.stat(path)
        return [path, st.st_size, int(st.st_mtime)]
    except FileNotFoundError:
        return [path, None]


def _escape_filter_path(path: Path | str) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def fit_text(text: str, base_size: int, max_width: int, max_lines: int = 3) -> tuple[str, int]:
    """Word-wrap text to the frame width, shrinking the font when it still doesn't fit."""
    text = re.sub(r"\s+", " ", text).strip()
    size = base_size
    while size > 12:
        chars = max(4, int(max_width / (size * 0.62)))
        lines = textwrap.wrap(text, width=chars) or [""]
        if len(lines) <= max_lines and max(len(x) for x in lines) <= chars:
            return "\n".join(lines), size
        size = int(size * 0.9)
    return "\n".join(textwrap.wrap(text, width=max(4, int(max_width / (size * 0.62))))[:max_lines]), size


def _hex_to_ff(color: str) -> str:
    return "0x" + color.lstrip("#")


class RenderPipeline:
    def __init__(
        self,
        spec: RenderSpec,
        workdir: Path,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ):
        self.spec = spec
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.on_progress = on_progress
        self.should_cancel = should_cancel
        self.manifest_path = workdir / "manifest.json"
        self.manifest: dict[str, Any] = self._load_manifest()
        self.width, self.height = spec.size

    # ------------------------------------------------------------------ manifest / checkpoints

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            try:
                return json.loads(self.manifest_path.read_text())
            except json.JSONDecodeError:
                log.warning("render_manifest_corrupt", extra={"path": str(self.manifest_path)})
        return {"version": 1, "stages": {}, "segments": {}}

    def _save_manifest(self) -> None:
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.manifest, indent=1))
        tmp.replace(self.manifest_path)

    def _stage_done(self, stage: str, fingerprint: str, output: Path | None) -> bool:
        entry = self.manifest["stages"].get(stage)
        return bool(entry and entry.get("fingerprint") == fingerprint and (output is None or output.exists()))

    def _mark(self, stage: str, fingerprint: str, **data: Any) -> None:
        self.manifest["stages"][stage] = {"fingerprint": fingerprint, **data}
        self._save_manifest()

    async def _progress(self, stage: str, fraction: float, **info: Any) -> None:
        done = sum(STAGE_WEIGHTS[s] for s in STAGES[: STAGES.index(stage)])
        overall = (done + STAGE_WEIGHTS[stage] * max(0.0, min(1.0, fraction))) / sum(STAGE_WEIGHTS.values()) * 100
        if self.on_progress:
            await self.on_progress(stage, round(overall, 2), info)

    async def _check_cancel(self) -> None:
        if self.should_cancel and await self.should_cancel():
            raise RenderCancelledError("Render cancelled")

    def _encode_args(self) -> list[str]:
        return [
            "-c:v",
            "libx264",
            "-preset",
            self.spec.preset,
            "-crf",
            str(self.spec.crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.spec.fps),
        ]

    # ------------------------------------------------------------------ public entry point

    async def run(self) -> RenderResult:
        await self._plan()
        segments = await self._render_scenes()
        video_only = await self._assemble(segments)
        audio = await self._audio()
        subs = await self._subtitles()
        final = await self._compose(video_only, audio, subs)
        thumb = await self._thumbnail(video_only)
        qc = await self._qc(final)
        return RenderResult(final, thumb, subs, self.manifest["plan"]["total_duration"], qc, self.manifest)

    # ------------------------------------------------------------------ plan

    async def _plan(self) -> None:
        await self._progress("plan", 0)
        spec = self.spec
        scenes = [s.model_copy() for s in spec.scenes]
        narration_duration = None
        if spec.narration_path:
            info = await probe_media(Path(spec.narration_path))
            if info is None or not info.has_audio:
                raise RenderFailedError("Narration file is not a readable audio file")
            narration_duration = info.duration
        for s in scenes:
            if s.source_path and not Path(s.source_path).exists():
                raise RenderFailedError(f"Scene source missing: {s.source_path}")
            # A transition can't be longer than half of either adjacent clip.
            s.transition_duration = 0.0 if s.transition == "none" else min(s.transition_duration, s.duration / 2.5)
        scenes[0].transition_duration = 0.0  # first scene has no incoming transition

        if narration_duration and spec.fit_to_narration:
            overlap = sum(s.transition_duration for s in scenes)
            visual = sum(s.duration for s in scenes) - overlap
            target = narration_duration + 0.6
            if visual > 0 and abs(visual - target) > 0.05:
                factor = (target + overlap) / (visual + overlap)
                for s in scenes:
                    s.duration = round(s.duration * factor, 3)

        starts, t = [], 0.0
        for i, s in enumerate(scenes):
            if i > 0:
                t -= s.transition_duration
            starts.append(round(t, 3))
            t += s.duration
        plan = {
            "scenes": [s.model_dump() for s in scenes],
            "starts": starts,
            "total_duration": round(t, 3),
            "narration_duration": narration_duration,
        }
        self.manifest["plan"] = plan
        self._mark("plan", _hash(plan))
        await self._progress("plan", 1)

    @property
    def _scenes(self) -> list[SceneSpec]:
        return [SceneSpec(**s) for s in self.manifest["plan"]["scenes"]]

    # ------------------------------------------------------------------ scenes

    def _motion_filter(self, scene: SceneSpec, frames: int) -> str:
        w, h = self.width, self.height
        # Upscale before zoompan to reduce sub-pixel jitter.
        sw, sh = int(w * 1.5) // 2 * 2, int(h * 1.5) // 2 * 2
        cover = f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh}"
        n = max(frames - 1, 1)
        zoom = {
            "zoom_in": f"z='1+0.15*on/{n}'",
            "zoom_out": f"z='1.15-0.15*on/{n}'",
            "pan_left": "z='1.15'",
            "pan_right": "z='1.15'",
            "none": "z='1'",
        }[scene.motion]
        x = {
            "pan_left": f"x='(iw-iw/zoom)*(1-on/{n})'",
            "pan_right": f"x='(iw-iw/zoom)*on/{n}'",
        }.get(scene.motion, "x='iw/2-(iw/zoom/2)'")
        y = "y='ih/2-(ih/zoom/2)'"
        return f"{cover},zoompan={zoom}:{x}:{y}:d={frames}:s={w}x{h}:fps={self.spec.fps}"

    def _text_file(self, name: str, text: str) -> str:
        """drawtext reads text from a file with expansion disabled: no escaping pitfalls with : ' % , etc."""
        path = self.workdir / "text" / f"{name}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return f"textfile='{_escape_filter_path(path)}':expansion=none:text_align=C"

    def _overlay_filter(self, scene: SceneSpec, index: int) -> str:
        if not scene.overlay_text or not self.spec.font_file:
            return ""
        base = int(self.height * (0.045 if self.height > self.width else 0.065))
        wrapped, size = fit_text(scene.overlay_text, base, int(self.width * 0.86))
        return (
            f",drawtext=fontfile='{_escape_filter_path(self.spec.font_file)}':{self._text_file(f'overlay_{index}', wrapped)}:line_spacing={size // 5}"
            f":fontsize={size}:fontcolor=white:borderw={max(2, size // 12)}:bordercolor=black@0.85"
            f":box=1:boxcolor=black@0.35:boxborderw={size // 3}:x=(w-text_w)/2:y=h*0.12"
            f":alpha='if(lt(t,0.3),t/0.3,1)'"
        )

    def _scene_args(self, scene: SceneSpec, out: Path, index: int = 0) -> list[str]:
        w, h, fps = self.width, self.height, self.spec.fps
        frames = max(1, round(scene.duration * fps))
        norm = f"fps={fps},format=yuv420p,setsar=1,settb=AVTB"
        overlay = self._overlay_filter(scene, index)
        if scene.source_kind == "image" and scene.source_path:
            inputs = ["-i", scene.source_path]
            vf = f"{self._motion_filter(scene, frames)},{norm}{overlay}"
        elif scene.source_kind == "video" and scene.source_path:
            inputs = ["-stream_loop", "-1", "-i", scene.source_path]
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},{norm}{overlay}"
        else:
            inputs = ["-f", "lavfi", "-i", f"color=c={_hex_to_ff(scene.background_color)}:s={w}x{h}:r={fps}"]
            vf = f"{norm}{overlay}"
        return [
            *inputs,
            "-vf",
            vf,
            "-frames:v",
            str(frames),
            "-an",
            *self._encode_args(),
            "-video_track_timescale",
            "90000",
            str(out),
        ]

    async def _render_scenes(self) -> list[Path]:
        scenes = self._scenes
        enc = {
            "w": self.width,
            "h": self.height,
            "fps": self.spec.fps,
            "preset": self.spec.preset,
            "crf": self.spec.crf,
            "font": self.spec.font_file,
        }
        seg_dir = self.workdir / "segments"
        seg_dir.mkdir(exist_ok=True)
        outputs: list[Path] = []
        for i, scene in enumerate(scenes):
            await self._check_cancel()
            out = seg_dir / f"seg_{i:04d}.mp4"
            fp = scene.fingerprint({**enc, "src": _file_sig(scene.source_path)})
            entry = self.manifest["segments"].get(str(i))
            if entry and entry.get("fingerprint") == fp and out.exists() and out.stat().st_size > 0:
                outputs.append(out)
                await self._progress("scenes", (i + 1) / len(scenes), scene=i, resumed=True)
                continue
            tmp = out.with_name(out.stem + ".part.mp4")

            async def prog(frac: float, _i: int = i) -> None:
                await self._progress("scenes", (_i + frac) / len(scenes), scene=_i)

            try:
                await run_ffmpeg(self._scene_args(scene, tmp, i), expected_duration=scene.duration, on_progress=prog)
            except FFmpegError as exc:
                raise RenderFailedError(f"Scene {i} failed: {exc}") from exc
            tmp.replace(out)
            self.manifest["segments"][str(i)] = {"fingerprint": fp, "path": out.name}
            self._save_manifest()
            outputs.append(out)
        self._mark("scenes", _hash([self.manifest["segments"][str(i)]["fingerprint"] for i in range(len(scenes))]))
        return outputs

    # ------------------------------------------------------------------ assemble

    async def _assemble(self, segments: list[Path]) -> Path:
        out = self.workdir / "video_only.mp4"
        fp = _hash([self.manifest["stages"]["scenes"]["fingerprint"], self.manifest["plan"]["starts"]])
        if self._stage_done("assemble", fp, out):
            await self._progress("assemble", 1, resumed=True)
            return out
        await self._check_cancel()
        scenes = self._scenes
        if len(segments) == 1:
            args = ["-i", str(segments[0]), "-c", "copy", str(out.with_suffix(".part.mp4"))]
        else:
            inputs: list[str] = []
            for seg in segments:
                inputs += ["-i", str(seg)]
            # Normalise timebase/fps of every input so xfade and concat can be chained freely.
            filters = [
                f"[{i}:v]fps={self.spec.fps},format=yuv420p,setsar=1,settb=AVTB[s{i}]" for i in range(len(segments))
            ]
            prev, cum = "[s0]", scenes[0].duration
            for i in range(1, len(segments)):
                s = scenes[i]
                label = f"[v{i}]"
                if s.transition == "none" or s.transition_duration <= 0:
                    filters.append(f"{prev}[s{i}]concat=n=2:v=1:a=0,settb=AVTB{label}")
                    cum += s.duration
                else:
                    offset = cum - s.transition_duration
                    filters.append(
                        f"{prev}[s{i}]xfade=transition={s.transition}:duration={s.transition_duration:.3f}:offset={offset:.3f}{label}"
                    )
                    cum = offset + s.duration
                prev = label
            args = [
                *inputs,
                "-filter_complex",
                ";".join(filters),
                "-map",
                prev,
                "-an",
                *self._encode_args(),
                str(out.with_suffix(".part.mp4")),
            ]

        async def prog(frac: float) -> None:
            await self._progress("assemble", frac)

        try:
            await run_ffmpeg(args, expected_duration=self.manifest["plan"]["total_duration"], on_progress=prog)
        except FFmpegError as exc:
            raise RenderFailedError(f"Assembly failed: {exc}") from exc
        out.with_suffix(".part.mp4").replace(out)
        self._mark("assemble", fp)
        return out

    # ------------------------------------------------------------------ audio

    async def _audio(self) -> Path:
        spec, total = self.spec, self.manifest["plan"]["total_duration"]
        out = self.workdir / "audio.m4a"
        fp = _hash(
            [
                _file_sig(spec.narration_path),
                _file_sig(spec.music_path),
                spec.music_volume,
                spec.duck_music,
                spec.target_lufs,
                total,
            ]
        )
        if self._stage_done("audio", fp, out):
            await self._progress("audio", 1, resumed=True)
            return out
        await self._check_cancel()
        fade_start = max(0.0, total - 1.5)
        tail = (
            f"atrim=0:{total:.3f},afade=t=out:st={fade_start:.3f}:d=1.5,aresample=48000,aformat=channel_layouts=stereo"
        )
        inputs: list[str] = []
        if spec.narration_path and spec.music_path:
            inputs = ["-i", spec.narration_path, "-stream_loop", "-1", "-i", spec.music_path]
            narr = f"[0:a]aformat=channel_layouts=stereo,aresample=48000,apad=whole_dur={total:.3f}"
            music = (
                f"[1:a]aformat=channel_layouts=stereo,aresample=48000,volume={spec.music_volume},atrim=0:{total:.3f}"
            )
            if spec.duck_music:
                fc = (
                    f"{narr},asplit=2[n1][n2];{music}[m];"
                    "[m][n1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
                    f"[n2][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I={spec.target_lufs}:TP=-1.5:LRA=11,{tail}[a]"
                )
            else:
                fc = f"{narr}[n];{music}[m];[n][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I={spec.target_lufs}:TP=-1.5:LRA=11,{tail}[a]"
        elif spec.narration_path:
            inputs = ["-i", spec.narration_path]
            fc = f"[0:a]aformat=channel_layouts=stereo,apad=whole_dur={total:.3f},loudnorm=I={spec.target_lufs}:TP=-1.5:LRA=11,{tail}[a]"
        elif spec.music_path:
            inputs = ["-stream_loop", "-1", "-i", spec.music_path]
            fc = f"[0:a]aformat=channel_layouts=stereo,atrim=0:{total:.3f},loudnorm=I={spec.target_lufs - 4}:TP=-1.5:LRA=11,{tail}[a]"
        else:
            inputs = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            fc = "[0:a]anull[a]"
        args = [
            *inputs,
            "-filter_complex",
            fc,
            "-map",
            "[a]",
            "-t",
            f"{total:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(out.with_suffix(".part.m4a")),
        ]

        async def prog(frac: float) -> None:
            await self._progress("audio", frac)

        try:
            await run_ffmpeg(args, expected_duration=total, on_progress=prog)
        except FFmpegError as exc:
            raise RenderFailedError(f"Audio mix failed: {exc}") from exc
        out.with_suffix(".part.m4a").replace(out)
        self._mark("audio", fp)
        return out

    # ------------------------------------------------------------------ subtitles

    def _cues(self) -> list[Cue]:
        spec = self.spec
        if spec.subtitle_path:
            return parse_srt(Path(spec.subtitle_path).read_text(encoding="utf-8", errors="replace"))
        scenes, starts = self._scenes, self.manifest["plan"]["starts"]
        timeline = []
        for i, s in enumerate(scenes):
            # Shift text out of the incoming transition so captions don't overlap the previous scene.
            start = starts[i] + (s.transition_duration / 2 if i else 0)
            end = starts[i] + s.duration - (scenes[i + 1].transition_duration / 2 if i + 1 < len(scenes) else 0)
            timeline.append((start, max(0.3, end - start), s.text))
        return cues_from_scenes(timeline, int(spec.subtitle_style.get("max_words_per_line", 5)))

    async def _subtitles(self) -> Path | None:
        cues = self._cues()
        if not cues:
            self._mark("subtitles", "none")
            await self._progress("subtitles", 1)
            return None
        ass = self.workdir / "subtitles.ass"
        ass.write_text(
            build_ass(cues, self.width, self.height, self.spec.subtitle_style, self.spec.font_name), encoding="utf-8"
        )
        write_srt(cues, self.workdir / "subtitles.srt")
        self._mark("subtitles", _hash([[[c.start, c.end, c.text] for c in cues], self.spec.subtitle_style]))
        await self._progress("subtitles", 1)
        return ass

    # ------------------------------------------------------------------ compose

    async def _compose(self, video: Path, audio: Path, subs: Path | None) -> Path:
        spec = self.spec
        out = self.workdir / "final.mp4"
        fp = _hash(
            [
                self.manifest["stages"]["assemble"]["fingerprint"],
                self.manifest["stages"]["audio"]["fingerprint"],
                self.manifest["stages"]["subtitles"]["fingerprint"],
                spec.burn_subtitles,
                spec.preset,
                spec.crf,
            ]
        )
        if self._stage_done("compose", fp, out):
            await self._progress("compose", 1, resumed=True)
            return out
        await self._check_cancel()
        total = self.manifest["plan"]["total_duration"]
        tmp = out.with_name("final.part.mp4")
        meta = ["-metadata", f"title={spec.title[:200]}"] if spec.title else []
        if subs and spec.burn_subtitles:
            fonts_dir = str(Path(spec.font_file).parent) if spec.font_file else ""
            vf = f"ass='{_escape_filter_path(subs)}'" + (
                f":fontsdir='{_escape_filter_path(fonts_dir)}'" if fonts_dir else ""
            )
            args = [
                "-i",
                str(video),
                "-i",
                str(audio),
                "-vf",
                vf,
                "-map",
                "0:v",
                "-map",
                "1:a",
                *self._encode_args(),
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                "-t",
                f"{total:.3f}",
                *meta,
                str(tmp),
            ]
        elif subs:
            srt = self.workdir / "subtitles.srt"
            args = [
                "-i",
                str(video),
                "-i",
                str(audio),
                "-i",
                str(srt),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map",
                "2:s",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-c:s",
                "mov_text",
                "-movflags",
                "+faststart",
                "-t",
                f"{total:.3f}",
                *meta,
                str(tmp),
            ]
        else:
            args = [
                "-i",
                str(video),
                "-i",
                str(audio),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                "-t",
                f"{total:.3f}",
                *meta,
                str(tmp),
            ]

        async def prog(frac: float) -> None:
            await self._progress("compose", frac)

        try:
            await run_ffmpeg(args, expected_duration=total, on_progress=prog)
        except FFmpegError as exc:
            raise RenderFailedError(f"Final compose failed: {exc}") from exc
        tmp.replace(out)
        self._mark("compose", fp)
        return out

    # ------------------------------------------------------------------ thumbnail

    async def _thumbnail(self, source: Path) -> Path:
        spec = self.spec
        out = self.workdir / "thumbnail.jpg"
        fp = _hash([self.manifest["stages"]["assemble"]["fingerprint"], spec.thumbnail_text])
        if self._stage_done("thumbnail", fp, out):
            await self._progress("thumbnail", 1, resumed=True)
            return out
        # YouTube thumbnails are 1280x720; vertical videos get a 1080x1920 cover image (Reels/Shorts).
        tw, th = (1280, 720) if spec.format == "horizontal" else (1080, 1920)
        first = self._scenes[0].duration
        seek = min(max(0.5, first * 0.4), max(0.0, self.manifest["plan"]["total_duration"] - 0.1))
        vf = f"thumbnail=n=30,scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},eq=contrast=1.08:saturation=1.15"
        if spec.thumbnail_text and spec.font_file:
            wrapped, size = fit_text(
                spec.thumbnail_text.upper(), int(th * (0.07 if th > tw else 0.12)), int(tw * 0.9), max_lines=2
            )
            vf += (
                f",drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.24:color=black@0.45:t=fill"
                f",drawtext=fontfile='{_escape_filter_path(spec.font_file)}':{self._text_file('thumbnail', wrapped)}"
                f":fontsize={size}:fontcolor=white:borderw={max(3, size // 10)}:bordercolor=black:x=(w-text_w)/2:y=h*0.74-text_h/2"
            )
        args = ["-ss", f"{seek:.2f}", "-i", str(source), "-vf", vf, "-frames:v", "1", "-q:v", "2", str(out)]
        try:
            await run_ffmpeg(args)
        except FFmpegError as exc:
            raise RenderFailedError(f"Thumbnail failed: {exc}") from exc
        self._mark("thumbnail", fp)
        await self._progress("thumbnail", 1)
        return out

    # ------------------------------------------------------------------ quality checks

    async def _measure(self, final: Path) -> tuple[float | None, float]:
        """Returns (integrated loudness LUFS, total black seconds)."""
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-i",
            str(final),
            "-filter_complex",
            "[0:a]ebur128=peak=true[aout];[0:v]blackdetect=d=0.5:pix_th=0.05[vout]",
            "-map",
            "[aout]",
            "-map",
            "[vout]",
            "-f",
            "null",
            "-",
        ]
        from app.core.config import settings  # local import keeps module import cheap

        cmd[0] = settings.ffmpeg_bin
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        text = err.decode(errors="replace")
        lufs = None
        m = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", text)
        if m and m[-1] != "-inf":
            lufs = float(m[-1])
        black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", text))
        return lufs, black

    async def _qc(self, final: Path) -> dict[str, Any]:
        await self._progress("qc", 0)
        spec, total = self.spec, self.manifest["plan"]["total_duration"]
        info = await probe_media(final)
        checks: list[dict[str, Any]] = []

        def check(name: str, passed: bool, value: Any, expected: Any, severity: str = "error") -> None:
            checks.append(
                {"name": name, "passed": bool(passed), "value": value, "expected": expected, "severity": severity}
            )

        if info is None:
            check("readable", False, None, "valid MP4")
        else:
            check("container", "mp4" in (info.format_name or ""), info.format_name, "mp4")
            check(
                "resolution",
                (info.width, info.height) == (self.width, self.height),
                f"{info.width}x{info.height}",
                f"{self.width}x{self.height}",
            )
            check("video_codec", info.video_codec == "h264", info.video_codec, "h264")
            check("pixel_format", info.pix_fmt == "yuv420p", info.pix_fmt, "yuv420p")
            check("audio_present", info.has_audio and info.audio_codec == "aac", info.audio_codec, "aac")
            dur_ok = info.duration is not None and abs(info.duration - total) <= max(0.5, total * 0.03)
            check("duration", dur_ok, info.duration, round(total, 2))
            check("file_size", final.stat().st_size > 10_000, final.stat().st_size, ">10KB")
            if spec.format == "vertical":
                check(
                    "shorts_reels_length",
                    (info.duration or 0) <= 180,
                    info.duration,
                    "<=180s for Shorts/Reels",
                    "warning",
                )
            lufs, black = await self._measure(final)
            if spec.narration_path or spec.music_path:
                check(
                    "loudness_lufs",
                    lufs is not None and abs(lufs - spec.target_lufs) <= 3,
                    lufs,
                    spec.target_lufs,
                    "warning",
                )
            check("black_frames", black <= max(1.5, total * 0.1), round(black, 2), "<=10% black", "warning")
        passed = all(c["passed"] for c in checks if c["severity"] == "error")
        report = {
            "passed": passed,
            "checks": checks,
            "warnings": [c["name"] for c in checks if not c["passed"] and c["severity"] == "warning"],
        }
        self.manifest["qc"] = report
        self._mark("qc", _hash(report))
        await self._progress("qc", 1)
        if not passed:
            failed = [c["name"] for c in checks if not c["passed"] and c["severity"] == "error"]
            raise RenderFailedError(f"Quality checks failed: {', '.join(failed)}")
        return report
