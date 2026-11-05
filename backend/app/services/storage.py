"""Local filesystem storage (mount a volume / network disk in production).

The interface is deliberately small so it can be swapped for S3-compatible storage.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import uuid
from pathlib import Path

import anyio
from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import ValidationFailedError

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

ALLOWED_MIME_PREFIXES = {
    "image": ("image/",),
    "video": ("video/",),
    "narration": ("audio/",),
    "music": ("audio/",),
    "subtitle": ("text/", "application/x-subrip", "application/octet-stream"),
}


def safe_filename(name: str) -> str:
    name = _SAFE.sub("_", Path(name).name).strip("._") or "file"
    return name[:120]


def root() -> Path:
    p = Path(settings.storage_root).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def org_dir(org_id: uuid.UUID, *parts: str) -> Path:
    p = root() / "orgs" / str(org_id)
    for part in parts:
        p = p / part
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve(storage_path: str) -> Path:
    """Resolve a stored relative path, refusing anything that escapes the storage root."""
    base = root()
    p = (base / storage_path).resolve()
    if base not in p.parents and p != base:
        raise ValidationFailedError("Invalid storage path")
    return p


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(root()))


def guess_mime(filename: str) -> str:
    if filename.lower().endswith(".srt"):
        return "application/x-subrip"
    if filename.lower().endswith(".ass"):
        return "text/x-ssa"
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


async def save_upload(
    upload: UploadFile, org_id: uuid.UUID, project_id: uuid.UUID | None, kind: str
) -> tuple[str, int, str, str]:
    """Stream an upload to disk. Returns (storage_path, size, sha256, mime)."""
    filename = safe_filename(upload.filename or "upload")
    mime = upload.content_type or guess_mime(filename)
    if mime == "application/octet-stream":
        mime = guess_mime(filename)
    allowed = ALLOWED_MIME_PREFIXES.get(kind)
    if allowed and not mime.startswith(allowed):
        raise ValidationFailedError(f"File type {mime} not allowed for asset kind '{kind}'")

    dest_dir = org_dir(org_id, "projects", str(project_id) if project_id else "shared", "uploads")
    dest = dest_dir / f"{uuid.uuid4().hex[:12]}_{filename}"
    limit = settings.max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    async with await anyio.open_file(dest, "wb") as fh:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                await fh.aclose()
                dest.unlink(missing_ok=True)
                raise ValidationFailedError(f"File exceeds {settings.max_upload_mb} MB limit")
            digest.update(chunk)
            await fh.write(chunk)
    return relative(dest), size, digest.hexdigest(), mime


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def delete_path(storage_path: str) -> None:
    p = resolve(storage_path)
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)
