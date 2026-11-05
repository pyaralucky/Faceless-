"""Structured output contracts for each agent (validated with Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KeyFact(BaseModel):
    fact: str
    source_hint: str = Field(description="Where this can be verified (publication, dataset, institution)")
    confidence: float = Field(ge=0, le=1)


class ResearchOutput(BaseModel):
    summary: str
    key_facts: list[KeyFact] = Field(min_length=1)
    audience_insights: list[str] = Field(default_factory=list)
    content_angles: list[str] = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class StrategyOutput(BaseModel):
    chosen_angle: str
    rationale: str
    hook_options: list[str] = Field(min_length=1)
    target_emotion: str
    structure: list[str] = Field(min_length=2, description="Ordered section names")
    call_to_action: str
    title_ideas: list[str] = Field(min_length=1)
    estimated_duration_sec: int = Field(ge=10, le=3600)


class ScriptSection(BaseModel):
    heading: str
    narration: str
    visual_notes: str = ""


class ScriptOutput(BaseModel):
    title: str
    hook: str
    sections: list[ScriptSection] = Field(min_length=1)
    call_to_action: str
    full_narration: str
    word_count: int = Field(ge=1)
    estimated_duration_sec: int = Field(ge=5)


class ClaimCheck(BaseModel):
    claim: str
    status: Literal["supported", "unverified", "false", "misleading"]
    note: str = ""
    suggested_fix: str = ""


class FactCheckOutput(BaseModel):
    verdict: Literal["pass", "revise"]
    overall_confidence: float = Field(ge=0, le=1)
    claims: list[ClaimCheck] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)


class StoryboardScene(BaseModel):
    index: int = Field(ge=0)
    duration_sec: float = Field(gt=0.5, le=60)
    narration: str
    visual_prompt: str = Field(description="Prompt for image/video generation or stock search")
    shot_type: str = "medium"
    motion: Literal["none", "zoom_in", "zoom_out", "pan_left", "pan_right"] = "zoom_in"
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
    overlay_text: str = ""


class StoryboardOutput(BaseModel):
    scenes: list[StoryboardScene] = Field(min_length=1)
    visual_style: str
    music_mood: str
    total_duration_sec: float = Field(gt=0)


class PlatformNotes(BaseModel):
    youtube: str = ""
    instagram: str = ""


class OptimizationOutput(BaseModel):
    titles: list[str] = Field(min_length=1)
    description: str
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    thumbnail_text: str = Field(max_length=60)
    thumbnail_prompt: str
    best_posting_times_utc: list[str] = Field(default_factory=list)
    platform_notes: PlatformNotes = Field(default_factory=PlatformNotes)
    seo_score: int = Field(ge=0, le=100)
