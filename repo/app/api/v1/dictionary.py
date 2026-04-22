from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import require_permission
from app.models.entities import User
from app.services import dictionary_service

router = APIRouter()

@router.get("/")
def get_dictionary(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("dictionary", "read"))
) -> list[dict]:
    """
    Service to retrieve the system data dictionary.
    Requires 'dictionary:read' permission.
    """
    return dictionary_service.get_data_dictionary(db)
