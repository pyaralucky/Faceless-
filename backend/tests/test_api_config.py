import uuid

from sqlalchemy import select

from app.core.security import decrypt_secret, encrypt_secret
from app.models import ProviderCredential


async def test_credentials_encrypted_at_rest(owner, db):
    r = await owner.post("/api-config/credentials", json={"provider": "openai", "api_key": "sk-test-1234567890abcdef"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "api_key" not in body and body["key_hint"] == "sk-…cdef"
    row = await db.scalar(select(ProviderCredential).where(ProviderCredential.id == uuid.UUID(body["id"])))
    assert "sk-test" not in row.encrypted_api_key
    assert decrypt_secret(row.encrypted_api_key) == "sk-test-1234567890abcdef"
    r = await owner.post("/api-config/credentials", json={"provider": "openai", "api_key": "x"})
    assert r.status_code == 409
    r = await owner.patch(
        f"/api-config/credentials/{body['id']}", json={"api_key": "sk-rotated-key-999999", "is_active": False}
    )
    assert r.json()["key_hint"] == "sk-…9999" and r.json()["is_active"] is False
    assert (await owner.delete(f"/api-config/credentials/{body['id']}")).status_code == 200


async def test_model_routes(owner):
    r = await owner.put(
        "/api-config/routes/script",
        json={
            "provider": "anthropic",
            "model": "claude-sonnet-5-5",
            "temperature": 0.8,
            "fallbacks": [{"provider": "openai", "model": "gpt-4.1-mini"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["fallbacks"][0]["provider"] == "openai"
    r = await owner.put("/api-config/routes/script", json={"provider": "google", "model": "gemini-2.5-flash"})
    assert r.json()["provider"] == "google" and r.json()["fallbacks"] == []
    assert (await owner.put("/api-config/routes/bogus", json={"provider": "openai", "model": "x"})).status_code == 422
    assert (await owner.put("/api-config/routes/*", json={"provider": "mock", "model": "mock-1"})).status_code == 200
    routes = (await owner.get("/api-config/routes")).json()
    assert {r["agent_name"] for r in routes} == {"script", "*"}
    catalog = (await owner.get("/api-config/catalog")).json()
    assert "fact_check" in catalog["agents"] and "anthropic" in catalog["providers"]


async def test_test_credential_mock(owner):
    r = await owner.post("/api-config/credentials", json={"provider": "mock", "api_key": "unused"})
    r = await owner.post(f"/api-config/credentials/{r.json()['id']}/test")
    assert r.json()["ok"] is True


def test_key_rotation(monkeypatch):
    from cryptography.fernet import Fernet

    from app.core.config import settings

    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "encryption_keys", k1)
    token = encrypt_secret("hello")
    monkeypatch.setattr(settings, "encryption_keys", f"{k2},{k1}")  # new primary, old still decrypts
    assert decrypt_secret(token) == "hello"
