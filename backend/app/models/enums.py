"""String enums stored as VARCHAR (portable, migration-friendly)."""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


ROLE_RANK = {Role.VIEWER: 0, Role.REVIEWER: 1, Role.EDITOR: 2, Role.ADMIN: 3, Role.OWNER: 4}


class VideoFormat(StrEnum):
    VERTICAL = "vertical"  # 1080x1920
    HORIZONTAL = "horizontal"  # 1920x1080


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    SCRIPTED = "scripted"
    RENDERING = "rendering"
    RENDERED = "rendered"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    NARRATION = "narration"
    MUSIC = "music"
    SUBTITLE = "subtitle"
    RENDER = "render"
    THUMBNAIL = "thumbnail"


class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class SocialAccountStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class PublishStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LLMProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENROUTER = "openrouter"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"
    MOCK = "mock"
