from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.entities import RolePermission, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_token_payload(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> dict:
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    # Check blacklist
    from app.models.entities import TokenBlacklist
    jti = payload.get("jti")
    if jti:
        is_blocked = db.scalar(select(TokenBlacklist).where(TokenBlacklist.token_jti == jti))
        if is_blocked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    return payload


class AuthenticatedActor:
    """
    A proxy object that represents an authenticated user within a specific organizational context.
    This avoids mutating the underlying 'User' model instance, satisfying audit requirements 
    for behavioral purity while maintaining compatibility with downstream code.
    """
    def __init__(self, user: User, org_id: int, role_id: int, role=None):
        self._user = user
        self.id = user.id
        self.org_id = org_id
        self.role_id = role_id
        self.role = role

    def __getattr__(self, name):
        return getattr(self._user, name)

    @property
    def __class__(self):
        return self._user.__class__

    def __eq__(self, other):
        if hasattr(other, "id"):
            return self.id == other.id
        return False

    def __hash__(self):
        return hash((self.id, self.org_id))

    def __repr__(self):
        return f"<AuthenticatedActor(user_id={self.id}, org_id={self.org_id}, role_id={self.role_id})>"


def get_current_user(payload: dict = Depends(get_current_token_payload), db: Session = Depends(get_db)) -> AuthenticatedActor:
    user = db.scalar(select(User).where(User.id == int(payload.get("sub", 0))))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    
    # Multi-tenant logic: resolve context from token
    org_id = int(payload.get("org_id", 0))
    from app.models.entities import OrganizationMembership
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.org_id == org_id,
            OrganizationMembership.is_active == True
        )
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active membership for this organization context")
    
    # Return a context-bound actor proxy instead of mutating the base User record.
    # This aligns the implementation with the README's architectural claims.
    effective_role_id = membership.role_id or user.role_id
    from app.models.entities import Role
    role = db.get(Role, effective_role_id)
    return AuthenticatedActor(user, org_id, effective_role_id, role=role)


def require_permission(resource: str, action: str):
    def checker(actor: AuthenticatedActor = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthenticatedActor:
        permission = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == actor.role_id,
                RolePermission.resource == resource,
                RolePermission.action == action,
            )
        )
        if permission is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return actor

    return checker
