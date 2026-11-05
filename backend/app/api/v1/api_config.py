"""API configuration: encrypted provider credentials and per-agent model routing."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.definitions import AGENT_ORDER
from app.api.deps import Admin, OrgContext, Viewer
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.session import get_db
from app.llm.base import LLMMessage, LLMProviderError, LLMRequest, ProviderConfig
from app.llm.providers import build_provider
from app.models import ModelRoute, ProviderCredential
from app.models.enums import LLMProvider
from app.schemas.common import Message
from app.schemas.content import CredentialCreate, CredentialOut, CredentialUpdate, ModelRouteOut, ModelRouteUpsert
from app.services.audit import record_audit
from app.services.scoping import get_scoped

router = APIRouter(prefix="/api-config", tags=["api configuration"])

SUGGESTED_MODELS = {
    "openai": ["gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"],
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
    "google": ["gemini-2.5-pro", "gemini-2.5-flash"],
    "openrouter": ["openrouter/auto"],
    "azure_openai": [],
    "ollama": ["llama3.1", "qwen2.5"],
    "mock": ["mock-1"],
}


@router.get("/catalog")
async def catalog(_: OrgContext = Viewer) -> dict:
    return {"providers": [p.value for p in LLMProvider], "agents": AGENT_ORDER, "suggested_models": SUGGESTED_MODELS}


@router.get("/credentials", response_model=list[CredentialOut])
async def list_credentials(ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)) -> list[ProviderCredential]:
    return list(
        (
            await db.scalars(
                select(ProviderCredential)
                .where(ProviderCredential.organization_id == ctx.org_id)
                .order_by(ProviderCredential.provider)
            )
        ).all()
    )


@router.post("/credentials", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(
    data: CredentialCreate, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> ProviderCredential:
    exists = await db.scalar(
        select(ProviderCredential.id).where(
            ProviderCredential.organization_id == ctx.org_id,
            ProviderCredential.provider == data.provider,
            ProviderCredential.label == data.label,
        )
    )
    if exists:
        raise ConflictError("A credential with this provider and label already exists")
    cred = ProviderCredential(
        organization_id=ctx.org_id,
        provider=data.provider,
        label=data.label,
        encrypted_api_key=encrypt_secret(data.api_key),
        key_hint=mask_secret(data.api_key),
        base_url=str(data.base_url) if data.base_url else None,
        config=data.config,
    )
    db.add(cred)
    await db.flush()
    record_audit(
        db,
        action="credential.created",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="credential",
        entity_id=cred.id,
        data={"provider": data.provider},
    )
    await db.commit()
    await db.refresh(cred)
    return cred


@router.patch("/credentials/{cred_id}", response_model=CredentialOut)
async def update_credential(
    cred_id: uuid.UUID, data: CredentialUpdate, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> ProviderCredential:
    cred = await get_scoped(db, ProviderCredential, cred_id, ctx.org_id, label="Credential")
    changes = data.model_dump(exclude_unset=True)
    if "api_key" in changes:
        key = changes.pop("api_key")
        cred.encrypted_api_key, cred.key_hint = encrypt_secret(key), mask_secret(key)
    if "base_url" in changes:
        cred.base_url = str(changes.pop("base_url")) if data.base_url else None
    for k, v in changes.items():
        setattr(cred, k, v)
    record_audit(
        db,
        action="credential.updated",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="credential",
        entity_id=cred.id,
        data={"fields": list(data.model_dump(exclude_unset=True))},
    )
    await db.commit()
    await db.refresh(cred)
    return cred


@router.delete("/credentials/{cred_id}", response_model=Message)
async def delete_credential(cred_id: uuid.UUID, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)) -> Message:
    cred = await get_scoped(db, ProviderCredential, cred_id, ctx.org_id, label="Credential")
    await db.delete(cred)
    record_audit(
        db,
        action="credential.deleted",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="credential",
        entity_id=cred_id,
        data={"provider": cred.provider},
    )
    await db.commit()
    return Message(message="Credential deleted")


@router.post("/credentials/{cred_id}/test")
async def test_credential(
    cred_id: uuid.UUID, model: str | None = None, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> dict:
    cred = await get_scoped(db, ProviderCredential, cred_id, ctx.org_id, label="Credential")
    model = model or (SUGGESTED_MODELS.get(cred.provider) or [""])[0] or cred.config.get("default_model")
    if not model:
        raise ValidationFailedError("Pass ?model= to test this provider")
    provider = build_provider(
        ProviderConfig(cred.provider, decrypt_secret(cred.encrypted_api_key), cred.base_url, dict(cred.config))
    )
    try:
        resp = await provider.complete(
            LLMRequest(
                model=model,
                messages=[LLMMessage("user", "Reply with the single word: ok")],
                max_tokens=16,
                temperature=0,
            )
        )
    except LLMProviderError as exc:
        return {"ok": False, "error": str(exc)[:500]}
    return {
        "ok": True,
        "model": resp.model,
        "reply": resp.text[:100],
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
    }


# ------------------------------------------------------------------ model routes


@router.get("/routes", response_model=list[ModelRouteOut])
async def list_routes(ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> list[ModelRoute]:
    return list(
        (
            await db.scalars(
                select(ModelRoute).where(ModelRoute.organization_id == ctx.org_id).order_by(ModelRoute.agent_name)
            )
        ).all()
    )


@router.put("/routes/{agent_name}", response_model=ModelRouteOut)
async def upsert_route(
    agent_name: str, data: ModelRouteUpsert, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)
) -> ModelRoute:
    if agent_name != "*" and agent_name not in AGENT_ORDER:
        raise ValidationFailedError(f"Unknown agent '{agent_name}'. Use '*' or one of {AGENT_ORDER}")
    route = await db.scalar(
        select(ModelRoute).where(ModelRoute.organization_id == ctx.org_id, ModelRoute.agent_name == agent_name)
    )
    if route is None:
        route = ModelRoute(organization_id=ctx.org_id, agent_name=agent_name, provider=data.provider, model=data.model)
        db.add(route)
    route.provider, route.model = data.provider, data.model
    route.temperature, route.max_tokens = data.temperature, data.max_tokens
    route.fallbacks = [f.model_dump(mode="json") for f in data.fallbacks]
    record_audit(
        db,
        action="model_route.updated",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="model_route",
        entity_id=agent_name,
        data=data.model_dump(mode="json"),
    )
    await db.commit()
    await db.refresh(route)
    return route


@router.delete("/routes/{agent_name}", response_model=Message)
async def delete_route(agent_name: str, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)) -> Message:
    route = await db.scalar(
        select(ModelRoute).where(ModelRoute.organization_id == ctx.org_id, ModelRoute.agent_name == agent_name)
    )
    if route is None:
        raise NotFoundError("Route not found")
    await db.delete(route)
    await db.commit()
    return Message(message="Route deleted")
