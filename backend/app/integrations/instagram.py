"""Instagram Graph API (professional accounts) via Facebook Login for Business.

Publishing uses the official Content Publishing API (media container -> media_publish) for Reels.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.integrations.base import (
    ConnectedAccount,
    Metrics,
    OAuthTokens,
    PlatformError,
    ProgressFn,
    PublishRequest,
    PublishResult,
    classify_http_error,
)

SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
]


class InstagramClient:
    platform = "instagram"

    def __init__(self, http: httpx.AsyncClient | None = None, poll_interval: float = 5.0, max_polls: int = 120):
        self.http = http or httpx.AsyncClient(timeout=60)
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    @property
    def graph(self) -> str:
        return f"https://graph.facebook.com/{settings.meta_graph_version}"

    @staticmethod
    def redirect_uri() -> str:
        return f"{settings.oauth_redirect_base}/instagram/callback"

    def authorization_url(self, state: str) -> str:
        if not settings.meta_app_id:
            raise PlatformError("Meta OAuth is not configured (META_APP_ID)", retryable=False)
        params = {
            "client_id": settings.meta_app_id,
            "redirect_uri": self.redirect_uri(),
            "state": state,
            "response_type": "code",
            "scope": ",".join(SCOPES),
        }
        return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{urlencode(params)}"

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self.http.get(f"{self.graph}/{path.lstrip('/')}", params=params)
        if resp.status_code >= 400:
            raise self._error(resp)
        return resp.json()

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        resp = await self.http.post(f"{self.graph}/{path.lstrip('/')}", data=data)
        if resp.status_code >= 400:
            raise self._error(resp)
        return resp.json()

    @staticmethod
    def _error(resp: httpx.Response) -> PlatformError:
        err = classify_http_error(resp, "instagram")
        try:
            e = resp.json().get("error", {})
        except ValueError:
            return err
        if e.get("code") in (190, 102) or e.get("type") == "OAuthException" and e.get("code") != 4:
            err.auth_error, err.retryable = True, False
        if e.get("code") in (4, 17, 32, 613) or e.get("is_transient"):
            err.retryable = True
        return err

    async def _long_lived(self, short_token: str) -> OAuthTokens:
        body = await self._get(
            "oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        )
        expires = body.get("expires_in")
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=None,
            expires_at=datetime.now(UTC) + timedelta(seconds=int(expires)) if expires else None,
            scopes=SCOPES,
        )

    async def exchange_code(self, code: str) -> list[ConnectedAccount]:
        short = await self._get(
            "oauth/access_token",
            {
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": self.redirect_uri(),
                "code": code,
            },
        )
        user_tokens = await self._long_lived(short["access_token"])
        pages = await self._get(
            "me/accounts",
            {
                "fields": "id,name,access_token,instagram_business_account{id,username,profile_picture_url}",
                "access_token": user_tokens.access_token,
            },
        )
        accounts = []
        for page in pages.get("data", []):
            ig = page.get("instagram_business_account")
            if not ig:
                continue
            # Page tokens obtained from a long-lived user token do not expire; keep user token for refresh.
            accounts.append(
                ConnectedAccount(
                    external_id=ig["id"],
                    display_name=ig.get("username") or page["name"],
                    avatar_url=ig.get("profile_picture_url"),
                    tokens=OAuthTokens(
                        access_token=page["access_token"],
                        refresh_token=user_tokens.access_token,
                        expires_at=user_tokens.expires_at,
                        scopes=SCOPES,
                    ),
                    meta={"page_id": page["id"], "page_name": page["name"]},
                )
            )
        if not accounts:
            raise PlatformError(
                "No Instagram professional account is linked to the Facebook Pages you granted. "
                "Convert the Instagram account to Business/Creator and link it to a Page.",
                retryable=False,
            )
        return accounts

    async def refresh(self, user_token: str) -> OAuthTokens:
        """Re-extend the long-lived user token (call before it expires)."""
        return await self._long_lived(user_token)

    async def publish(
        self, token: str, account_id: str, req: PublishRequest, on_progress: ProgressFn | None = None
    ) -> PublishResult:
        if not req.public_video_url:
            raise PlatformError(
                "Instagram requires a publicly reachable video URL (configure MEDIA_PUBLIC_BASE_URL)", retryable=False
            )
        container = req.state.get("container_id")
        if not container:
            caption = req.description
            if req.tags:
                caption = f"{caption}\n\n" + " ".join(
                    t if t.startswith("#") else f"#{t.replace(' ', '')}" for t in req.tags[:25]
                )
            data = {
                "media_type": "REELS",
                "video_url": req.public_video_url,
                "caption": caption[:2200],
                "share_to_feed": "true",
                "access_token": token,
            }
            if req.public_thumbnail_url:
                data["cover_url"] = req.public_thumbnail_url
            container = (await self._post(f"{account_id}/media", data))["id"]
            req.state["container_id"] = container
        for i in range(self.max_polls):
            status = await self._get(container, {"fields": "status_code,status", "access_token": token})
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                req.state.pop("container_id", None)
                raise PlatformError(
                    f"Instagram media processing {code}: {status.get('status')}", retryable=code == "EXPIRED"
                )
            if on_progress:
                await on_progress(min(0.95, (i + 1) / self.max_polls))
            await asyncio.sleep(self.poll_interval)
        else:
            raise PlatformError("Instagram media processing timed out", retryable=True)
        media_id = (await self._post(f"{account_id}/media_publish", {"creation_id": container, "access_token": token}))[
            "id"
        ]
        info = await self._get(media_id, {"fields": "permalink", "access_token": token})
        req.state.pop("container_id", None)
        if on_progress:
            await on_progress(1.0)
        return PublishResult(external_id=media_id, url=info.get("permalink"), state=req.state)

    async def fetch_metrics(self, token: str, media_id: str) -> Metrics:
        base = await self._get(media_id, {"fields": "like_count,comments_count", "access_token": token})
        m = Metrics(
            likes=int(base.get("like_count", 0)), comments=int(base.get("comments_count", 0)), raw={"fields": base}
        )
        try:
            ins = await self._get(
                f"{media_id}/insights",
                {
                    "metric": "views,reach,saved,shares,ig_reels_avg_watch_time,ig_reels_video_view_total_time",
                    "access_token": token,
                },
            )
        except PlatformError as exc:
            m.raw["insights_error"] = str(exc)[:300]
            return m
        values = {d["name"]: (d.get("values") or [{}])[0].get("value", 0) for d in ins.get("data", [])}
        m.views = int(values.get("views", 0))
        m.reach = int(values.get("reach", 0))
        m.saves = int(values.get("saved", 0))
        m.shares = int(values.get("shares", 0))
        m.avg_view_duration_sec = float(values.get("ig_reels_avg_watch_time", 0)) / 1000
        m.watch_time_minutes = float(values.get("ig_reels_video_view_total_time", 0)) / 60000
        m.raw["insights"] = values
        return m
