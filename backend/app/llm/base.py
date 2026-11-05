"""Provider-agnostic LLM request/response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(slots=True)
class LLMRequest:
    model: str
    messages: list[LLMMessage]
    temperature: float = 0.7
    max_tokens: int = 4096
    json_schema: dict[str, Any] | None = None
    schema_name: str = "output"
    # Used only by the mock provider to return deterministic, schema-valid content.
    mock_response: dict[str, Any] | None = None


@dataclass(slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProviderError(Exception):
    """Raised by providers. `retryable` drives the router's retry/fallback behaviour."""

    def __init__(self, message: str, *, retryable: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class StructuredOutputError(Exception):
    """Model returned text that is not valid JSON for the requested schema."""


@dataclass(slots=True)
class ProviderConfig:
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
