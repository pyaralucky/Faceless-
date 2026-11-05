"""LLM provider adapters using plain HTTPS (no vendor SDK lock-in)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings
from app.llm.base import LLMProviderError, LLMRequest, LLMResponse, ProviderConfig

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.status_code >= 400:
        body = resp.text[:500]
        raise LLMProviderError(
            f"{provider} HTTP {resp.status_code}: {body}",
            retryable=resp.status_code in RETRYABLE_STATUS,
            status_code=resp.status_code,
        )


class BaseProvider:
    name = "base"

    def __init__(self, config: ProviderConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self._client = client

    async def _post(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"{self.name} timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise LLMProviderError(f"{self.name} transport error: {exc}", retryable=True) from exc
        finally:
            if self._client is None:
                await client.aclose()
        _raise_for_status(resp, self.name)
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"{self.name} returned non-JSON body", retryable=True) from exc

    async def complete(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover - interface
        raise NotImplementedError


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI, OpenRouter, Azure OpenAI (v1 API), Ollama and any OpenAI-compatible gateway."""

    DEFAULT_BASE = {
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "ollama": "http://localhost:11434/v1",
    }

    def __init__(self, config: ProviderConfig, client: httpx.AsyncClient | None = None):
        super().__init__(config, client)
        self.name = config.provider

    async def complete(self, req: LLMRequest) -> LLMResponse:
        base = (self.config.base_url or self.DEFAULT_BASE.get(self.name, "https://api.openai.com/v1")).rstrip("/")
        headers = {"Content-Type": "application/json"}
        if self.name == "azure_openai":
            headers["api-key"] = self.config.api_key or ""
        elif self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        data = await self._post(f"{base}/chat/completions", headers=headers, payload=payload)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMProviderError(f"{self.name} malformed response", retryable=True) from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=data.get("model", req.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw={"id": data.get("id"), "finish_reason": data["choices"][0].get("finish_reason")},
        )


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        base = (self.config.base_url or "https://api.anthropic.com").rstrip("/")
        system = "\n\n".join(m.content for m in req.messages if m.role == "system")
        messages = [{"role": m.role, "content": m.content} for m in req.messages if m.role != "system"]
        payload: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": messages,
            "temperature": req.temperature,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        data = await self._post(f"{base}/v1/messages", headers=headers, payload=payload)
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=data.get("model", req.model),
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            raw={"id": data.get("id"), "stop_reason": data.get("stop_reason")},
        )


class GoogleProvider(BaseProvider):
    name = "google"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        base = (self.config.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        system = "\n\n".join(m.content for m in req.messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in req.messages
            if m.role != "system"
        ]
        gen_cfg: dict[str, Any] = {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}
        if req.json_schema is not None:
            gen_cfg["responseMimeType"] = "application/json"
        payload: dict[str, Any] = {"contents": contents, "generationConfig": gen_cfg}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.config.api_key or ""}
        data = await self._post(f"{base}/models/{req.model}:generateContent", headers=headers, payload=payload)
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise LLMProviderError("google returned no candidates", retryable=True) from exc
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text="".join(p.get("text", "") for p in parts),
            provider=self.name,
            model=req.model,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
        )


class MockProvider(BaseProvider):
    """Offline provider for development, demos and tests. Returns the agent-supplied mock payload."""

    name = "mock"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if self.config.extra.get("fail_times", 0) > 0:
            self.config.extra["fail_times"] -= 1
            raise LLMProviderError("mock transient failure", retryable=True, status_code=503)
        payload = req.mock_response if req.mock_response is not None else {"text": "mock"}
        text = json.dumps(payload)
        prompt_chars = sum(len(m.content) for m in req.messages)
        return LLMResponse(
            text=text,
            provider=self.name,
            model=req.model,
            prompt_tokens=max(1, prompt_chars // 4),
            completion_tokens=max(1, len(text) // 4),
        )


PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAICompatibleProvider,
    "openrouter": OpenAICompatibleProvider,
    "azure_openai": OpenAICompatibleProvider,
    "ollama": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "mock": MockProvider,
}


def build_provider(config: ProviderConfig, client: httpx.AsyncClient | None = None) -> BaseProvider:
    cls = PROVIDER_CLASSES.get(config.provider)
    if cls is None:
        raise LLMProviderError(f"Unknown provider '{config.provider}'", retryable=False)
    return cls(config, client)
