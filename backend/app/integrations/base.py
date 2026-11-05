"""Shared types for official platform API integrations.

All integrations use the platforms' documented OAuth 2.0 flows and public REST APIs only.
No browser automation, scraping or credential sharing is used or supported.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

ProgressFn = Callable[[float], Awaitable[None]]


class PlatformError(Exception):
    def __init__(
        self, message: str, *, retryable: bool = True, auth_error: bool = False, status_code: int | None = None
    ):
        super().__init__(message)
        self.retryable = retryable
        self.auth_error = auth_error
        self.status_code = status_code


@dataclass(slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConnectedAccount:
    external_id: str
    display_name: str
    avatar_url: str | None
    tokens: OAuthTokens
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublishRequest:
    video_path: str
    thumbnail_path: str | None
    title: str
    description: str
    tags: list[str]
    privacy: str
    public_video_url: str | None = None  # Instagram fetches media from a public URL
    public_thumbnail_url: str | None = None
    state: dict[str, Any] = field(default_factory=dict)  # resumable platform state


@dataclass(slots=True)
class PublishResult:
    external_id: str
    url: str | None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Metrics:
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    impressions: int = 0
    reach: int = 0
    watch_time_minutes: float = 0.0
    avg_view_duration_sec: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


def classify_http_error(resp: httpx.Response, platform: str) -> PlatformError:
    status = resp.status_code
    body = resp.text[:600]
    auth = status in (401, 403) and ("auth" in body.lower() or "token" in body.lower() or status == 401)
    retryable = status in (408, 429) or status >= 500
    return PlatformError(f"{platform} API {status}: {body}", retryable=retryable, auth_error=auth, status_code=status)
