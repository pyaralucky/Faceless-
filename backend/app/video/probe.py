"""ffprobe helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass(slots=True)
class MediaInfo:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    has_video: bool = False
    has_audio: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None
    pix_fmt: str | None = None
    fps: float | None = None
    format_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _fps(rate: str | None) -> float | None:
    if not rate or rate == "0/0":
        return None
    num, _, den = rate.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None


async def probe_media(path: Path) -> MediaInfo | None:
    proc = await asyncio.create_subprocess_exec(
        settings.ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    data = json.loads(out or b"{}")
    info = MediaInfo(raw=data, format_name=data.get("format", {}).get("format_name"))
    try:
        info.duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        info.duration = None
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            # Still images report codec_type=video too (mjpeg/png); duration will be ~0/None.
            info.has_video = True
            info.video_codec = s.get("codec_name")
            info.width, info.height = s.get("width"), s.get("height")
            info.pix_fmt = s.get("pix_fmt")
            info.fps = _fps(s.get("avg_frame_rate"))
        elif s.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = s.get("codec_name")
    return info
