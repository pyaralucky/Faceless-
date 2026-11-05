"""Test fixtures. Uses SQLite by default; set TEST_DATABASE_URL to run against PostgreSQL."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="faceless-test-"))
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_TMP}/test.db"),
    STORAGE_ROOT=str(_TMP / "storage"),
    SECRET_KEY="test-secret-key-for-unit-tests-only-0123456789",
    LOG_JSON="false",
    LOG_LEVEL="WARNING",
    RENDER_PRESET="ultrafast",
    RENDER_CRF="32",
    LOGIN_RATE_LIMIT_PER_MINUTE="1000",
    PUBLIC_API_URL="https://api.example.test",
    FRONTEND_URL="https://app.example.test",
    GOOGLE_CLIENT_ID="google-client",
    GOOGLE_CLIENT_SECRET="google-secret",
    META_APP_ID="meta-app",
    META_APP_SECRET="meta-secret",
)

import fakeredis  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from app.core.redis import set_redis  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.services.queue import InMemoryQueue, set_queue  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with db_session.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await db_session.engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _fakes() -> InMemoryQueue:
    set_redis(fakeredis.FakeAsyncRedis(decode_responses=True))
    q = InMemoryQueue()
    set_queue(q)
    return q


@pytest.fixture
def queue(_fakes: InMemoryQueue) -> InMemoryQueue:
    return _fakes


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    return db_session.SessionLocal


@pytest.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class Account:
    def __init__(self, client: httpx.AsyncClient, email: str, token: str, refresh: str, org_id: str):
        self.client, self.email, self.token, self.refresh, self.org_id = client, email, token, refresh, org_id

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Org-Id": self.org_id}

    async def get(self, url: str, **kw):
        return await self.client.get(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    async def post(self, url: str, **kw):
        return await self.client.post(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    async def patch(self, url: str, **kw):
        return await self.client.patch(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    async def put(self, url: str, **kw):
        return await self.client.put(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    async def delete(self, url: str, **kw):
        return await self.client.delete(f"/api/v1{url}", headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def as_org(self, org_id: str) -> Account:
        return Account(self.client, self.email, self.token, self.refresh, org_id)


async def register(client: httpx.AsyncClient, email: str | None = None, org: str = "Acme Studio") -> Account:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Sup3r-secret-pw", "full_name": "Test User", "organization_name": org},
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    org_id = me.json()["memberships"][0]["organization_id"]
    return Account(client, email, tokens["access_token"], tokens["refresh_token"], org_id)


@pytest.fixture
async def owner(client) -> Account:
    return await register(client)


async def add_member(owner: Account, role: str) -> Account:
    member = await register(owner.client)
    r = await owner.post("/organizations/current/members", json={"email": member.email, "role": role})
    assert r.status_code == 201, r.text
    return member.as_org(owner.org_id)


async def make_channel(acc: Account, **overrides) -> dict:
    payload = {"name": f"Channel {uuid.uuid4().hex[:6]}", "niche": "history", "require_approval": False, **overrides}
    r = await acc.post("/channels", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def make_project(acc: Account, channel_id: str, **overrides) -> dict:
    r = await acc.post(
        "/projects",
        json={
            "channel_id": channel_id,
            "title": "The Lost City",
            "topic": "the lost city of Atlantis",
            "target_duration_sec": 30,
            **overrides,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_png(path: Path, size: str = "800x600") -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}", "-frames:v", "1", str(path)],
        check=True,
    )
    return path


def make_wav(path: Path, seconds: float = 3.0, freq: int = 440) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}", str(path)], check=True
    )
    return path


@pytest.fixture
def tmp_media(tmp_path: Path) -> Path:
    return tmp_path
