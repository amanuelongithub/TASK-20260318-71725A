from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import User
from app.schemas.data_governance import CreateDataVersionRequest, RollbackRequest, ValidateBatchRequest
from app.services import data_governance_service

router = APIRouter()


@router.post("/versions")
def create_version(
    payload: CreateDataVersionRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("data_governance", "write")),
) -> dict:
    row = data_governance_service.create_data_version(db, actor, payload.entity_type, payload.entity_id, payload.payload)
    return {"version_id": row.id, "version_no": row.version_no}


@router.post("/validate")
def validate_batch(
    payload: ValidateBatchRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("data_governance", "write")),
) -> dict:
    return data_governance_service.validate_records(db, actor, payload.batch_id, payload.records)


@router.post("/rollback")
def rollback(
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("data_governance", "write")),
) -> dict:
    return data_governance_service.rollback_to_version(db, actor, payload.version_id)


@router.get("/lineage/{entity_type}/{entity_id}")
def get_lineage(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("data_governance", "read")),

) -> list:
    rows = data_governance_service.list_lineage(db, actor, entity_type, entity_id)
    return [
        {
            "version_id": r.id,
            "version_no": r.version_no,
            "created_by": r.created_by,
            "created_at": r.created_at,
            "payload_summary": list(r.payload.keys()) if r.payload else [],
        }
        for r in rows
    ]
