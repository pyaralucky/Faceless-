"""Password hashing, JWT tokens and symmetric encryption for stored secrets."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings
from app.core.errors import AuthenticationError

# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    # bcrypt only considers the first 72 bytes; pre-hash to support long passphrases safely.
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest())
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    digest = base64.b64encode(hashlib.sha256(password.encode()).digest())
    try:
        return bcrypt.checkpw(digest, hashed.encode())
    except ValueError:
        return False


# ---------------------------------------------------------------- tokens


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(user_id: uuid.UUID, extra: dict[str, Any] | None = None) -> str:
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": secrets.token_hex(8),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_signed_token(purpose: str, data: dict[str, Any], ttl: timedelta) -> str:
    """Short-lived signed token for non-auth purposes (e.g. OAuth `state`)."""
    payload = {"type": purpose, "iat": _now(), "exp": _now() + ttl, "nonce": secrets.token_urlsafe(8), **data}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid token", code="invalid_token") from exc
    if payload.get("type") != expected_type:
        raise AuthenticationError("Invalid token type", code="invalid_token")
    return payload


def generate_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hash). Only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- encryption at rest


def _derive_dev_key() -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings.encryption_keys.split(",") if k.strip()]
    if not keys:
        if settings.is_production:
            raise RuntimeError("ENCRYPTION_KEYS must be configured in production")
        keys = [_derive_dev_key().decode()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt secret: wrong or rotated-out encryption key") from exc


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}…{value[-4:]}"
