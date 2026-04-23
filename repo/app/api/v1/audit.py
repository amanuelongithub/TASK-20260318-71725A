from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import desensitize_response, mask_value
from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import AuditLog, RoleType, User

router = APIRouter()

# Sensitive keys that may appear in event_metadata and must be masked for non-admin
_SENSITIVE_META_KEYS = {"username", "target_username", "org_code", "email", "full_name"}


def _serialize_log(log: AuditLog, role_name) -> dict:
    """Return an audit log entry with role-appropriate metadata visibility.

    - ADMIN: full metadata
    - AUDITOR: event + created_at + desensitized metadata (sensitive keys masked)
    - REVIEWER / GENERAL_USER: event + created_at only, no metadata
    """
    role_str = str(role_name.value if hasattr(role_name, "value") else role_name)

    base = {
        "id": log.id,
        "event": log.event,
        "created_at": log.created_at.isoformat(),
    }

    if role_str == RoleType.ADMIN.value:
        base["metadata"] = log.event_metadata
        return base

    if role_str == RoleType.AUDITOR.value:
        sanitized = {}
        for k, v in (log.event_metadata or {}).items():
            if k in _SENSITIVE_META_KEYS:
                sanitized[k] = mask_value(k, v)
            else:
                sanitized[k] = v
        base["metadata"] = sanitized
        return base

    # REVIEWER / GENERAL_USER — no metadata
    base["metadata"] = None
    return base


@router.get("/logs")
def list_logs(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("audit", "read")),
) -> list[dict]:
    logs = (
        db.scalars(
            select(AuditLog)
            .where(AuditLog.org_id == actor.org_id)
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        ).all()
    )
    return [_serialize_log(r, actor.role.name) for r in logs]
