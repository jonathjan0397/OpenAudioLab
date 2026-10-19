"""Admin audit helper."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AdminAudit


def record_admin_audit(
    session: Session,
    admin_id: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    reason: str | None = None,
    context_json: dict | None = None,
) -> AdminAudit:
    audit = AdminAudit(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        context_json=context_json or {},
    )
    session.add(audit)
    return audit
