"""YouTube Data API v3 + YouTube Analytics API v2 via Google OAuth 2.0."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import anyio
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

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CHUNK = 8 * 1024 * 1024  # must be a multiple of 256 KiB


class YouTubeClient:
    platform = "youtube"

    def __init__(self, http: httpx.AsyncClient | None = None):
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(60, read=300))

    @staticmethod
    def redirect_uri() -> str:
        return f"{settings.oauth_redirect_base}/youtube/callback"

    def authorization_url(self, state: str) -> str:
        if not settings.google_client_id:
            raise PlatformError("Google OAuth is not configured (GOOGLE_CLIENT_ID)", retryable=False)
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _token_request(self, data: dict[str, str]) -> OAuthTokens:
        resp = await self.http.post(
            TOKEN_URL,
            data={"client_id": settings.google_client_id, "client_secret": settings.google_client_secret, **data},
        )
        if resp.status_code >= 400:
            err = classify_http_error(resp, "google")
            if resp.status_code == 400 and "invalid_grant" in resp.text:
                err.auth_error, err.retryable = True, False
            raise err
        body = resp.json()
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token") or data.get("refresh_token"),
            expires_at=datetime.now(UTC) + timedelta(seconds=int(body.get("expires_in", 3600))),
            scopes=body.get("scope", "").split(),
        )

    async def exchange_code(self, code: str) -> list[ConnectedAccount]:
        tokens = await self._token_request(
            {"code": code, "grant_type": "authorization_code", "redirect_uri": self.redirect_uri()}
        )
        resp = await self.http.get(
            f"{API}/channels",
            params={"part": "snippet,statistics", "mine": "true"},
            headers=self._auth(tokens.access_token),
        )
        if resp.status_code >= 400:
            raise classify_http_error(resp, "youtube")
        items = resp.json().get("items", [])
        if not items:
            raise PlatformError("This Google account has no YouTube channel", retryable=False)
        return [
            ConnectedAccount(
                external_id=it["id"],
                display_name=it["snippet"]["title"],
                avatar_url=it["snippet"].get("thumbnails", {}).get("default", {}).get("url"),
                tokens=tokens,
                meta={"subscriber_count": it.get("statistics", {}).get("subscriberCount")},
            )
            for it in items
        ]

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        return await self._token_request({"refresh_token": refresh_token, "grant_type": "refresh_token"})

    async def revoke(self, token: str) -> None:
        await self.http.post(REVOKE_URL, params={"token": token})

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------ upload (resumable protocol)

    async def _start_session(self, token: str, req: PublishRequest, size: int) -> str:
        body = {
            "snippet": {
                "title": req.title[:100],
                "description": req.description[:5000],
                "tags": req.tags[:30],
                "categoryId": "22",
            },
            "status": {"privacyStatus": req.privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
        }
        resp = await self.http.post(
            f"{UPLOAD_API}/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={**self._auth(token), "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
            json=body,
        )
        if resp.status_code >= 400:
            raise classify_http_error(resp, "youtube")
        location = resp.headers.get("Location")
        if not location:
            raise PlatformError("YouTube did not return an upload session URL")
        return location

    async def _query_offset(self, token: str, session: str, size: int) -> int | dict[str, Any]:
        resp = await self.http.put(
            session, headers={**self._auth(token), "Content-Range": f"bytes */{size}", "Content-Length": "0"}
        )
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 308:
            rng = resp.headers.get("Range")
            return int(rng.split("-")[1]) + 1 if rng else 0
        if resp.status_code == 404:
            return -1  # session expired -> restart
        raise classify_http_error(resp, "youtube")

    async def publish(self, token: str, req: PublishRequest, on_progress: ProgressFn | None = None) -> PublishResult:
        size = os.path.getsize(req.video_path)
        session = req.state.get("upload_session")
        offset = 0
        if session:
            status = await self._query_offset(token, session, size)
            if isinstance(status, dict):
                return await self._finish(token, status, req)
            if status < 0:
                session = None
            else:
                offset = status
        if not session:
            session = await self._start_session(token, req, size)
            req.state["upload_session"] = session
            offset = 0
        async with await anyio.open_file(req.video_path, "rb") as fh:
            while offset < size:
                await fh.seek(offset)
                chunk = await fh.read(CHUNK)
                end = offset + len(chunk) - 1
                try:
                    resp = await self.http.put(
                        session,
                        content=chunk,
                        headers={
                            **self._auth(token),
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{size}",
                        },
                    )
                except httpx.TransportError as exc:
                    raise PlatformError(f"Upload interrupted: {exc}", retryable=True) from exc
                if resp.status_code == 308:
                    rng = resp.headers.get("Range")
                    offset = int(rng.split("-")[1]) + 1 if rng else 0
                elif resp.status_code in (200, 201):
                    if on_progress:
                        await on_progress(1.0)
                    return await self._finish(token, resp.json(), req)
                else:
                    raise classify_http_error(resp, "youtube")
                if on_progress:
                    await on_progress(offset / size)
        status = await self._query_offset(token, session, size)
        if isinstance(status, dict):
            return await self._finish(token, status, req)
        raise PlatformError("Upload finished without a video resource", retryable=True)

    async def _finish(self, token: str, video: dict[str, Any], req: PublishRequest) -> PublishResult:
        vid = video["id"]
        if req.thumbnail_path and os.path.exists(req.thumbnail_path):
            image = await anyio.Path(req.thumbnail_path).read_bytes()
            resp = await self.http.post(
                f"{UPLOAD_API}/thumbnails/set",
                params={"videoId": vid},
                headers={**self._auth(token), "Content-Type": "image/jpeg"},
                content=image,
            )
            # Custom thumbnails require a verified channel; failure must not fail the publish.
            req.state["thumbnail_status"] = resp.status_code
        req.state.pop("upload_session", None)
        return PublishResult(external_id=vid, url=f"https://www.youtube.com/watch?v={vid}", state=req.state)

    # ------------------------------------------------------------------ analytics

    async def fetch_metrics(self, token: str, video_id: str, published_at: datetime | None) -> Metrics:
        resp = await self.http.get(
            f"{API}/videos", params={"part": "statistics", "id": video_id}, headers=self._auth(token)
        )
        if resp.status_code >= 400:
            raise classify_http_error(resp, "youtube")
        items = resp.json().get("items", [])
        stats = items[0]["statistics"] if items else {}
        m = Metrics(
            views=int(stats.get("viewCount", 0)),
            likes=int(stats.get("likeCount", 0)),
            comments=int(stats.get("commentCount", 0)),
            raw={"statistics": stats},
        )
        start = (published_at or datetime.now(UTC) - timedelta(days=28)).date().isoformat()
        resp = await self.http.get(
            ANALYTICS_API,
            params={
                "ids": "channel==MINE",
                "startDate": start,
                "endDate": datetime.now(UTC).date().isoformat(),
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,shares",
                "filters": f"video=={video_id}",
            },
            headers=self._auth(token),
        )
        if resp.status_code < 400:
            rows = resp.json().get("rows") or []
            if rows:
                _, minutes, avg, shares = rows[0][:4]
                m.watch_time_minutes, m.avg_view_duration_sec, m.shares = float(minutes), float(avg), int(shares)
                m.raw["analytics"] = rows[0]
        return m
