"""Official-API integration clients tested against mocked HTTP endpoints (respx)."""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.security import decrypt_secret
from app.integrations.base import PlatformError, PublishRequest
from app.integrations.instagram import InstagramClient
from app.integrations.youtube import CHUNK, UPLOAD_API, YouTubeClient
from app.models import SocialAccount
from app.services import social as social_service
from app.services.publishing import public_media_url
from tests.conftest import make_channel

G = "https://graph.facebook.com/v21.0"


def test_authorization_urls():
    yt_url = YouTubeClient().authorization_url("STATE")
    q = parse_qs(urlparse(yt_url).query)
    assert q["access_type"] == ["offline"] and q["state"] == ["STATE"]
    assert "youtube.upload" in q["scope"][0] and q["redirect_uri"][0].endswith("/social/oauth/youtube/callback")
    ig = parse_qs(urlparse(InstagramClient().authorization_url("S2")).query)
    assert "instagram_content_publish" in ig["scope"][0]


@respx.mock
async def test_youtube_resumable_upload(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0" * (CHUNK + 1000))  # two chunks
    session = "https://upload.example/session/1"
    start = respx.post(f"{UPLOAD_API}/videos").mock(return_value=httpx.Response(200, headers={"Location": session}))
    chunks = respx.put(session).mock(
        side_effect=[
            httpx.Response(308, headers={"Range": f"bytes=0-{CHUNK - 1}"}),
            httpx.Response(200, json={"id": "VID42"}),
        ]
    )
    progress = []

    async def on_progress(f):
        progress.append(f)

    req = PublishRequest(
        video_path=str(video), thumbnail_path=None, title="T" * 150, description="d", tags=["a"], privacy="private"
    )
    res = await YouTubeClient(httpx.AsyncClient()).publish("tok", req, on_progress)
    assert res.external_id == "VID42" and res.url.endswith("VID42")
    assert start.calls[0].request.headers["x-upload-content-length"] == str(CHUNK + 1000)
    body = start.calls[0].request.content.decode()
    assert '"title":"' + "T" * 100 + '"' in body.replace(" ", "")  # title truncated to 100
    assert chunks.calls[1].request.headers["content-range"] == f"bytes {CHUNK}-{CHUNK + 999}/{CHUNK + 1000}"
    assert progress[-1] == 1.0


@respx.mock
async def test_youtube_resume_existing_session(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\1" * 1000)
    session = "https://upload.example/session/2"
    route = respx.put(session).mock(
        side_effect=[
            httpx.Response(308, headers={"Range": "bytes=0-499"}),  # status query: 500 bytes already uploaded
            httpx.Response(201, json={"id": "VID7"}),
        ]
    )
    req = PublishRequest(
        video_path=str(video),
        thumbnail_path=None,
        title="t",
        description="",
        tags=[],
        privacy="private",
        state={"upload_session": session},
    )
    res = await YouTubeClient(httpx.AsyncClient()).publish("tok", req)
    assert res.external_id == "VID7"
    assert route.calls[0].request.headers["content-range"] == "bytes */1000"
    assert route.calls[1].request.headers["content-range"] == "bytes 500-999/1000"
    assert "upload_session" not in res.state


@respx.mock
async def test_youtube_errors_classified(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    respx.post(f"{UPLOAD_API}/videos").mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})
    )
    with pytest.raises(PlatformError) as ei:
        await YouTubeClient(httpx.AsyncClient()).publish(
            "bad", PublishRequest(str(video), None, "t", "", [], "private")
        )
    assert ei.value.auth_error and not ei.value.retryable
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(PlatformError) as ei:
        await YouTubeClient(httpx.AsyncClient()).refresh("r")
    assert ei.value.auth_error


@respx.mock
async def test_instagram_reel_publish_flow():
    create = respx.post(f"{G}/1784/media").mock(return_value=httpx.Response(200, json={"id": "C1"}))
    respx.get(f"{G}/C1").mock(
        side_effect=[
            httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
            httpx.Response(200, json={"status_code": "FINISHED"}),
        ]
    )
    publish = respx.post(f"{G}/1784/media_publish").mock(return_value=httpx.Response(200, json={"id": "M9"}))
    respx.get(f"{G}/M9").mock(return_value=httpx.Response(200, json={"permalink": "https://instagram.com/reel/abc"}))
    client = InstagramClient(httpx.AsyncClient(), poll_interval=0)
    req = PublishRequest(
        video_path="/x.mp4",
        thumbnail_path=None,
        title="t",
        description="Caption",
        tags=["history", "#facts"],
        privacy="public",
        public_video_url="https://api.example.test/api/v1/media/tok",
    )
    res = await client.publish("page-token", "1784", req)
    assert res.external_id == "M9" and res.url == "https://instagram.com/reel/abc"
    form = parse_qs(create.calls[0].request.content.decode())
    assert form["media_type"] == ["REELS"] and "#history #facts" in form["caption"][0]
    assert parse_qs(publish.calls[0].request.content.decode())["creation_id"] == ["C1"]


@respx.mock
async def test_instagram_requires_public_url_and_handles_error_status():
    client = InstagramClient(httpx.AsyncClient(), poll_interval=0)
    with pytest.raises(PlatformError) as ei:
        await client.publish("t", "1", PublishRequest("/x.mp4", None, "t", "", [], "public"))
    assert not ei.value.retryable
    respx.post(f"{G}/1/media").mock(return_value=httpx.Response(200, json={"id": "C2"}))
    respx.get(f"{G}/C2").mock(return_value=httpx.Response(200, json={"status_code": "ERROR", "status": "bad codec"}))
    with pytest.raises(PlatformError, match="ERROR"):
        await client.publish(
            "t", "1", PublishRequest("/x.mp4", None, "t", "", [], "public", public_video_url="https://x/v.mp4")
        )
    respx.post(f"{G}/2/media").mock(
        return_value=httpx.Response(400, json={"error": {"type": "OAuthException", "code": 190, "message": "expired"}})
    )
    with pytest.raises(PlatformError) as ei:
        await client.publish(
            "t", "2", PublishRequest("/x.mp4", None, "t", "", [], "public", public_video_url="https://x/v.mp4")
        )
    assert ei.value.auth_error


@respx.mock
async def test_oauth_callback_stores_encrypted_tokens(client, owner, db):
    social_service.set_client("youtube", YouTubeClient(httpx.AsyncClient()))
    ch = await make_channel(owner)
    r = await owner.get(f"/social/youtube/authorize?channel_id={ch['id']}")
    assert r.status_code == 200
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "ya29.access", "refresh_token": "1//refresh", "expires_in": 3599, "scope": "a b"}
        )
    )
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UC123",
                        "snippet": {"title": "My YT", "thumbnails": {"default": {"url": "https://img"}}},
                        "statistics": {"subscriberCount": "5"},
                    }
                ]
            },
        )
    )
    r = await client.get(f"/api/v1/social/oauth/youtube/callback?code=abc&state={state}")
    assert r.status_code == 307 and "connected=youtube" in r.headers["location"]
    acc = await db.scalar(select(SocialAccount).where(SocialAccount.external_id == "UC123"))
    assert acc.display_name == "My YT" and str(acc.channel_id) == ch["id"]
    assert "ya29" not in acc.encrypted_access_token and decrypt_secret(acc.encrypted_access_token) == "ya29.access"
    assert decrypt_secret(acc.encrypted_refresh_token) == "1//refresh"
    listed = (await owner.get("/social/accounts")).json()
    assert listed[0]["external_id"] == "UC123" and "encrypted_access_token" not in listed[0]
    # tampered / wrong-platform state is rejected without storing anything
    r = await client.get(f"/api/v1/social/oauth/instagram/callback?code=abc&state={state}")
    assert "error=" in r.headers["location"]
    r = await client.get("/api/v1/social/oauth/youtube/callback?error=access_denied")
    assert "error=access_denied" in r.headers["location"]
    social_service._clients.pop("youtube", None)


async def test_public_media_url_signed_and_scoped(client, db, owner):
    import uuid

    from app.models import Asset

    a = Asset(organization_id=uuid.UUID(owner.org_id), kind="image", filename="x.png", storage_path="x.png")
    db.add(a)
    await db.commit()
    url = public_media_url(a.id)
    path = url.replace("https://api.example.test", "")
    assert (await client.get(path)).status_code == 404  # only renders/thumbnails are public
    assert (await client.get("/api/v1/media/not-a-token")).status_code == 401
