"""OAuth connections for YouTube and Instagram professional accounts (official APIs only)."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Admin, Editor, OrgContext, Viewer
from app.core.config import settings
from app.core.errors import AppError, ValidationFailedError
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import get_db
from app.integrations.base import PlatformError
from app.models import Channel, PublishJob, SocialAccount
from app.models.enums import Platform, PublishStatus, SocialAccountStatus
from app.schemas.common import Message
from app.schemas.social import OAuthStartOut, SocialAccountOut, SocialAccountUpdate
from app.services import social as social_service
from app.services.audit import record_audit
from app.services.scoping import get_scoped

router = APIRouter(prefix="/social", tags=["social accounts"])
log = get_logger(__name__)


@router.get("/accounts", response_model=list[SocialAccountOut])
async def list_accounts(ctx: OrgContext = Viewer, db: AsyncSession = Depends(get_db)) -> list[SocialAccount]:
    return list(
        (
            await db.scalars(
                select(SocialAccount)
                .where(SocialAccount.organization_id == ctx.org_id)
                .order_by(SocialAccount.platform)
            )
        ).all()
    )


@router.get("/{platform}/authorize", response_model=OAuthStartOut)
async def authorize(
    platform: Platform,
    channel_id: uuid.UUID | None = None,
    ctx: OrgContext = Editor,
    db: AsyncSession = Depends(get_db),
) -> OAuthStartOut:
    if channel_id:
        await get_scoped(db, Channel, channel_id, ctx.org_id)
    state = social_service.make_state(ctx.org_id, ctx.user.id, platform, channel_id)
    try:
        url = social_service.get_client(platform).authorization_url(state)
    except PlatformError as exc:
        raise ValidationFailedError(str(exc), code="oauth_not_configured") from exc
    return OAuthStartOut(authorization_url=url)


@router.get("/oauth/{platform}/callback", include_in_schema=False)
async def oauth_callback(
    platform: Platform,
    code: str | None = None,
    state: str | None = None,
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Browser redirect target registered with Google/Meta. Authenticated via the signed `state`."""
    dest = f"{settings.frontend_url.rstrip('/')}/accounts"
    if error or not code or not state:
        return RedirectResponse(f"{dest}?{urlencode({'error': error or 'missing_code', 'platform': platform})}")
    try:
        payload = social_service.read_state(state, platform)
        accounts = await social_service.get_client(platform).exchange_code(code)
        saved = await social_service.store_accounts(
            db,
            uuid.UUID(payload["org"]),
            uuid.UUID(payload["usr"]),
            platform,
            uuid.UUID(payload["ch"]) if payload.get("ch") else None,
            accounts,
        )
    except (PlatformError, AppError) as exc:
        log.warning("oauth_callback_failed", extra={"platform": platform, "error": str(exc)[:300]})
        return RedirectResponse(f"{dest}?{urlencode({'error': str(exc)[:200], 'platform': platform})}")
    return RedirectResponse(f"{dest}?{urlencode({'connected': platform, 'count': len(saved)})}")


@router.patch("/accounts/{account_id}", response_model=SocialAccountOut)
async def update_account(
    account_id: uuid.UUID, data: SocialAccountUpdate, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> SocialAccount:
    acc = await get_scoped(db, SocialAccount, account_id, ctx.org_id, label="Social account")
    if data.channel_id:
        await get_scoped(db, Channel, data.channel_id, ctx.org_id)
    acc.channel_id = data.channel_id
    await db.commit()
    await db.refresh(acc)
    return acc


@router.post("/accounts/{account_id}/refresh", response_model=SocialAccountOut)
async def refresh_account(
    account_id: uuid.UUID, ctx: OrgContext = Editor, db: AsyncSession = Depends(get_db)
) -> SocialAccount:
    acc = await get_scoped(db, SocialAccount, account_id, ctx.org_id, label="Social account")
    try:
        await social_service.get_access_token(db, acc)
    except PlatformError as exc:
        raise ValidationFailedError(str(exc), code="token_refresh_failed") from exc
    await db.refresh(acc)
    return acc


@router.delete("/accounts/{account_id}", response_model=Message)
async def disconnect(account_id: uuid.UUID, ctx: OrgContext = Admin, db: AsyncSession = Depends(get_db)) -> Message:
    acc = await get_scoped(db, SocialAccount, account_id, ctx.org_id, label="Social account")
    if acc.platform == Platform.YOUTUBE:
        try:  # best effort token revocation at Google
            await social_service.get_client(acc.platform).revoke(
                decrypt_secret(acc.encrypted_refresh_token or acc.encrypted_access_token)
            )
        except Exception:  # noqa: BLE001
            log.warning("token_revoke_failed", extra={"account_id": str(acc.id)})
    # Soft-revoke: wipe credentials but keep the row so publish history and analytics survive.
    # Reconnecting the same platform account through OAuth reactivates it.
    acc.status = SocialAccountStatus.REVOKED
    acc.encrypted_access_token = encrypt_secret("")
    acc.encrypted_refresh_token = None
    acc.token_expires_at = None
    await db.execute(
        update(PublishJob)
        .where(
            PublishJob.social_account_id == acc.id,
            PublishJob.status.in_([PublishStatus.SCHEDULED, PublishStatus.PENDING_APPROVAL]),
        )
        .values(status=PublishStatus.CANCELLED, next_attempt_at=None, last_error="Social account disconnected")
    )
    record_audit(
        db,
        action="social.disconnected",
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        entity_type="social_account",
        entity_id=acc.id,
    )
    await db.commit()
    return Message(message="Account disconnected")
