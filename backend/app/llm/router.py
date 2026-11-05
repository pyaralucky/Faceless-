"""Configurable model router: per-agent model selection, fallbacks, retries and token accounting."""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.llm.base import LLMMessage, LLMProviderError, LLMRequest, ProviderConfig, StructuredOutputError
from app.llm.pricing import estimate_cost
from app.llm.providers import build_provider
from app.llm.structured import parse_structured, schema_instructions
from app.models import ModelRoute, ProviderCredential

log = get_logger(__name__)

# Providers that work without an API key.
KEYLESS = {"mock", "ollama"}


@dataclass(slots=True)
class ModelTarget:
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass(slots=True)
class AttemptRecord:
    agent_name: str
    attempt: int
    provider: str
    model: str
    status: str  # succeeded | retry | failed
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StructuredResult[T: BaseModel]:
    data: T
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    attempts: int


AttemptCallback = Callable[[AttemptRecord], Awaitable[None]]


class AllModelsFailedError(Exception):
    pass


class ModelRouter:
    def __init__(
        self,
        routes: dict[str, ModelRoute | ModelTarget | dict[str, Any]],
        credentials: dict[str, ProviderConfig],
        *,
        max_retries: int | None = None,
        http_client: httpx.AsyncClient | None = None,
        backoff_base: float = 1.0,
    ):
        self.routes = routes
        self.credentials = credentials
        self.max_retries = max_retries or settings.llm_max_retries
        self.http_client = http_client
        self.backoff_base = backoff_base

    # ------------------------------------------------------------------ construction

    @classmethod
    async def for_organization(cls, db: AsyncSession, org_id: uuid.UUID, **kwargs: Any) -> ModelRouter:
        routes = {
            r.agent_name: r
            for r in (await db.scalars(select(ModelRoute).where(ModelRoute.organization_id == org_id))).all()
        }
        creds: dict[str, ProviderConfig] = {}
        rows = await db.scalars(
            select(ProviderCredential)
            .where(ProviderCredential.organization_id == org_id, ProviderCredential.is_active.is_(True))
            .order_by(ProviderCredential.created_at)
        )
        for c in rows.all():
            creds.setdefault(
                c.provider,
                ProviderConfig(
                    provider=c.provider,
                    api_key=decrypt_secret(c.encrypted_api_key),
                    base_url=c.base_url,
                    extra=dict(c.config or {}),
                ),
            )
        return cls(routes, creds, **kwargs)

    # ------------------------------------------------------------------ selection

    def resolve(self, agent_name: str) -> list[ModelTarget]:
        route = self.routes.get(agent_name) or self.routes.get("*")
        if route is None:
            return [ModelTarget(settings.llm_default_provider, settings.llm_default_model)]
        if isinstance(route, ModelTarget):
            return [route]
        get = (
            (lambda k, d=None: route.get(k, d)) if isinstance(route, dict) else (lambda k, d=None: getattr(route, k, d))
        )
        temperature = float(get("temperature", 0.7))
        max_tokens = int(get("max_tokens", 4096))
        chain = [ModelTarget(get("provider"), get("model"), temperature, max_tokens)]
        for fb in get("fallbacks", []) or []:
            chain.append(ModelTarget(fb["provider"], fb["model"], temperature, max_tokens))
        return chain

    def _provider_config(self, provider: str) -> ProviderConfig:
        cfg = self.credentials.get(provider)
        if cfg is None:
            if provider in KEYLESS:
                return ProviderConfig(provider=provider)
            raise LLMProviderError(f"No active API credential configured for provider '{provider}'", retryable=False)
        return cfg

    # ------------------------------------------------------------------ execution

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = min(30.0, self.backoff_base * (2 ** (attempt - 1))) * (0.5 + random.random())
        await asyncio.sleep(delay)

    async def generate_structured[T: BaseModel](
        self,
        *,
        agent_name: str,
        system: str,
        user: str,
        output_model: type[T],
        on_attempt: AttemptCallback | None = None,
        mock_response: dict[str, Any] | None = None,
    ) -> StructuredResult[T]:
        errors: list[str] = []
        total_prompt = total_completion = 0
        total_cost = 0.0
        attempt_no = 0
        for target in self.resolve(agent_name):
            try:
                cfg = self._provider_config(target.provider)
                provider = build_provider(cfg, self.http_client)
            except LLMProviderError as exc:
                errors.append(f"{target.provider}/{target.model}: {exc}")
                attempt_no += 1
                if on_attempt:
                    await on_attempt(
                        AttemptRecord(agent_name, attempt_no, target.provider, target.model, "failed", error=str(exc))
                    )
                continue

            messages = [
                LLMMessage("system", f"{system}\n\n{schema_instructions(output_model)}"),
                LLMMessage("user", user),
            ]
            for local_attempt in range(1, self.max_retries + 1):
                attempt_no += 1
                started = time.perf_counter()
                req = LLMRequest(
                    model=target.model,
                    messages=messages,
                    temperature=target.temperature,
                    max_tokens=target.max_tokens,
                    json_schema=output_model.model_json_schema(),
                    schema_name=output_model.__name__,
                    mock_response=mock_response,
                )
                record = AttemptRecord(agent_name, attempt_no, target.provider, target.model, "retry")
                try:
                    resp = await provider.complete(req)
                    record.prompt_tokens, record.completion_tokens = resp.prompt_tokens, resp.completion_tokens
                    record.cost_usd = estimate_cost(
                        target.model, resp.prompt_tokens, resp.completion_tokens, cfg.extra.get("pricing")
                    )
                    total_prompt += resp.prompt_tokens
                    total_completion += resp.completion_tokens
                    total_cost += record.cost_usd
                    try:
                        parsed = parse_structured(resp.text, output_model)
                    except StructuredOutputError as exc:
                        # Ask the model to repair its own output on the next attempt.
                        record.error = str(exc)
                        messages = [
                            *messages[:2],
                            LLMMessage("assistant", resp.text[:8000]),
                            LLMMessage(
                                "user",
                                f"Your previous reply was invalid: {exc}. Return ONLY the corrected JSON object.",
                            ),
                        ]
                        record.latency_ms = int((time.perf_counter() - started) * 1000)
                        if on_attempt:
                            await on_attempt(record)
                        errors.append(f"{target.provider}/{target.model}#{local_attempt}: {exc}")
                        continue
                    record.status = "succeeded"
                    record.latency_ms = int((time.perf_counter() - started) * 1000)
                    record.output = parsed.model_dump(mode="json")
                    if on_attempt:
                        await on_attempt(record)
                    log.info(
                        "llm_call_succeeded",
                        extra={
                            "agent": agent_name,
                            "provider": target.provider,
                            "model": target.model,
                            "tokens": resp.prompt_tokens + resp.completion_tokens,
                        },
                    )
                    return StructuredResult(
                        parsed,
                        target.provider,
                        target.model,
                        total_prompt,
                        total_completion,
                        round(total_cost, 6),
                        attempt_no,
                    )
                except LLMProviderError as exc:
                    record.error = str(exc)
                    record.latency_ms = int((time.perf_counter() - started) * 1000)
                    record.status = "retry" if exc.retryable and local_attempt < self.max_retries else "failed"
                    if on_attempt:
                        await on_attempt(record)
                    errors.append(f"{target.provider}/{target.model}#{local_attempt}: {exc}")
                    log.warning(
                        "llm_call_failed",
                        extra={"agent": agent_name, "provider": target.provider, "error": str(exc)[:300]},
                    )
                    if not exc.retryable:
                        break
                    if local_attempt < self.max_retries:
                        await self._sleep_backoff(local_attempt)
        raise AllModelsFailedError(f"All model targets failed for agent '{agent_name}': " + " | ".join(errors[-6:]))
