"""Helpers for robust structured (JSON) output."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.base import StructuredOutputError

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def extract_json(text: str) -> Any:
    """Parse JSON from model output, tolerating code fences and leading/trailing prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"Invalid JSON: {exc.msg} at pos {exc.pos}") from exc
    raise StructuredOutputError("No JSON object found in model output")


def parse_structured[T: BaseModel](text: str, model: type[T]) -> T:
    data = extract_json(text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10])
        raise StructuredOutputError(f"Schema validation failed: {problems}") from exc


def schema_instructions(model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), separators=(",", ":"))
    return (
        "Respond with a single JSON object only — no markdown, no commentary. "
        f"It MUST validate against this JSON Schema:\n{schema}"
    )
