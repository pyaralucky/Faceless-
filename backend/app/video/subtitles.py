"""Subtitle cue generation (from scene narration or SRT) and styled ASS output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


@dataclass(slots=True)
class Cue:
    start: float
    end: float
    text: str


def _parse_ts(ts: str) -> float:
    m = _SRT_TIME.search(ts)
    if not m:
        raise ValueError(f"Bad SRT timestamp: {ts}")
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(content: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
        lines = [x for x in block.strip().splitlines() if x.strip()]
        idx = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if idx is None:
            continue
        start_s, _, end_s = lines[idx].partition("-->")
        text = " ".join(lines[idx + 1 :]).strip()
        text = re.sub(r"<[^>]+>", "", text)
        if text:
            cues.append(Cue(_parse_ts(start_s), _parse_ts(end_s), text))
    return cues


def chunk_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)] if words else []


def cues_from_scenes(scenes: list[tuple[float, float, str]], max_words: int) -> list[Cue]:
    """scenes: (start, duration, narration). Chunks are timed proportionally to word count."""
    cues: list[Cue] = []
    for start, duration, text in scenes:
        chunks = chunk_words(text, max_words)
        if not chunks:
            continue
        total_words = sum(len(c.split()) for c in chunks)
        t = start
        for c in chunks:
            d = duration * len(c.split()) / total_words
            cues.append(Cue(round(t, 3), round(t + d, 3), c))
            t += d
    return cues


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(cues: list[Cue], width: int, height: int, style: dict[str, Any], default_font: str) -> str:
    vertical = height > width
    font_size = style.get("font_size") or (int(height * 0.045) if vertical else int(height * 0.06))
    position = style.get("position", "bottom")
    alignment = {"bottom": 2, "center": 5, "top": 8}[position]
    margin_v = style.get("margin_v") or (
        int(height * 0.18) if vertical and position == "bottom" else int(height * 0.06)
    )
    upper = style.get("uppercase", False)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.get('font_name') or default_font},{font_size},{_ass_color(style.get('primary_color', '#FFFFFF'))},{_ass_color(style.get('highlight_color', '#FFD400'))},{_ass_color(style.get('outline_color', '#000000'))},&H80000000,{-1 if style.get('bold', True) else 0},0,0,0,100,100,0,0,1,{style.get('outline', 4)},{style.get('shadow', 1)},{alignment},{int(width * 0.08)},{int(width * 0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in cues:
        text = _escape(c.text.upper() if upper else c.text)
        # subtle pop-in animation
        lines.append(f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Default,,0,0,0,,{{\\fad(80,40)}}{text}")
    return header + "\n".join(lines) + "\n"


def write_srt(cues: list[Cue], path: Path) -> None:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"

    path.write_text(
        "\n".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1)), encoding="utf-8"
    )
