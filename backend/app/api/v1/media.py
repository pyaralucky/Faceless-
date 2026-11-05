"""Signed, expiring public media URLs (needed by Instagram's Content Publishing API to fetch videos)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Asset
from app.models.enums import AssetKind
from app.services import storage

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{token}", include_in_schema=False)
async def public_media(token: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    payload = decode_token(token, "media")
    asset = await db.get(Asset, uuid.UUID(payload["asset"]))
    if asset is None or asset.kind not in (AssetKind.RENDER, AssetKind.THUMBNAIL):
        raise NotFoundError("Media not found")
    path = storage.resolve(asset.storage_path)
    if not path.exists():
        raise NotFoundError("Media not found")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.filename)
