"""Executes an AgentRun: builds the LangGraph, logs every LLM attempt, persists outputs and token usage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.definitions import AGENT_ORDER, AGENTS, PipelineState
from app.agents.graph import build_graph, missing_prerequisites
from app.core.logging import get_logger
from app.llm.router import AttemptRecord, ModelRouter
from app.models import AgentRun, AgentStep, Channel, Organization, Project
from app.models.enums import ProjectStatus, RunStatus

log = get_logger(__name__)


class TokenBudgetExceededError(Exception):
    pass


class RunCancelledError(Exception):
    pass


def project_state(project: Project, channel: Channel, instructions: str = "") -> PipelineState:
    state: PipelineState = {
        "project": {
            "title": project.title,
            "topic": project.topic,
            "format": project.format,
            "target_duration_sec": project.target_duration_sec,
            "brief": project.brief or {},
        },
        "channel": {
            "name": channel.name,
            "niche": channel.niche,
            "tone": channel.tone,
            "language": channel.language,
            "target_audience": channel.target_audience,
            "branding": channel.branding or {},
        },
        "instructions": instructions,
        "revisions": 0,
        "completed": [],
    }
    for name in AGENT_ORDER:
        value = getattr(project, name)
        if value:
            state[name] = value  # type: ignore[literal-required]
    return state


async def tokens_used_this_month(db: AsyncSession, org_id: uuid.UUID) -> int:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = await db.scalar(
        select(func.coalesce(func.sum(AgentStep.prompt_tokens + AgentStep.completion_tokens), 0)).where(
            AgentStep.organization_id == org_id, AgentStep.created_at >= start
        )
    )
    return int(total or 0)


async def execute_agent_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    router: ModelRouter | None = None,
) -> RunStatus:
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        if run is None:
            log.error("agent_run_missing", extra={"run_id": str(run_id)})
            return RunStatus.FAILED
        if run.status in (RunStatus.SUCCEEDED, RunStatus.CANCELLED):
            return RunStatus(run.status)
        project = await db.get(Project, run.project_id)
        org = await db.get(Organization, run.organization_id)
        assert project is not None and org is not None
        channel = await db.get(Channel, project.channel_id)
        assert channel is not None
        project_id = project.id

        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        run.error = None
        project.status = ProjectStatus.GENERATING
        await db.commit()

        try:
            if org.monthly_token_budget and await tokens_used_this_month(db, org.id) >= org.monthly_token_budget:
                raise TokenBudgetExceededError("Monthly token budget exhausted for this organization")

            state = project_state(project, channel, run.input.get("instructions", ""))
            agents = list(run.agents or [])
            missing = missing_prerequisites(state, agents)
            if missing:
                raise ValueError(f"Missing prerequisite outputs: {missing}. Run those agents first.")

            router = router or await ModelRouter.for_organization(db, org.id)

            async def on_attempt(rec: AttemptRecord) -> None:
                db.add(
                    AgentStep(
                        run_id=run.id,
                        organization_id=org.id,
                        agent_name=rec.agent_name,
                        attempt=rec.attempt,
                        status=rec.status,
                        provider=rec.provider,
                        model=rec.model,
                        prompt_tokens=rec.prompt_tokens,
                        completion_tokens=rec.completion_tokens,
                        cost_usd=rec.cost_usd,
                        latency_ms=rec.latency_ms,
                        error=rec.error,
                        output=rec.output,
                    )
                )
                run.prompt_tokens += rec.prompt_tokens
                run.completion_tokens += rec.completion_tokens
                run.cost_usd = round(run.cost_usd + rec.cost_usd, 6)
                await db.commit()

            async def run_node(name: str, st: PipelineState) -> dict[str, Any]:
                async with session_factory() as check:
                    if await check.scalar(select(AgentRun.status).where(AgentRun.id == run.id)) == RunStatus.CANCELLED:
                        raise RunCancelledError("Run cancelled by user")
                spec = AGENTS[name]
                log.info("agent_started", extra={"run_id": str(run.id), "agent": name})
                result = await router.generate_structured(
                    agent_name=name,
                    system=spec.system_prompt,
                    user=spec.build_prompt(st),
                    output_model=spec.output_model,
                    on_attempt=on_attempt,
                    mock_response=spec.mock(st),
                )
                output = result.data.model_dump(mode="json")
                setattr(project, name, output)  # persist incrementally so partial progress survives failures
                await db.commit()
                return output

            graph = build_graph(run_node, agents)
            final: dict[str, Any] = await graph.ainvoke(state, {"recursion_limit": 50})

            run.output = {k: final.get(k) for k in AGENT_ORDER if final.get(k)} | {
                "revisions": final.get("revisions", 0),
                "completed": final.get("completed", []),
            }
            run.status = RunStatus.SUCCEEDED
            if project.script:
                project.status = ProjectStatus.SCRIPTED
            else:
                project.status = ProjectStatus.DRAFT
        except Exception as exc:  # noqa: BLE001 - we persist any failure on the run
            log.exception("agent_run_failed", extra={"run_id": str(run_id)})
            await db.rollback()
            run = await db.get(AgentRun, run_id)
            project = await db.get(Project, project_id)
            assert run is not None and project is not None
            run.status = RunStatus.CANCELLED if isinstance(exc, RunCancelledError) else RunStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"[:4000]
            project.status = ProjectStatus.SCRIPTED if project.script else ProjectStatus.DRAFT
        run.finished_at = datetime.now(UTC)
        await db.commit()
        log.info(
            "agent_run_finished",
            extra={"run_id": str(run_id), "status": run.status, "tokens": run.prompt_tokens + run.completion_tokens},
        )
        return RunStatus(run.status)
