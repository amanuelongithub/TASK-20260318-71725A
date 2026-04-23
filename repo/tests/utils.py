import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.models.entities import User, Organization, Role, RoleType, OrganizationMembership
from app.core.security import get_password_hash

def create_test_org(db: Session, org_code: str) -> Organization:
    org = Organization(org_code=org_code, name=f"Test Org {org_code}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org

def create_test_user(db: Session, org_id: int, username: str = "test_user", role_name: RoleType = RoleType.GENERAL_USER) -> User:
    role = db.scalar(sa.select(Role).where(Role.name == role_name))
    if not role:
        # Fallback if not seeded
        role = Role(name=role_name)
        db.add(role)
        db.commit()
        db.refresh(role)
        
    user = User(
        org_id=org_id,
        role_id=role.id,
        username=username,
        hashed_password=get_password_hash("password123"),
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Also create membership
    db.add(OrganizationMembership(user_id=user.id, org_id=org_id, role_id=role.id, is_active=True))
    db.commit()
    
    return user
