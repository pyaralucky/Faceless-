from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def record_audit(
    db: AsyncSession,
    *,
    action: str,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    data: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Adds an audit entry to the current unit of work (committed with the caller's transaction)."""
    db.add(
        AuditLog(
            organization_id=org_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            data=data or {},
            ip_address=ip,
        )
    )
