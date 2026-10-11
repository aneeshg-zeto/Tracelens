from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    project_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the current transaction (committed with the change it describes)."""
    db.add(
        AuditEvent(
            organization_id=organization_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_=metadata or {},
        )
    )
