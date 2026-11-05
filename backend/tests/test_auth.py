from tests.conftest import register


async def test_register_login_me(client):
    acc = await register(client, email="Alice@Example.com")
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {acc.token}"})
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "alice@example.com"
    assert me["memberships"][0]["role"] == "owner"

    r = await client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "Sup3r-secret-pw"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"


async def test_duplicate_email_and_weak_password(client):
    await register(client, email="dup@example.com")
    r = await client.post("/api/v1/auth/register", json={"email": "dup@example.com", "password": "Sup3r-secret-pw"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"
    r = await client.post("/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


async def test_wrong_password_and_missing_token(client):
    await register(client, email="bob@example.com")
    r = await client.post("/api/v1/auth/login", json={"email": "bob@example.com", "password": "wrong-password-1"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    r = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
    assert r.status_code == 401
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"


async def test_refresh_rotation_and_reuse_detection(client):
    acc = await register(client)
    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": acc.refresh})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    assert new_refresh != acc.refresh
    # Reusing the old (rotated) token revokes the whole family
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": acc.refresh})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "token_reused"
    r3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 401


async def test_logout_revokes(client):
    acc = await register(client)
    assert (await client.post("/api/v1/auth/logout", json={"refresh_token": acc.refresh})).status_code == 200
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": acc.refresh})
    assert r.status_code == 401


async def test_change_password(client):
    acc = await register(client, email="carol@example.com")
    h = {"Authorization": f"Bearer {acc.token}"}
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": "nope-nope-1", "new_password": "An0ther-secret!"},
    )
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={"current_password": "Sup3r-secret-pw", "new_password": "An0ther-secret!"},
    )
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login", json={"email": "carol@example.com", "password": "An0ther-secret!"})
    assert r.status_code == 200


async def test_login_rate_limit(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 3)
    for _ in range(3):
        await client.post("/api/v1/auth/login", json={"email": "rl@example.com", "password": "whatever-123"})
    r = await client.post("/api/v1/auth/login", json={"email": "rl@example.com", "password": "whatever-123"})
    assert r.status_code == 429


async def test_request_id_and_health(client):
    r = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.status_code == 200 and r.headers["X-Request-ID"] == "abc123"
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
