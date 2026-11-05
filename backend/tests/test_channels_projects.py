from tests.conftest import make_channel, make_png, make_project, requires_ffmpeg


async def test_channel_crud(owner):
    ch = await make_channel(owner, name="History Shorts", branding={"subtitle_style": {"primary_color": "#FFFFFF"}})
    assert ch["project_count"] == 0 and ch["default_format"] == "vertical"
    r = await owner.post("/channels", json={"name": "history shorts"})
    assert r.status_code == 409
    r = await owner.patch(f"/channels/{ch['id']}", json={"tone": "dramatic", "default_format": "horizontal"})
    assert r.status_code == 200 and r.json()["tone"] == "dramatic"
    await make_project(owner, ch["id"])
    listed = (await owner.get("/channels")).json()
    assert listed[0]["project_count"] == 1
    r = await owner.patch(f"/channels/{ch['id']}", json={"is_active": False})
    assert (await owner.get("/channels")).json() == []
    assert len((await owner.get("/channels?include_inactive=true")).json()) == 1


async def test_project_crud_and_filters(owner):
    ch = await make_channel(owner, default_format="horizontal")
    p = await make_project(owner, ch["id"])
    assert p["format"] == "horizontal"  # inherited from channel
    assert p["status"] == "draft"
    await make_project(owner, ch["id"], title="Volcanoes", topic="supervolcanoes")
    page = (await owner.get("/projects?q=volcano")).json()
    assert page["total"] == 1 and page["items"][0]["title"] == "Volcanoes"
    page = (await owner.get(f"/projects?channel_id={ch['id']}&limit=1")).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    r = await owner.patch(f"/projects/{p['id']}", json={"script": {"title": "edited"}})
    assert r.json()["script"]["title"] == "edited"
    assert (await owner.delete(f"/projects/{p['id']}")).status_code == 200
    assert (await owner.get(f"/projects/{p['id']}")).status_code == 404


@requires_ffmpeg
async def test_asset_upload_download_delete(owner, tmp_media):
    ch = await make_channel(owner)
    p = await make_project(owner, ch["id"])
    img = make_png(tmp_media / "frame.png")
    with img.open("rb") as fh:
        r = await owner.post(
            f"/projects/{p['id']}/assets", data={"kind": "image"}, files={"file": ("frame.png", fh, "image/png")}
        )
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["width"] == 800 and asset["height"] == 600 and asset["size_bytes"] > 0
    r = await owner.get(f"/projects/{p['id']}/assets/{asset['id']}/file")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    # wrong mime for kind
    r = await owner.post(
        f"/projects/{p['id']}/assets", data={"kind": "narration"}, files={"file": ("x.png", b"123", "image/png")}
    )
    assert r.status_code == 422
    assert (await owner.delete(f"/projects/{p['id']}/assets/{asset['id']}")).status_code == 200
    assert (await owner.get(f"/projects/{p['id']}/assets")).json() == []


async def test_path_traversal_rejected():
    import pytest

    from app.core.errors import ValidationFailedError
    from app.services import storage

    with pytest.raises(ValidationFailedError):
        storage.resolve("../../etc/passwd")
    assert storage.safe_filename("../../evil name.mp4") == "evil_name.mp4"
