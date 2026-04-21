from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decrypt_field, encrypt_field, get_password_hash, verify_password
from app.models.entities import Organization, Role, RoleType, User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.audit_service import log_event

MAX_ATTEMPTS = 5
LOCK_DURATION_MINUTES = 30


def register(db: Session, payload: RegisterRequest) -> User:
    # STRICT TENANT ISOLATION: Registration is ONLY for creating new organizations.
    # Joining existing organizations must go through the authorized invitation path.
    org_exists = db.scalar(select(Organization).where(Organization.org_code == payload.org_code))
    if org_exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Organization code already registered. To join an existing organization, please use an invitation link or contact your administrator."
        )
    
    org = Organization(org_code=payload.org_code, name=payload.org_name)
    db.add(org)
    db.flush() # Ensure org.id is available for role checks

    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if admin_role is None:
        admin_role = Role(name=RoleType.ADMIN)
        db.add(admin_role)
        db.flush()

    general_role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))
    if general_role is None:
        general_role = Role(name=RoleType.GENERAL_USER)
        db.add(general_role)
        db.flush()

    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail="Username already exists")

    # If it's a brand new org, the first user is ADMIN. Otherwise, GENERAL_USER.
    # Note: org.created_at check or simply checking if any users exist in org.
    from sqlalchemy import func
    user_count = db.scalar(select(func.count(User.id)).where(User.org_id == org.id))
    assigned_role_id = admin_role.id if (user_count == 0) else general_role.id

    user = User(
        org_id=org.id,
        role_id=assigned_role_id,
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        email_encrypted=encrypt_field(payload.email) if payload.email else None,
    )
    db.add(user)
    db.flush()
    
    from app.models.entities import OrganizationMembership
    db.add(OrganizationMembership(user_id=user.id, org_id=org.id))
    
    log_event(db, org_id=org.id, actor_id=None, event="auth.register", metadata={"username": payload.username, "role": "admin" if user_count == 0 else "user"})
    db.commit()
    db.refresh(user)
    return user


def login(db: Session, payload: LoginRequest) -> str:
    org = db.scalar(select(Organization).where(Organization.org_code == payload.org_code))
    user = db.scalar(select(User).where(User.org_id == (org.id if org else -1), User.username == payload.username))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    now = datetime.utcnow()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=423, detail="Account is locked")

    if not verify_password(payload.password, user.hashed_password):
        if user.last_failed_login and (now - user.last_failed_login) > timedelta(minutes=10):
            user.failed_login_attempts = 1
        else:
            user.failed_login_attempts += 1
            
        user.last_failed_login = now
        
        if user.failed_login_attempts >= MAX_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCK_DURATION_MINUTES)
            user.failed_login_attempts = 0
            user.last_failed_login = None
            
        log_event(db, user.org_id, user.id, "auth.login_failed", {"username": user.username})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.failed_login_attempts = 0
    user.last_failed_login = None
    user.locked_until = None
    log_event(
        db,
        user.org_id,
        user.id,
        "auth.login_success",
        {"username": user.username},
    )
    db.commit()
    role_name = user.role.name.value if user.role else RoleType.GENERAL_USER.value
    return create_access_token(subject=str(user.id), org_id=user.org_id, roles=[role_name])


def request_password_reset(db: Session, org_code: str, username: str) -> str | None:
    org = db.scalar(select(Organization).where(Organization.org_code == org_code))
    user = db.scalar(select(User).where(User.org_id == (org.id if org else -1), User.username == username))
    if not user:
        return None
    
    import secrets
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    
    # Audit logic
    log_event(db, user.org_id, user.id, "auth.password_reset_requested", {"username": user.username})
    
    # Simulate delivery via log - SECURITY FIX: token no longer logged in clear text
    import logging
    logger = logging.getLogger("app.auth")
    logger.warning(f"PASSWORD RESET REQUESTED for {username}. Link: /api/auth/password-reset/confirm?org_code={org_code}")
    
    db.commit()
    return token



def reset_password(db: Session, org_code: str, token: str, new_password: str) -> bool:
    org = db.scalar(select(Organization).where(Organization.org_code == org_code))
    user = db.scalar(select(User).where(User.org_id == (org.id if org else -1), User.reset_token == token))
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        return False
    
    user.hashed_password = get_password_hash(new_password)
    user.reset_token = None
    user.reset_token_expires = None
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    return True


def join_organization(db: Session, actor: User, org_code: str) -> bool:
    from app.models.entities import Organization, OrganizationMembership, Role, RoleType
    target_org = db.scalar(select(Organization).where(Organization.org_code == org_code))
    if not target_org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # Check if a membership exists
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == actor.id,
            OrganizationMembership.org_id == target_org.id,
            OrganizationMembership.is_active == True
        )
    )
    if not membership:
        raise HTTPException(
            status_code=403, 
            detail="You do not have a valid membership or invitation for this organization."
        )
    
    # Update user's ACTIVE context to this organization.
    # The role is now sourced from the membership table if available.
    if membership.role_id:
        actor.role_id = membership.role_id
    else:
        # Fallback to general user if no specific role in this org
        general_role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))
        if general_role:
            actor.role_id = general_role.id
    
    actor.org_id = target_org.id
    db.add(actor)
    log_event(db, target_org.id, actor.id, "auth.join_org", {"org_code": org_code})
    db.commit()
    db.refresh(actor)

    return actor


def logout_event(db: Session, actor: User, token_payload: dict) -> None:
    from app.models.entities import TokenBlacklist
    jti = token_payload.get("jti")
    exp = token_payload.get("exp")
    if jti:
        if exp:
            expires_at = datetime.fromtimestamp(exp)
        else:
            expires_at = datetime.utcnow() + timedelta(hours=1)
            
        db.add(TokenBlacklist(token_jti=jti, expires_at=expires_at))
        
    log_event(db, actor.org_id, actor.id, "auth.logout", {})
    db.commit()
