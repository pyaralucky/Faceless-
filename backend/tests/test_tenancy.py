from tests.conftest import add_member, make_channel, make_project, register


async def test_cross_tenant_isolation(client, owner):
    other = await register(client, org="Other Co")
    ch = await make_channel(owner)
    # Other user's token with our org header -> not a member -> 404 (no existence leak)
    assert (await other.as_org(owner.org_id).get("/channels")).status_code == 404
    # Other user's own org cannot see our channel by id
    assert (await other.get(f"/channels/{ch['id']}")).status_code == 404
    assert (await other.get("/channels")).json() == []
    proj = await make_project(owner, ch["id"])
    assert (await other.get(f"/projects/{proj['id']}")).status_code == 404
    # Can't create a project in someone else's channel
    r = await other.post("/projects", json={"channel_id": ch["id"], "title": "x"})
    assert r.status_code == 404


async def test_missing_org_header(client, owner):
    r = await client.get("/api/v1/channels", headers={"Authorization": f"Bearer {owner.token}"})
    assert r.status_code == 422


async def test_role_enforcement(client, owner):
    viewer = await add_member(owner, "viewer")
    editor = await add_member(owner, "editor")
    assert (await viewer.get("/channels")).status_code == 200
    r = await viewer.post("/channels", json={"name": "Nope"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    ch = await make_channel(editor)
    # editors can't delete channels (admin+)
    assert (await editor.delete(f"/channels/{ch['id']}")).status_code == 403
    assert (await owner.delete(f"/channels/{ch['id']}")).status_code == 200
    # API configuration is admin-only
    assert (await editor.get("/api-config/credentials")).status_code == 403


async def test_member_management_rules(client, owner):
    admin = await add_member(owner, "admin")
    target = await register(client)
    r = await admin.post("/organizations/current/members", json={"email": target.email, "role": "owner"})
    assert r.status_code == 403  # can't grant above own role
    r = await admin.post("/organizations/current/members", json={"email": target.email, "role": "editor"})
    assert r.status_code == 201
    r = await admin.post("/organizations/current/members", json={"email": target.email, "role": "editor"})
    assert r.status_code == 409
    members = (await owner.get("/organizations/current/members")).json()
    owner_id = next(m["user_id"] for m in members if m["role"] == "owner")
    # admin can't remove an owner; owner can't demote the last owner
    assert (await admin.delete(f"/organizations/current/members/{owner_id}")).status_code == 403
    r = await owner.patch(f"/organizations/current/members/{owner_id}", json={"role": "admin"})
    assert r.status_code == 422
    logs = (await owner.get("/organizations/current/audit-logs")).json()
    assert logs["total"] >= 2
    assert any(entry["action"] == "member.added" for entry in logs["items"])


async def test_multiple_organizations(client, owner):
    r = await client.post(
        "/api/v1/organizations", json={"name": "Second Studio"}, headers={"Authorization": f"Bearer {owner.token}"}
    )
    assert r.status_code == 201
    second = owner.as_org(r.json()["id"])
    await make_channel(second, name="Only in second")
    names_first = [c["name"] for c in (await owner.get("/channels")).json()]
    assert "Only in second" not in names_first
    orgs = (await client.get("/api/v1/organizations", headers={"Authorization": f"Bearer {owner.token}"})).json()
    assert len(orgs) == 2


async def test_superuser_admin_endpoints(client):
    # The first registered user in a fresh DB is the platform superuser; others are not.
    normal = await register(client)
    r = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {normal.token}"})
    assert r.status_code == 403
