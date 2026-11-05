"""Fully-resolved render specification (paths, not asset ids). Stored on RenderJob.spec."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

RESOLUTIONS = {"vertical": (1080, 1920), "horizontal": (1920, 1080)}

Transition = Literal[
    "none", "fade", "fadeblack", "wipeleft", "wiperight", "slideup", "slideleft", "circleopen", "dissolve", "smoothleft"
]
Motion = Literal["none", "zoom_in", "zoom_out", "pan_left", "pan_right"]


class SceneSpec(BaseModel):
    source_path: str | None = None  # absolute path
    source_kind: Literal["image", "video", "color"] = "color"
    duration: float = Field(gt=0.2)
    text: str = ""
    overlay_text: str = ""
    transition: Transition = "fade"
    transition_duration: float = 0.5
    motion: Motion = "zoom_in"
    background_color: str = "#101418"

    def fingerprint(self, extra: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps([self.model_dump(), extra], sort_keys=True).encode()).hexdigest()[:16]


class RenderSpec(BaseModel):
    format: Literal["vertical", "horizontal"]
    fps: int = 30
    title: str = ""
    scenes: list[SceneSpec] = Field(min_length=1)
    narration_path: str | None = None
    music_path: str | None = None
    subtitle_path: str | None = None
    burn_subtitles: bool = True
    subtitle_style: dict[str, Any] = Field(default_factory=dict)
    music_volume: float = 0.15
    duck_music: bool = True
    target_lufs: float = -14.0
    fit_to_narration: bool = True
    thumbnail_text: str | None = None
    # encoder settings (overridable for tests / fast previews)
    preset: str = "medium"
    crf: int = 20
    font_file: str = ""
    font_name: str = "DejaVu Sans"

    @property
    def size(self) -> tuple[int, int]:
        return RESOLUTIONS[self.format]
