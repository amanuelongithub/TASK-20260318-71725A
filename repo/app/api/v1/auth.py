from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_token_payload, get_current_user
from app.models.entities import User
from app.schemas.auth import JoinOrganizationRequest, LoginRequest, PasswordResetConfirm, PasswordResetRequest, RegisterRequest, TokenResponse
from app.services import auth_service

router = APIRouter()


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    user = auth_service.register(db, payload)
    return {"id": user.id, "username": user.username, "org_id": user.org_id}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return TokenResponse(access_token=auth_service.login(db, payload))


@router.post("/password-reset/request")
def request_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> dict:
    auth_service.request_password_reset(db, payload.org_code, payload.username)
    return {"message": "If user exists, a reset token has been generated"}


@router.post("/password-reset/confirm")
def confirm_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)) -> dict:
    success = auth_service.reset_password(db, payload.org_code, payload.token, payload.new_password)
    if not success:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return {"message": "Password reset successfully"}


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    payload: dict = Depends(get_current_token_payload),
) -> dict:
    auth_service.logout_event(db, actor, payload)
    return {"message": "Logged out"}


@router.post("/join-organization", response_model=TokenResponse)
def join_organization(
    payload: JoinOrganizationRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TokenResponse:
    from app.core.security import create_access_token
    updated_user = auth_service.join_organization(db, actor, payload.org_code)
    
    role_name = updated_user.role.name.value if updated_user.role else "general_user"
    token = create_access_token(
        subject=str(updated_user.id),
        org_id=updated_user.org_id,
        roles=[role_name]
    )
    return TokenResponse(access_token=token)
    
