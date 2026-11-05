"""Social account connection (OAuth), secure token storage and refresh."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.core.logging import get_logger
from app.core.security import create_signed_token, decode_token, decrypt_secret, encrypt_secret
from app.integrations.base import ConnectedAccount, PlatformError
from app.integrations.instagram import InstagramClient
from app.integrations.youtube import YouTubeClient
from app.models import SocialAccount
from app.models.enums import Platform, SocialAccountStatus
from app.services.audit import record_audit

log = get_logger(__name__)

_clients: dict[str, Any] = {}


def get_client(platform: str) -> Any:
    if platform not in _clients:
        if platform == Platform.YOUTUBE:
            _clients[platform] = YouTubeClient()
        elif platform == Platform.INSTAGRAM:
            _clients[platform] = InstagramClient()
        else:
            raise ValidationFailedError(f"Unsupported platform {platform}")
    return _clients[platform]


def set_client(platform: str, client: Any) -> None:
    """Test hook."""
    _clients[platform] = client


def make_state(org_id: uuid.UUID, user_id: uuid.UUID, platform: str, channel_id: uuid.UUID | None) -> str:
    return create_signed_token(
        "oauth_state",
        {"org": str(org_id), "usr": str(user_id), "plt": platform, "ch": str(channel_id) if channel_id else None},
        timedelta(minutes=15),
    )


def read_state(state: str, platform: str) -> dict[str, Any]:
    payload = decode_token(state, "oauth_state")
    if payload.get("plt") != platform:
        raise ValidationFailedError("OAuth state does not match platform")
    return payload


async def store_accounts(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    platform: str,
    channel_id: uuid.UUID | None,
    accounts: list[ConnectedAccount],
) -> list[SocialAccount]:
    saved = []
    for acc in accounts:
        row = await db.scalar(
            select(SocialAccount).where(
                SocialAccount.organization_id == org_id,
                SocialAccount.platform == platform,
                SocialAccount.external_id == acc.external_id,
            )
        )
        if row is None:
            row = SocialAccount(
                organization_id=org_id, platform=platform, external_id=acc.external_id, encrypted_access_token=""
            )
            db.add(row)
        row.display_name = acc.display_name
        row.avatar_url = acc.avatar_url
        row.encrypted_access_token = encrypt_secret(acc.tokens.access_token)
        if acc.tokens.refresh_token:
            row.encrypted_refresh_token = encrypt_secret(acc.tokens.refresh_token)
        row.token_expires_at = acc.tokens.expires_at
        row.scopes = acc.tokens.scopes
        row.status = SocialAccountStatus.ACTIVE
        row.meta = {**(row.meta or {}), **acc.meta}
        row.connected_by_id = user_id
        if channel_id:
            row.channel_id = channel_id
        saved.append(row)
    await db.flush()
    for row in saved:
        record_audit(
            db,
            action="social.connected",
            org_id=org_id,
            actor_id=user_id,
            entity_type="social_account",
            entity_id=row.id,
            data={"platform": platform, "name": row.display_name},
        )
    await db.commit()
    return saved


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


async def get_access_token(db: AsyncSession, account: SocialAccount) -> str:
    """Return a valid access token, refreshing it when it is close to expiry."""
    if account.status in (SocialAccountStatus.REVOKED,):
        raise PlatformError("Account access was revoked; reconnect it", retryable=False, auth_error=True)
    expires = _aware(account.token_expires_at)
    margin = timedelta(minutes=5) if account.platform == Platform.YOUTUBE else timedelta(days=7)
    if expires is None or expires - margin > datetime.now(UTC):
        return decrypt_secret(account.encrypted_access_token)
    if not account.encrypted_refresh_token:
        if expires > datetime.now(UTC):
            return decrypt_secret(account.encrypted_access_token)
        account.status = SocialAccountStatus.EXPIRED
        await db.commit()
        raise PlatformError(
            "Access token expired and no refresh token is available; reconnect the account",
            retryable=False,
            auth_error=True,
        )
    client = get_client(account.platform)
    try:
        tokens = await client.refresh(decrypt_secret(account.encrypted_refresh_token))
    except PlatformError as exc:
        if exc.auth_error:
            account.status = SocialAccountStatus.EXPIRED
            await db.commit()
        raise
    if account.platform == Platform.YOUTUBE:
        account.encrypted_access_token = encrypt_secret(tokens.access_token)
    else:
        # Instagram: page token stays valid; we only extend the long-lived user token used for refresh.
        account.encrypted_refresh_token = encrypt_secret(tokens.access_token)
    if tokens.refresh_token and account.platform == Platform.YOUTUBE:
        account.encrypted_refresh_token = encrypt_secret(tokens.refresh_token)
    account.token_expires_at = tokens.expires_at
    account.status = SocialAccountStatus.ACTIVE
    await db.commit()
    log.info("social_token_refreshed", extra={"account_id": str(account.id), "platform": account.platform})
    return decrypt_secret(account.encrypted_access_token)
