from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Role, RoleType

def ensure_standard_roles(db: Session) -> None:
    """
    Idempotently ensure that all standard roles defined in RoleType exist in the database.
    This does NOT handle permissions, which are seeded separately in init_db.
    """
    for role_type in RoleType:
        exists = db.scalar(select(Role).where(Role.name == role_type))
        if exists is None:
            db.add(Role(name=role_type))
    db.flush()
    # Note: caller is responsible for commit if needed, or it will be part of the larger transaction.
