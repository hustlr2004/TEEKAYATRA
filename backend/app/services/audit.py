from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog


def audit_child_access(db: Session, actor_id: int, action: str, child_id: int, purpose: str) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type="child",
            resource_id=str(child_id),
            purpose=purpose,
        )
    )
