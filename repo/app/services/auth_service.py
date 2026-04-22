from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decrypt_field, deterministic_hash, encrypt_field, get_password_hash, verify_password
from app.models.entities import Organization, OrganizationMembership, Role, RoleType, User, OrganizationInvitation
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.audit_service import log_event

MAX_ATTEMPTS = 5
LOCK_DURATION_MINUTES = 30


def register(db: Session, payload: RegisterRequest) -> User:
    # STRICT TENANT ISOLATION: Registration is for:
    # 1. Creating a brand new organization (standard registration)
    # 2. Joining an existing organization ONLY with a valid invitation token.
    
    target_org = db.scalar(select(Organization).where(Organization.org_code == payload.org_code))
    
    invitation = None
    if payload.invitation_token:
        # Resolve invitation
        token_hash = deterministic_hash(payload.invitation_token)
        invitation = db.scalar(
            select(OrganizationInvitation).where(
                OrganizationInvitation.token_hash == token_hash,
                OrganizationInvitation.revoked_at.is_(None),
                OrganizationInvitation.used_at.is_(None)
            )
        )
        if not invitation:
            raise HTTPException(status_code=400, detail="Invalid, used, or revoked invitation token")
        if invitation.expires_at < datetime.utcnow():
            log_event(db, invitation.org_id, None, "auth.invitation_expired", {"invitation_id": invitation.id})
            db.commit()
            raise HTTPException(status_code=400, detail="Invitation token has expired")
        
        # Ensure org matches
        if target_org and target_org.id != invitation.org_id:
             raise HTTPException(status_code=400, detail="Invitation token does not match the organization code")
        
        # If invitation is valid but org.id doesn't match payload.org_code in DB, 
        # it means the invitation is for an org that exists, so target_org SHOULD exist.
        if not target_org:
            target_org = db.scalar(select(Organization).where(Organization.id == invitation.org_id))
    
    elif target_org:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict: Organization code already registered. To join an existing organization, please use an invitation link or contact your administrator."
        )
    
    if not target_org:
        # Create new organization
        target_org = Organization(org_code=payload.org_code, name=payload.org_name)
        db.add(target_org)
        db.flush()

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

    # If it's a brand new org, the first user is ADMIN. 
    # If it's an invitation, we use the invitation role.
    # Otherwise, GENERAL_USER.
    from sqlalchemy import func
    user_count = db.scalar(select(func.count(User.id)).where(User.org_id == target_org.id))
    
    if invitation:
        assigned_role_id = invitation.role_id
    else:
        assigned_role_id = admin_role.id if (user_count == 0) else general_role.id

    user = User(
        org_id=target_org.id,
        role_id=assigned_role_id,
        username=payload.username,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        email_encrypted=encrypt_field(payload.email) if payload.email else None,
    )
    db.add(user)
    db.flush()
    
    db.add(OrganizationMembership(user_id=user.id, org_id=target_org.id, role_id=assigned_role_id))
    
    if invitation:
        invitation.used_at = datetime.utcnow()
        log_event(db, target_org.id, user.id, "auth.invitation_accepted", {"invitation_id": invitation.id})
    
    log_event(db, org_id=target_org.id, actor_id=None, event="auth.register", metadata={"username": payload.username, "role_id": assigned_role_id})
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


def join_organization(db: Session, actor: User, org_code: str) -> dict:
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
    
    # Resolve effective role for this organization context
    role_name = "general_user"
    if membership.role_id:
        role = db.scalar(select(Role).where(Role.id == membership.role_id))
        if role:
            role_name = role.name.value
    log_event(db, target_org.id, actor.id, "auth.join_org", {"org_code": org_code})
    db.commit()
    return {
        "user_id": actor.id,
        "org_id": target_org.id,
        "role_name": role_name
    }


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


def add_organization_member(db: Session, admin_actor: User, username: str, role_name: RoleType = RoleType.GENERAL_USER) -> OrganizationMembership:
    # Verify target user exists
    target_user = db.scalar(select(User).where(User.username == username))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found. To add a new user to the system, please use the invitation flow.")
    
    # Verify role exists
    role = db.scalar(select(Role).where(Role.name == role_name))
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    # Check if already a member
    existing = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == target_user.id,
            OrganizationMembership.org_id == admin_actor.org_id
        )
    )
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=409, detail="User is already a member of this organization")
        existing.is_active = True
        existing.role_id = role.id
        membership = existing
    else:
        membership = OrganizationMembership(
            user_id=target_user.id,
            org_id=admin_actor.org_id,
            role_id=role.id,
            is_active=True
        )
        db.add(membership)
    
    log_event(db, admin_actor.org_id, admin_actor.id, "auth.member_added", {"target_username": username, "role": role_name.value})
    db.commit()
    db.refresh(membership)
    return membership


def create_invitation(db: Session, admin: User, email_or_username: str, role_type: RoleType) -> tuple[OrganizationInvitation, str]:
    import secrets
    
    role = db.scalar(select(Role).where(Role.name == role_type))
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role")
        
    token = secrets.token_urlsafe(32)
    token_hash = deterministic_hash(token)
    
    invitation = OrganizationInvitation(
        org_id=admin.org_id,
        email_or_username=email_or_username,
        role_id=role.id,
        token_hash=token_hash,
        expires_at=datetime.utcnow() + timedelta(days=7),
        created_by=admin.id
    )
    db.add(invitation)
    log_event(db, admin.org_id, admin.id, "auth.invitation_created", {"target": email_or_username, "role": role_type.value})
    db.commit()
    db.refresh(invitation)
    return invitation, token


def revoke_invitation(db: Session, admin: User, invitation_id: int) -> None:
    invitation = db.scalar(select(OrganizationInvitation).where(OrganizationInvitation.id == invitation_id, OrganizationInvitation.org_id == admin.org_id))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.revoked_at or invitation.used_at:
        raise HTTPException(status_code=400, detail="Invitation already processed or revoked")
        
    invitation.revoked_at = datetime.utcnow()
    log_event(db, admin.org_id, admin.id, "auth.invitation_revoked", {"invitation_id": invitation_id})
    db.commit()
