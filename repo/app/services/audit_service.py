from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def log_event(db: Session, org_id: int, actor_id: int | None, event: str, metadata: dict) -> None:
    db.add(AuditLog(org_id=org_id, actor_id=actor_id, event=event, event_metadata=metadata))
