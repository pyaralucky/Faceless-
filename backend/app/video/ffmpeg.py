"""Async FFmpeg runner with real-time progress parsing."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Sequence

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

ProgressFn = Callable[[float], Awaitable[None] | None]


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(f"{message}\n{stderr_tail}".strip())
        self.stderr_tail = stderr_tail


async def run_ffmpeg(
    args: Sequence[str],
    *,
    expected_duration: float | None = None,
    on_progress: ProgressFn | None = None,
    time_limit: float | None = 3600,
) -> str:
    """Run ffmpeg; `args` exclude the binary. Reports progress in [0, 1]. Returns stderr tail."""
    cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    log.debug("ffmpeg_exec", extra={"cmd": " ".join(cmd)[:2000]})
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stderr_lines: deque[str] = deque(maxlen=40)

    async def read_stderr() -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            stderr_lines.append(raw.decode(errors="replace").rstrip())

    async def read_progress() -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            key, _, value = line.partition("=")
            if key in ("out_time_us", "out_time_ms") and expected_duration and on_progress:
                try:
                    seconds = int(value) / 1_000_000  # both keys are microseconds in modern ffmpeg
                except ValueError:
                    continue
                res = on_progress(max(0.0, min(1.0, seconds / expected_duration)))
                if asyncio.iscoroutine(res):
                    await res

    try:
        await asyncio.wait_for(asyncio.gather(read_stderr(), read_progress(), proc.wait()), timeout=time_limit)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise FFmpegError("ffmpeg timed out", "\n".join(stderr_lines)) from exc
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    tail = "\n".join(stderr_lines)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg exited with code {proc.returncode}", tail)
    if on_progress:
        res = on_progress(1.0)
        if asyncio.iscoroutine(res):
            await res
    return tail
