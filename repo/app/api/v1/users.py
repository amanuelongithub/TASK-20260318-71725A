from fastapi import APIRouter, Depends

from app.core.security import decrypt_field
from app.middleware.auth import get_current_user
from app.models.entities import User

router = APIRouter()


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict:
    from app.core.security import desensitize_response
    role_name = current_user.role.name.value if current_user.role else ""
    data = {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "email": decrypt_field(current_user.email_encrypted) if current_user.email_encrypted else None,
        "org_id": current_user.org_id,
        "role": role_name,
    }
    return desensitize_response(data, role_name)

