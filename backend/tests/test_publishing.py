"""Publishing queue, approvals, retries and analytics using fake platform clients."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import encrypt_secret
from app.integrations.base import Metrics, OAuthTokens, PlatformError, PublishResult
from app.models import Asset, RenderJob, SocialAccount
from app.models.enums import AssetKind, RunStatus
from app.services import social as social_service
from app.services.analytics import collect_all
from app.services.publishing import claim_due_jobs, execute_publish
from tests.conftest import add_member, make_channel, make_project


class FakeYouTube:
    def __init__(self):
        self.errors: list[PlatformError] = []
        self.published = []
        self.refreshed = 0

    async def publish(self, token, req, on_progress=None):
        if self.errors:
            raise self.errors.pop(0)
        if on_progress:
            await on_progress(0.5)
            await on_progress(1.0)
        self.published.append((token, req.title, req.tags))
        return PublishResult(external_id="yt123", url="https://www.youtube.com/watch?v=yt123")

    async def refresh(self, refresh_token):
        self.refreshed += 1
        return OAuthTokens(
            access_token="fresh-token", refresh_token=None, expires_at=datetime.now(UTC) + timedelta(hours=1)
        )

    async def fetch_metrics(self, token, video_id, published_at):
        return Metrics(views=1000, likes=80, comments=10, shares=10, watch_time_minutes=250.0)


@pytest.fixture
def yt():
    fake = FakeYouTube()
    social_service.set_client("youtube", fake)
    yield fake
    social_service._clients.pop("youtube", None)


async def _setup(
    owner, db, *, require_approval=False, fmt="vertical", platform="youtube", expires_in=timedelta(hours=1)
):
    ch = await make_channel(owner, require_approval=require_approval)
    p = await make_project(owner, ch["id"])
    org_id, pid = uuid.UUID(owner.org_id), uuid.UUID(p["id"])
    video = Asset(
        organization_id=org_id,
        project_id=pid,
        kind=AssetKind.RENDER,
        filename="v.mp4",
        storage_path="orgs/x/v.mp4",
        mime_type="video/mp4",
    )
    db.add(video)
    await db.flush()
    render = RenderJob(
        organization_id=org_id,
        project_id=pid,
        format=fmt,
        status=RunStatus.SUCCEEDED,
        qc_report={"passed": True},
        output_asset_id=video.id,
        finished_at=datetime.now(UTC),
    )
    account = SocialAccount(
        organization_id=org_id,
        platform=platform,
        external_id=f"ext-{uuid.uuid4().hex[:6]}",
        display_name="My Channel",
        encrypted_access_token=encrypt_secret("old-token"),
        encrypted_refresh_token=encrypt_secret("refresh"),
        token_expires_at=datetime.now(UTC) + expires_in,
    )
    db.add_all([render, account])
    await db.commit()
    return p, render, account


async def test_publish_without_approval(owner, db, session_factory, yt):
    p, render, account = await _setup(owner, db)
    await owner.patch(
        f"/projects/{p['id']}",
        json={
            "optimization": {"titles": ["Optimised title"], "description": "desc", "tags": ["a", "b"], "hashtags": []}
        },
    )
    r = await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "scheduled" and job["title"] == "Optimised title" and job["tags"] == ["a", "b"]
    async with session_factory() as s:
        ids = await claim_due_jobs(s)
    assert uuid.UUID(job["id"]) in ids
    assert await execute_publish(session_factory, uuid.UUID(job["id"])) == "published"
    done = (await owner.get(f"/publishing/jobs/{job['id']}")).json()
    assert done["external_url"].endswith("yt123") and done["upload_progress"] == 100
    assert [h["event"] for h in done["history"]][-1] == "published"
    assert (await owner.get(f"/projects/{p['id']}")).json()["status"] == "published"
    assert yt.published[0][0] == "old-token"


async def test_approval_workflow(client, owner, db, session_factory, yt, monkeypatch):
    reviewer = await add_member(owner, "reviewer")
    editor = await add_member(owner, "editor")
    p, render, account = await _setup(owner, db, require_approval=True)
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    r = await editor.post(
        "/publishing/jobs",
        json={"project_id": p["id"], "social_account_id": str(account.id), "title": "T", "scheduled_at": future},
    )
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "pending_approval"
    approvals = (await owner.get("/approvals?status=pending")).json()["items"]
    assert len(approvals) == 1
    aid = approvals[0]["id"]
    # editor (requester) can't review: role is fine but self-approval is blocked
    r = await editor.post(f"/approvals/{aid}/decision", json={"decision": "approve"})
    assert r.status_code == 422
    # viewer-level users cannot review at all
    viewer = await add_member(owner, "viewer")
    assert (await viewer.post(f"/approvals/{aid}/decision", json={"decision": "approve"})).status_code == 403
    r = await reviewer.post(f"/approvals/{aid}/decision", json={"decision": "approve", "note": "LGTM"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    job = (await owner.get(f"/publishing/jobs/{job['id']}")).json()
    assert job["status"] == "scheduled"
    # scheduled for the future -> not claimed yet
    async with session_factory() as s:
        assert uuid.UUID(job["id"]) not in await claim_due_jobs(s)
    assert (await reviewer.post(f"/approvals/{aid}/decision", json={"decision": "reject"})).status_code == 409
    # publish-now bypasses the schedule
    r = await owner.post(f"/publishing/jobs/{job['id']}/publish-now")
    assert r.status_code == 202


async def test_rejection(owner, db, yt):
    reviewer = await add_member(owner, "reviewer")
    p, _, account = await _setup(owner, db, require_approval=True)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    aid = (await owner.get("/approvals")).json()["items"][0]["id"]
    await reviewer.post(f"/approvals/{aid}/decision", json={"decision": "reject", "note": "Fix the hook"})
    assert (await owner.get(f"/publishing/jobs/{job['id']}")).json()["status"] == "rejected"


async def test_retry_with_backoff_then_success(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    yt.errors = [PlatformError("youtube 503", retryable=True)]
    assert await execute_publish(session_factory, uuid.UUID(job["id"])) == "scheduled"
    j = (await owner.get(f"/publishing/jobs/{job['id']}")).json()
    assert j["attempts"] == 1 and j["last_error"] == "youtube 503"
    assert datetime.fromisoformat(j["next_attempt_at"]).replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(seconds=30)
    assert await execute_publish(session_factory, uuid.UUID(job["id"])) == "published"


async def test_permanent_failure_and_manual_retry(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    yt.errors = [PlatformError("invalid video", retryable=False)]
    assert await execute_publish(session_factory, uuid.UUID(job["id"])) == "failed"
    r = await owner.post(f"/publishing/jobs/{job['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "scheduled" and r.json()["attempts"] == 0


async def test_max_attempts_exhausted(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    yt.errors = [PlatformError("503")] * 10
    statuses = [await execute_publish(session_factory, uuid.UUID(job["id"])) for _ in range(5)]
    assert statuses[-1] == "failed" and statuses[:-1] == ["scheduled"] * 4


async def test_auth_error_marks_account_expired(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    yt.errors = [PlatformError("token revoked", retryable=False, auth_error=True)]
    assert await execute_publish(session_factory, uuid.UUID(job["id"])) == "failed"
    accounts = (await owner.get("/social/accounts")).json()
    assert accounts[0]["status"] == "expired"
    r = await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    assert r.status_code == 422


async def test_token_refresh_before_upload(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db, expires_in=timedelta(minutes=1))
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    assert await execute_publish(session_factory, uuid.UUID(job["id"])) == "published"
    assert yt.refreshed == 1 and yt.published[0][0] == "fresh-token"


async def test_validation_rules(owner, db, yt):
    p, render, account = await _setup(owner, db, fmt="horizontal", platform="instagram")
    r = await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    assert r.status_code == 422 and "vertical" in r.json()["error"]["message"]
    ch = await make_channel(owner)
    p2 = await make_project(owner, ch["id"])
    r = await owner.post("/publishing/jobs", json={"project_id": p2["id"], "social_account_id": str(account.id)})
    assert r.status_code == 422 and "render" in r.json()["error"]["message"]
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    p3, _, acc3 = await _setup(owner, db)
    r = await owner.post(
        "/publishing/jobs", json={"project_id": p3["id"], "social_account_id": str(acc3.id), "scheduled_at": past}
    )
    assert r.status_code == 422


async def test_cancel_and_edit(owner, db, yt):
    p, _, account = await _setup(owner, db, require_approval=True)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    r = await owner.patch(f"/publishing/jobs/{job['id']}", json={"title": "New title", "tags": ["x"]})
    assert r.json()["title"] == "New title"
    r = await owner.post(f"/publishing/jobs/{job['id']}/cancel")
    assert r.json()["status"] == "cancelled"
    assert (await owner.get("/approvals?status=pending")).json()["total"] == 0
    assert (await owner.patch(f"/publishing/jobs/{job['id']}", json={"title": "x"})).status_code == 409


async def test_analytics_collection_and_report(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db)
    job = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    await execute_publish(session_factory, uuid.UUID(job["id"]))
    assert await collect_all(session_factory, uuid.UUID(owner.org_id)) == 1
    snaps = (await owner.get(f"/analytics/jobs/{job['id']}/snapshots")).json()
    assert snaps[0]["views"] == 1000
    report = (await owner.get("/analytics/report?days=7")).json()
    assert report["totals"]["views"] == 1000 and report["totals"]["engagement_rate"] == 10.0
    assert report["by_platform"]["youtube"]["posts"] == 1
    assert report["top_posts"][0]["title"] == job["title"]
    assert report["daily"][0]["cumulative_views"] == 1000
    assert (await owner.post("/analytics/collect")).status_code == 202
    dash = (await owner.get("/dashboard")).json()
    assert dash["total_views"] == 1000 and dash["counts"]["published_posts"] == 1


async def test_disconnect_keeps_history_and_cancels_pending(owner, db, session_factory, yt):
    p, _, account = await _setup(owner, db)
    published = (
        await owner.post("/publishing/jobs", json={"project_id": p["id"], "social_account_id": str(account.id)})
    ).json()
    await execute_publish(session_factory, uuid.UUID(published["id"]))
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    pending = (
        await owner.post(
            "/publishing/jobs",
            json={"project_id": p["id"], "social_account_id": str(account.id), "scheduled_at": future},
        )
    ).json()
    assert (await owner.delete(f"/social/accounts/{account.id}")).status_code == 200
    acc = (await owner.get("/social/accounts")).json()[0]
    assert acc["status"] == "revoked"
    assert (await owner.get(f"/publishing/jobs/{published['id']}")).json()["status"] == "published"
    assert (await owner.get(f"/publishing/jobs/{pending['id']}")).json()["status"] == "cancelled"
