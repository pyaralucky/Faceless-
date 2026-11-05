import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.llm.base import LLMMessage, LLMProviderError, LLMRequest, LLMResponse, ProviderConfig, StructuredOutputError
from app.llm.pricing import estimate_cost
from app.llm.providers import PROVIDER_CLASSES, AnthropicProvider, GoogleProvider, OpenAICompatibleProvider
from app.llm.router import AllModelsFailedError, ModelRouter, ModelTarget
from app.llm.structured import extract_json, parse_structured


class Out(BaseModel):
    title: str
    score: int


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    with pytest.raises(StructuredOutputError):
        extract_json("no json here")
    with pytest.raises(StructuredOutputError):
        parse_structured('{"title": "x"}', Out)


def test_cost_estimation():
    pricing = {"gpt-4.1": {"input": 2.0, "output": 8.0}, "gpt-4.1-mini": {"input": 0.4, "output": 1.6}}
    assert estimate_cost("gpt-4.1-mini-2025", 1_000_000, 0, pricing) == 0.4  # longest prefix wins
    assert estimate_cost("unknown", 1000, 1000, pricing) == 0.0
    assert estimate_cost("gpt-4.1", 500_000, 250_000, pricing) == 3.0


class ScriptedProvider:
    """Returns queued responses / raises queued errors."""

    def __init__(self, name: str, script: list):
        self.name, self.script, self.calls = name, script, 0

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, provider=self.name, model=req.model, prompt_tokens=10, completion_tokens=5)


@pytest.fixture
def scripted(monkeypatch):
    providers: dict[str, ScriptedProvider] = {}

    def fake_build(config, client=None):
        return providers[config.provider]

    monkeypatch.setattr("app.llm.router.build_provider", fake_build)
    return providers


async def test_router_retries_then_succeeds(scripted):
    scripted["openai"] = ScriptedProvider(
        "openai", [LLMProviderError("503", retryable=True), '{"title": "ok", "score": 3}']
    )
    router = ModelRouter(
        {"*": ModelTarget("openai", "gpt")}, {"openai": ProviderConfig("openai", "k")}, backoff_base=0.001
    )
    attempts = []

    async def log(rec):
        attempts.append(rec)

    res = await router.generate_structured(agent_name="script", system="s", user="u", output_model=Out, on_attempt=log)
    assert res.data.title == "ok" and res.attempts == 2
    assert [a.status for a in attempts] == ["retry", "succeeded"]
    assert res.prompt_tokens == 10  # failed transport attempt consumed no tokens


async def test_router_repairs_invalid_json(scripted):
    p = ScriptedProvider("openai", ['{"title": "missing score"}', '{"title": "fixed", "score": 1}'])
    scripted["openai"] = p
    router = ModelRouter(
        {"*": ModelTarget("openai", "gpt")}, {"openai": ProviderConfig("openai", "k")}, backoff_base=0.001
    )
    res = await router.generate_structured(agent_name="x", system="s", user="u", output_model=Out)
    assert res.data.title == "fixed"
    assert res.prompt_tokens == 20 and res.completion_tokens == 10  # both attempts counted


async def test_router_falls_back_to_next_model(scripted):
    scripted["openai"] = ScriptedProvider("openai", [LLMProviderError("401 bad key", retryable=False)])
    scripted["anthropic"] = ScriptedProvider("anthropic", ['{"title": "from claude", "score": 9}'])
    routes = {
        "script": {
            "provider": "openai",
            "model": "gpt",
            "fallbacks": [{"provider": "anthropic", "model": "claude-sonnet-5-5"}],
        }
    }
    creds = {"openai": ProviderConfig("openai", "k"), "anthropic": ProviderConfig("anthropic", "k")}
    res = await ModelRouter(routes, creds, backoff_base=0.001).generate_structured(
        agent_name="script", system="s", user="u", output_model=Out
    )
    assert res.provider == "anthropic" and res.data.score == 9
    assert scripted["openai"].calls == 1  # non-retryable -> no retries


async def test_router_missing_credentials_and_exhaustion(scripted):
    router = ModelRouter({"*": ModelTarget("openai", "gpt")}, {}, backoff_base=0.001)
    with pytest.raises(AllModelsFailedError, match="No active API credential"):
        await router.generate_structured(agent_name="x", system="s", user="u", output_model=Out)
    scripted["openai"] = ScriptedProvider("openai", [LLMProviderError("503")] * 3)
    router = ModelRouter(
        {"*": ModelTarget("openai", "gpt")},
        {"openai": ProviderConfig("openai", "k")},
        max_retries=3,
        backoff_base=0.001,
    )
    with pytest.raises(AllModelsFailedError):
        await router.generate_structured(agent_name="x", system="s", user="u", output_model=Out)
    assert scripted["openai"].calls == 3


def test_route_resolution_defaults():
    r = ModelRouter({}, {})
    assert r.resolve("research")[0].provider == "mock"
    r = ModelRouter({"*": {"provider": "openai", "model": "a"}, "script": {"provider": "anthropic", "model": "b"}}, {})
    assert r.resolve("script")[0].model == "b" and r.resolve("research")[0].model == "a"


@respx.mock
async def test_openai_adapter():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "x",
                "model": "gpt-4.1",
                "choices": [{"message": {"content": '{"a":1}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )
    )
    p = OpenAICompatibleProvider(ProviderConfig("openai", "sk"))
    res = await p.complete(LLMRequest(model="gpt-4.1", messages=[LLMMessage("user", "hi")], json_schema={}))
    assert res.prompt_tokens == 12 and res.text == '{"a":1}'
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert route.calls[0].request.headers["authorization"] == "Bearer sk"


@respx.mock
async def test_anthropic_adapter_and_errors():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=[
            httpx.Response(529, json={"error": "overloaded"}),
            httpx.Response(
                200,
                json={
                    "id": "m",
                    "model": "claude-sonnet-5-5",
                    "content": [{"type": "text", "text": "{}"}],
                    "usage": {"input_tokens": 7, "output_tokens": 2},
                },
            ),
        ]
    )
    p = AnthropicProvider(ProviderConfig("anthropic", "key"))
    req = LLMRequest(model="claude-sonnet-5-5", messages=[LLMMessage("system", "sys"), LLMMessage("user", "hi")])
    with pytest.raises(LLMProviderError) as ei:
        await p.complete(req)
    assert ei.value.retryable
    res = await p.complete(req)
    assert res.prompt_tokens == 7 and res.completion_tokens == 2
    body = json.loads(route.calls[1].request.content)
    assert body["system"] == "sys" and body["messages"] == [{"role": "user", "content": "hi"}]
    assert route.calls[1].request.headers["x-api-key"] == "key"


@respx.mock
async def test_google_adapter():
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 6},
            },
        )
    )
    res = await GoogleProvider(ProviderConfig("google", "g")).complete(
        LLMRequest(model="gemini-2.5-flash", messages=[LLMMessage("user", "x")], json_schema={})
    )
    assert res.completion_tokens == 6 and res.text == '{"ok": true}'
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/bad:generateContent").mock(
        return_value=httpx.Response(400, text="bad")
    )
    with pytest.raises(LLMProviderError) as ei:
        await GoogleProvider(ProviderConfig("google", "g")).complete(
            LLMRequest(model="bad", messages=[LLMMessage("user", "x")])
        )
    assert not ei.value.retryable


def test_all_providers_registered():
    assert {"openai", "anthropic", "google", "openrouter", "azure_openai", "ollama", "mock"} <= set(PROVIDER_CLASSES)
