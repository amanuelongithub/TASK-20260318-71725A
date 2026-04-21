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


def get_current_user(payload: dict = Depends(get_current_token_payload), db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.id == int(payload.get("sub", 0)), User.org_id == int(payload.get("org_id", 0))))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_permission(resource: str, action: str):
    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        permission = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == user.role_id,
                RolePermission.resource == resource,
                RolePermission.action == action,
            )
        )
        if permission is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker
