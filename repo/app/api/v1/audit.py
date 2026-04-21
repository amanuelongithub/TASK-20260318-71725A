from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import AuditLog, User

router = APIRouter()


@router.get("/logs")
def list_logs(db: Session = Depends(get_db), actor: User = Depends(require_permission("audit", "read"))) -> list[dict]:
    logs = db.scalars(select(AuditLog).where(AuditLog.org_id == actor.org_id).order_by(AuditLog.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "event": r.event, "metadata": r.event_metadata, "created_at": r.created_at.isoformat()} for r in logs]
