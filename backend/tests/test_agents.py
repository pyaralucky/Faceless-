import uuid

from sqlalchemy import select

from app.agents.definitions import AGENTS, fact_check_mock
from app.agents.graph import build_graph
from app.agents.runner import execute_agent_run
from app.llm.base import LLMRequest, LLMResponse, ProviderConfig
from app.llm.router import ModelRouter, ModelTarget
from app.models import AgentStep
from tests.conftest import make_channel, make_project


async def test_full_pipeline_with_mock_provider(owner, queue, session_factory, db):
    ch = await make_channel(owner, tone="mysterious")
    p = await make_project(owner, ch["id"])
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"instructions": "Keep it under 30s"})
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    assert queue.jobs[-1][0] == "run_agents"
    # a second concurrent run is rejected
    assert (await owner.post(f"/projects/{p['id']}/agent-runs", json={})).status_code == 409

    status = await execute_agent_run(session_factory, uuid.UUID(run_id))
    assert status == "succeeded"
    detail = (await owner.get(f"/agent-runs/{run_id}")).json()
    assert detail["status"] == "succeeded"
    assert [s["agent_name"] for s in detail["steps"]] == [
        "research",
        "strategy",
        "script",
        "fact_check",
        "storyboard",
        "optimization",
    ]
    assert all(s["provider"] == "mock" and s["prompt_tokens"] > 0 for s in detail["steps"])
    assert detail["prompt_tokens"] == sum(s["prompt_tokens"] for s in detail["steps"])
    proj = (await owner.get(f"/projects/{p['id']}")).json()
    assert proj["status"] == "scripted"
    assert proj["storyboard"]["scenes"] and proj["optimization"]["titles"]
    assert "atlantis" in proj["script"]["full_narration"].lower()

    dash = (await owner.get("/dashboard")).json()
    assert dash["usage"]["tokens_30d"] > 0 and dash["counts"]["projects"] == 1


async def test_subset_requires_prerequisites(owner, session_factory):
    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"])
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"agents": ["storyboard"]})
    assert r.status_code == 422 and "script" in str(r.json()["error"]["details"])
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"agents": ["research", "strategy"]})
    assert r.status_code == 202
    assert await execute_agent_run(session_factory, uuid.UUID(r.json()["id"])) == "succeeded"
    proj = (await owner.get(f"/projects/{p['id']}")).json()
    assert proj["strategy"] and not proj["script"]
    # now script-only works because prerequisites exist on the project
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"agents": ["script"]})
    assert r.status_code == 202


class RevisingProvider:
    """Fact checker says 'revise' on first call, 'pass' afterwards; other agents use mocks."""

    def __init__(self):
        self.fact_checks = 0

    async def complete(self, req: LLMRequest) -> LLMResponse:
        import json

        payload = req.mock_response
        if "fact checker" in req.messages[0].content:
            self.fact_checks += 1
            if self.fact_checks == 1:
                payload = {
                    **payload,
                    "verdict": "revise",
                    "required_changes": ["Remove unverifiable claim"],
                    "claims": [{"claim": "x", "status": "false", "note": "wrong"}],
                }
        return LLMResponse(
            text=json.dumps(payload), provider="mock", model=req.model, prompt_tokens=5, completion_tokens=5
        )


async def test_fact_check_revision_loop(owner, session_factory, db, monkeypatch):
    provider = RevisingProvider()
    monkeypatch.setattr("app.llm.router.build_provider", lambda cfg, client=None: provider)
    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"])
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={})
    router = ModelRouter({"*": ModelTarget("mock", "mock-1")}, {"mock": ProviderConfig("mock")})
    assert await execute_agent_run(session_factory, uuid.UUID(r.json()["id"]), router=router) == "succeeded"
    steps = (
        await db.scalars(
            select(AgentStep).where(AgentStep.run_id == uuid.UUID(r.json()["id"])).order_by(AgentStep.created_at)
        )
    ).all()
    names = [s.agent_name for s in steps]
    assert names.count("script") == 2 and names.count("fact_check") == 2
    detail = (await owner.get(f"/agent-runs/{r.json()['id']}")).json()
    assert detail["output"]["revisions"] == 1


async def test_failed_run_is_recorded(owner, session_factory):
    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"])
    # route to a provider without credentials -> every attempt fails
    await owner.put("/api-config/routes/*", json={"provider": "openai", "model": "gpt-4.1"})
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"agents": ["research"]})
    assert await execute_agent_run(session_factory, uuid.UUID(r.json()["id"])) == "failed"
    detail = (await owner.get(f"/agent-runs/{r.json()['id']}")).json()
    assert "No active API credential" in detail["error"]
    assert detail["steps"][0]["status"] == "failed"


async def test_token_budget_enforced(owner, session_factory):
    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"])
    await owner.patch("/organizations/current", json={"monthly_token_budget": 1})
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"agents": ["research"]})
    await execute_agent_run(session_factory, uuid.UUID(r.json()["id"]))  # consumes > 1 token
    r = await owner.post(f"/projects/{p['id']}/agent-runs", json={"agents": ["research"]})
    assert await execute_agent_run(session_factory, uuid.UUID(r.json()["id"])) == "failed"
    assert "budget" in (await owner.get(f"/agent-runs/{r.json()['id']}")).json()["error"]


async def test_graph_respects_max_revisions():
    calls: list[str] = []

    async def node(name, state):
        calls.append(name)
        if name == "fact_check":
            return {**fact_check_mock(state), "verdict": "revise"}
        return AGENTS[name].mock(state)

    graph = build_graph(node, ["script", "fact_check"], max_revisions=2)
    state = {
        "project": {"title": "t", "topic": "t", "target_duration_sec": 30},
        "channel": {},
        "research": {"keywords": []},
        "strategy": {},
    }
    final = await graph.ainvoke(state)
    assert calls == ["script", "fact_check"] * 3
    assert final["revisions"] == 2
