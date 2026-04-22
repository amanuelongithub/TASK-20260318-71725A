from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_token_payload, get_current_user, require_permission
from app.models.entities import User
from app.schemas.auth import (
    AddMemberRequest, InvitationRequest, InvitationResponse, JoinOrganizationRequest, 
    LoginRequest, PasswordResetConfirm, PasswordResetRequest, RegisterRequest, TokenResponse
)
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
    result = auth_service.join_organization(db, actor, payload.org_code)
    
    token = create_access_token(
        subject=str(result["user_id"]),
        org_id=result["org_id"],
        roles=[result["role_name"]]
    )
    return TokenResponse(access_token=token)
    

@router.post("/members")
def add_member(
    payload: AddMemberRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("org", "update")),
) -> dict:
    from app.models.entities import RoleType
         
    try:
        role_enum = RoleType(payload.role)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")

    membership = auth_service.add_organization_member(db, actor, payload.username, role_enum)
    return {"message": f"User {payload.username} added to organization", "membership_id": membership.id}


@router.post("/invitations", response_model=InvitationResponse)
def create_invitation(
    payload: InvitationRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("membership", "write")),
) -> InvitationResponse:
    from app.models.entities import RoleType
    from fastapi import HTTPException
    try:
        role_enum = RoleType(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")
        
    invitation, token = auth_service.create_invitation(db, actor, payload.email_or_username, role_enum)
    return InvitationResponse(
        invitation_id=invitation.id,
        token=token,
        expires_at=invitation.expires_at.isoformat()
    )


@router.delete("/invitations/{invitation_id}")
def revoke_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("membership", "write")),
) -> dict:
    auth_service.revoke_invitation(db, actor, invitation_id)
    return {"message": "Invitation revoked"}
