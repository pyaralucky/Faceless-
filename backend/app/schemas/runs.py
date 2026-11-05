from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import RunStatus, VideoFormat
from app.schemas.common import Entity

AgentName = Literal["research", "strategy", "script", "fact_check", "storyboard", "optimization"]


class AgentRunCreate(BaseModel):
    agents: list[AgentName] = Field(default_factory=list, description="Subset to run; empty = full pipeline")
    instructions: str = Field(default="", max_length=4000)


class AgentStepOut(Entity):
    agent_name: str
    attempt: int
    status: str
    provider: str | None
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    error: str | None
    output: dict[str, Any]


class AgentRunOut(Entity):
    project_id: uuid.UUID
    status: RunStatus
    agents: list[str]
    input: dict[str, Any]
    error: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    started_at: datetime | None
    finished_at: datetime | None


class AgentRunDetail(AgentRunOut):
    output: dict[str, Any]
    steps: list[AgentStepOut]


class SubtitleStyle(BaseModel):
    font_name: str | None = None
    font_size: int = Field(default=0, ge=0, le=200, description="0 = auto by resolution")
    primary_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    highlight_color: str = Field(default="#FFD400", pattern=r"^#[0-9A-Fa-f]{6}$")
    outline: float = Field(default=4, ge=0, le=20)
    shadow: float = Field(default=1, ge=0, le=20)
    bold: bool = True
    position: Literal["bottom", "center", "top"] = "bottom"
    margin_v: int = Field(default=0, ge=0, le=900, description="0 = auto")
    max_words_per_line: int = Field(default=5, ge=1, le=20)
    uppercase: bool = False


class RenderSceneIn(BaseModel):
    asset_id: uuid.UUID | None = Field(default=None, description="Image or video asset; omitted = solid color card")
    duration: float = Field(default=4.0, gt=0.2, le=600)
    text: str = Field(default="", description="Narration text for this scene (used for subtitles)")
    overlay_text: str = Field(default="", max_length=200, description="Optional on-screen headline")
    transition: Literal[
        "none",
        "fade",
        "fadeblack",
        "wipeleft",
        "wiperight",
        "slideup",
        "slideleft",
        "circleopen",
        "dissolve",
        "smoothleft",
    ] = "fade"
    transition_duration: float = Field(default=0.5, ge=0, le=3)
    motion: Literal["none", "zoom_in", "zoom_out", "pan_left", "pan_right"] = "zoom_in"
    background_color: str = Field(default="#101418", pattern=r"^#[0-9A-Fa-f]{6}$")


class RenderCreate(BaseModel):
    format: VideoFormat | None = None
    scenes: list[RenderSceneIn] | None = Field(default=None, description="Omitted = derive from project storyboard")
    narration_asset_id: uuid.UUID | None = None
    music_asset_id: uuid.UUID | None = None
    subtitle_asset_id: uuid.UUID | None = Field(
        default=None, description="SRT asset; omitted = generated from scene text"
    )
    burn_subtitles: bool = True
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    music_volume: float = Field(default=0.15, ge=0, le=1)
    duck_music: bool = True
    target_lufs: float = Field(default=-14.0, ge=-30, le=-5)
    thumbnail_text: str | None = Field(default=None, max_length=120)


class RenderJobOut(Entity):
    project_id: uuid.UUID
    status: RunStatus
    format: VideoFormat
    progress: float
    stage: str
    qc_report: dict[str, Any]
    output_asset_id: uuid.UUID | None
    thumbnail_asset_id: uuid.UUID | None
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
