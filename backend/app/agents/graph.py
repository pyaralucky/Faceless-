"""LangGraph orchestration of the specialised agents.

    research -> strategy -> script -> fact_check --(revise & budget left)--> script
                                                 \\--(pass)--> storyboard -> optimization -> END

Only the requested agents are added to the graph; prerequisites must already exist in the state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.definitions import AGENT_ORDER, AGENTS, PipelineState
from app.core.config import settings

NodeRunner = Callable[[str, PipelineState], Awaitable[dict[str, Any]]]


def build_graph(run_node: NodeRunner, agents: list[str] | None = None, max_revisions: int | None = None):
    selected = [a for a in AGENT_ORDER if not agents or a in agents]
    if not selected:
        raise ValueError("No agents selected")
    max_rev = settings.agent_max_revisions if max_revisions is None else max_revisions

    graph = StateGraph(PipelineState)

    def make_node(name: str):
        async def node(state: PipelineState) -> dict[str, Any]:
            output = await run_node(name, state)
            update: dict[str, Any] = {name: output, "completed": [*state.get("completed", []), name]}
            if name == "script" and state.get("fact_check", {}).get("verdict") == "revise":
                update["revisions"] = state.get("revisions", 0) + 1
            return update

        node.__name__ = f"{name}_node"
        return node

    for name in selected:
        graph.add_node(name, make_node(name))

    graph.add_edge(START, selected[0])
    for current, nxt in zip(selected, [*selected[1:], None], strict=True):
        target = nxt or END
        if current == "fact_check" and "script" in selected:

            def route(state: PipelineState, _target: str = target) -> str:
                verdict = state.get("fact_check", {}).get("verdict")
                if verdict == "revise" and state.get("revisions", 0) < max_rev:
                    return "script"
                return _target

            graph.add_conditional_edges("fact_check", route, {"script": "script", target: target})
        else:
            graph.add_edge(current, target)
    return graph.compile()


def missing_prerequisites(state: PipelineState, agents: list[str]) -> dict[str, list[str]]:
    selected = set(agents or AGENT_ORDER)
    missing: dict[str, list[str]] = {}
    for name in selected:
        lacking = [r for r in AGENTS[name].requires if r not in selected and not state.get(r)]
        if lacking:
            missing[name] = lacking
    return missing
