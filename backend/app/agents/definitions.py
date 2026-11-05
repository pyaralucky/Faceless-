"""Agent definitions: prompt construction and deterministic offline (mock) outputs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from pydantic import BaseModel

from app.agents import prompts
from app.agents.schemas import (
    FactCheckOutput,
    OptimizationOutput,
    ResearchOutput,
    ScriptOutput,
    StoryboardOutput,
    StrategyOutput,
)

AGENT_ORDER = ["research", "strategy", "script", "fact_check", "storyboard", "optimization"]
WORDS_PER_SECOND = 2.5


class PipelineState(TypedDict, total=False):
    project: dict[str, Any]
    channel: dict[str, Any]
    instructions: str
    research: dict[str, Any]
    strategy: dict[str, Any]
    script: dict[str, Any]
    fact_check: dict[str, Any]
    storyboard: dict[str, Any]
    optimization: dict[str, Any]
    revisions: int
    completed: list[str]


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)[:12000]


def _context(state: PipelineState) -> str:
    p, c = state.get("project", {}), state.get("channel", {})
    parts = [
        f"PROJECT TITLE: {p.get('title')}",
        f"TOPIC: {p.get('topic')}",
        f"TARGET DURATION: {p.get('target_duration_sec')} seconds ({p.get('format')} video)",
        f"CHANNEL: {c.get('name')} | niche: {c.get('niche')} | tone: {c.get('tone')} | language: {c.get('language')}",
        f"AUDIENCE: {c.get('target_audience') or 'general'}",
    ]
    if p.get("brief"):
        parts.append(f"BRIEF: {_j(p['brief'])}")
    if state.get("instructions"):
        parts.append(f"ADDITIONAL INSTRUCTIONS: {state['instructions']}")
    return "\n".join(parts)


# ----------------------------------------------------------------- user prompts


def research_prompt(s: PipelineState) -> str:
    return f"{_context(s)}\n\nResearch this topic for a video."


def strategy_prompt(s: PipelineState) -> str:
    return f"{_context(s)}\n\nRESEARCH:\n{_j(s.get('research', {}))}\n\nDefine the content strategy."


def script_prompt(s: PipelineState) -> str:
    words = int(s.get("project", {}).get("target_duration_sec", 60) * WORDS_PER_SECOND)
    base = (
        f"{_context(s)}\n\nRESEARCH:\n{_j(s.get('research', {}))}\n\nSTRATEGY:\n{_j(s.get('strategy', {}))}\n\n"
        f"Write the script (~{words} words of narration)."
    )
    fc = s.get("fact_check")
    if fc and fc.get("verdict") == "revise" and s.get("script"):
        base += (
            f"\n\nREVISION REQUIRED. Previous script:\n{_j(s['script'])}\n\nFact-check findings:\n{_j(fc)}\n"
            "Fix every issue; remove or soften any claim that cannot be supported."
        )
    return base


def fact_check_prompt(s: PipelineState) -> str:
    return f"RESEARCH NOTES:\n{_j(s.get('research', {}))}\n\nSCRIPT TO CHECK:\n{_j(s.get('script', {}))}"


def storyboard_prompt(s: PipelineState) -> str:
    return (
        f"{_context(s)}\n\nSCRIPT:\n{_j(s.get('script', {}))}\n\n"
        f"Channel branding: {_j(s.get('channel', {}).get('branding', {}))}\nCreate the storyboard."
    )


def optimization_prompt(s: PipelineState) -> str:
    return (
        f"{_context(s)}\n\nSCRIPT:\n{_j(s.get('script', {}))}\n\nRESEARCH KEYWORDS: {s.get('research', {}).get('keywords', [])}\n"
        "Produce publishing metadata for YouTube and Instagram."
    )


# ----------------------------------------------------------------- mock outputs (offline mode)


def _topic(s: PipelineState) -> str:
    return s.get("project", {}).get("topic") or s.get("project", {}).get("title") or "this topic"


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def research_mock(s: PipelineState) -> dict[str, Any]:
    t = _topic(s)
    return ResearchOutput(
        summary=f"An overview of {t}, its background, why it matters and the most surprising details.",
        key_facts=[
            {
                "fact": f"{t} has a documented history that most viewers have never heard.",
                "source_hint": "Encyclopaedia Britannica",
                "confidence": 0.7,
            },
            {
                "fact": f"Experts still debate several aspects of {t}.",
                "source_hint": "Peer-reviewed literature review",
                "confidence": 0.6,
            },
            {
                "fact": f"Interest in {t} has grown steadily in recent years.",
                "source_hint": "Google Trends",
                "confidence": 0.65,
            },
        ],
        audience_insights=[
            "Viewers want a clear payoff within the first seconds",
            "Concrete examples outperform abstractions",
        ],
        content_angles=[f"The hidden story behind {t}", f"3 things nobody tells you about {t}"],
        keywords=[w for w in re.findall(r"[A-Za-z]{4,}", t.lower())][:5] or ["facts", "explained"],
        open_questions=[],
    ).model_dump()


def strategy_mock(s: PipelineState) -> dict[str, Any]:
    t = _topic(s)
    dur = int(s.get("project", {}).get("target_duration_sec", 60))
    return StrategyOutput(
        chosen_angle=(s.get("research", {}).get("content_angles") or [f"The hidden story behind {t}"])[0],
        rationale="Curiosity gap angle with a fast payoff fits short-form retention patterns.",
        hook_options=[f"You've been thinking about {t} all wrong.", f"Here's what nobody tells you about {t}."],
        target_emotion="curiosity",
        structure=["Hook", "Context", "Surprising detail", "Payoff", "Call to action"],
        call_to_action="Follow for more stories like this.",
        title_ideas=[f"The Truth About {t.title()}", f"{t.title()} Explained in {dur} Seconds"],
        estimated_duration_sec=dur,
    ).model_dump()


def script_mock(s: PipelineState) -> dict[str, Any]:
    t = _topic(s)
    st = s.get("strategy", {})
    hook = (st.get("hook_options") or [f"Here's what nobody tells you about {t}."])[0]
    sections = [
        {
            "heading": "Context",
            "narration": f"To understand {t}, we need to start at the beginning. The story is stranger than most people think.",
            "visual_notes": "Establishing wide shot, archival feel",
        },
        {
            "heading": "Surprising detail",
            "narration": f"Experts still debate key parts of {t}. And the details they agree on are surprising.",
            "visual_notes": "Close-up details, slow zoom",
        },
        {
            "heading": "Payoff",
            "narration": f"So next time someone mentions {t}, you will know the real story behind it.",
            "visual_notes": "Bright resolving shot",
        },
    ]
    cta = st.get("call_to_action", "Follow for more.")
    full = " ".join([hook, *[x["narration"] for x in sections], cta])
    wc = len(full.split())
    return ScriptOutput(
        title=(st.get("title_ideas") or [s.get("project", {}).get("title", t)])[0],
        hook=hook,
        sections=sections,
        call_to_action=cta,
        full_narration=full,
        word_count=wc,
        estimated_duration_sec=max(5, round(wc / WORDS_PER_SECOND)),
    ).model_dump()


def fact_check_mock(s: PipelineState) -> dict[str, Any]:
    claims = [
        {"claim": x, "status": "supported", "note": "Consistent with research notes."}
        for x in _sentences(s.get("script", {}).get("full_narration", ""))[:5]
    ]
    return FactCheckOutput(verdict="pass", overall_confidence=0.8, claims=claims, required_changes=[]).model_dump()


def storyboard_mock(s: PipelineState) -> dict[str, Any]:
    script = s.get("script", {})
    lines = _sentences(script.get("full_narration", "")) or [_topic(s)]
    motions = ["zoom_in", "pan_left", "zoom_out", "pan_right"]
    transitions = ["fade", "slideleft", "dissolve", "wipeleft"]
    scenes = []
    for i, line in enumerate(lines):
        dur = round(min(8.0, max(2.0, len(line.split()) / WORDS_PER_SECOND)), 2)
        scenes.append(
            {
                "index": i,
                "duration_sec": dur,
                "narration": line,
                "visual_prompt": f"Cinematic, moody illustration representing: {line[:120]}",
                "shot_type": "wide" if i == 0 else "medium",
                "motion": motions[i % 4],
                "transition": transitions[i % 4],
                "overlay_text": script.get("hook", "")[:60] if i == 0 else "",
            }
        )
    return StoryboardOutput(
        scenes=scenes,
        visual_style="Cinematic, high contrast, consistent warm color grade",
        music_mood="mysterious, building",
        total_duration_sec=round(sum(x["duration_sec"] for x in scenes), 2),
    ).model_dump()


def optimization_mock(s: PipelineState) -> dict[str, Any]:
    t = _topic(s)
    kws = s.get("research", {}).get("keywords", [])
    return OptimizationOutput(
        titles=[s.get("script", {}).get("title") or t.title(), f"What Nobody Tells You About {t.title()}"],
        description=f"The real story behind {t}.\n\nIn this video we break down {t}: background, surprising details and why it matters.",
        tags=[*kws, "explained", "facts", "shorts"][:15],
        hashtags=["#shorts", "#facts", "#explained"],
        thumbnail_text="THE TRUTH",
        thumbnail_prompt=f"Bold dramatic visual about {t}, high contrast, single focal subject",
        best_posting_times_utc=["14:00", "18:00"],
        platform_notes={
            "youtube": "Use as a Short (<60s) with vertical format.",
            "instagram": "Post as a Reel; first line of caption is the hook.",
        },
        seo_score=72,
    ).model_dump()


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    system_prompt: str
    output_model: type[BaseModel]
    build_prompt: Callable[[PipelineState], str]
    mock: Callable[[PipelineState], dict[str, Any]]
    requires: tuple[str, ...] = ()


AGENTS: dict[str, AgentSpec] = {
    "research": AgentSpec("research", prompts.RESEARCH, ResearchOutput, research_prompt, research_mock),
    "strategy": AgentSpec("strategy", prompts.STRATEGY, StrategyOutput, strategy_prompt, strategy_mock, ("research",)),
    "script": AgentSpec("script", prompts.SCRIPT, ScriptOutput, script_prompt, script_mock, ("research", "strategy")),
    "fact_check": AgentSpec(
        "fact_check", prompts.FACT_CHECK, FactCheckOutput, fact_check_prompt, fact_check_mock, ("research", "script")
    ),
    "storyboard": AgentSpec(
        "storyboard", prompts.STORYBOARD, StoryboardOutput, storyboard_prompt, storyboard_mock, ("script",)
    ),
    "optimization": AgentSpec(
        "optimization", prompts.OPTIMIZATION, OptimizationOutput, optimization_prompt, optimization_mock, ("script",)
    ),
}
