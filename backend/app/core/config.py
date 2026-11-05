"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ---
    app_name: str = "Faceless AI Studio"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True
    api_prefix: str = "/api/v1"
    public_api_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- security ---
    secret_key: str = "change-me-in-production-please-32b+"
    # Fernet key (urlsafe base64, 32 bytes). Comma separated list supports key rotation:
    # the first key encrypts, all keys may decrypt.
    encryption_keys: str = ""
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    jwt_algorithm: str = "HS256"
    password_min_length: int = 10
    login_rate_limit_per_minute: int = 10

    # --- data stores ---
    database_url: str = "postgresql+asyncpg://faceless:faceless@localhost:5432/faceless"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = "redis://localhost:6379/0"

    # --- storage ---
    storage_root: Path = Path("./data")
    max_upload_mb: int = 512

    # --- rendering ---
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    render_font_file: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    render_font_name: str = "DejaVu Sans"
    render_preset: str = "medium"
    render_crf: int = 20
    render_fps: int = 30

    # --- LLM defaults (per-organization credentials override these) ---
    llm_default_provider: str = "mock"
    llm_default_model: str = "mock-1"
    llm_max_retries: int = 3
    llm_timeout_seconds: float = 120.0
    agent_max_revisions: int = 2

    # --- OAuth: Google / YouTube ---
    google_client_id: str = ""
    google_client_secret: str = ""
    # --- OAuth: Meta / Instagram (Instagram API with Facebook Login) ---
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = "v21.0"

    # --- publishing ---
    publish_max_attempts: int = 5
    allow_self_approval: bool = False
    publish_retry_base_seconds: int = 60
    # Public base URL from which Instagram can fetch rendered media (required by the Graph API)
    media_public_base_url: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def oauth_redirect_base(self) -> str:
        return f"{self.public_api_url.rstrip('/')}{self.api_prefix}/social/oauth"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
