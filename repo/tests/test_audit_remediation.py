import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db.session import SessionLocal
from app.models.entities import User, Organization, Role, RoleType, OrganizationMembership, TokenBlacklist
from app.core.config import settings
from app.core.security import create_access_token

client = TestClient(app)

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def test_setup(db):
    # Setup roles
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if not admin_role:
        admin_role = Role(name=RoleType.ADMIN)
        db.add(admin_role)
    
    gen_role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))
    if not gen_role:
        gen_role = Role(name=RoleType.GENERAL_USER)
        db.add(gen_role)
    db.commit()

    # Setup Org
    org = db.scalar(select(Organization).where(Organization.org_code == "audit_test"))
    if not org:
        org = Organization(org_code="audit_test", name="Audit Test Org")
        db.add(org)
        db.commit()
        db.refresh(org)

    # Setup User
    user = db.scalar(select(User).where(User.username == "audit_user", User.org_id == org.id))
    if not user:
        user = User(
            org_id=org.id,
            role_id=gen_role.id,
            username="audit_user",
            hashed_password="fake",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Membership
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.user_id == user.id, 
        OrganizationMembership.org_id == org.id
    ))
    if not membership:
        db.add(OrganizationMembership(user_id=user.id, org_id=org.id))
        db.commit()

    return org, user

def test_logout_token_invalidation(db, test_setup):
    org, user = test_setup
    token = create_access_token(subject=str(user.id), org_id=org.id, roles=[RoleType.GENERAL_USER.value])
    headers = {"Authorization": f"Bearer {token}"}

    # Verify we can access a protected route
    response = client.get("/api/users/me", headers=headers)
    assert response.status_code == 200

    # Logout
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 200

    # Verify we can NO LONGER access the route
    response = client.get("/api/users/me", headers=headers)
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()

def test_password_reset_invalid_token_status(db, test_setup):
    org, user = test_setup
    payload = {
        "org_code": org.org_code,
        "token": "invalid-or-expired-token",
        "new_password": "new_secure_password123"
    }
    response = client.post("/api/auth/password-reset/confirm", json=payload)
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()

def test_https_enforcement_in_acceptance(db, test_setup, monkeypatch):
    monkeypatch.setattr("app.main.settings.environment", "acceptance")
    
    # Try access with HTTP (scheme will be http in testclient by default for root_url)
    response = client.get("/api/health") # Health is exempt in some configs but main.py adds middleware to all routes
    # Middleware check: if not is_https and forwarded_proto != "https": raise 403
    
    # TestClient requests are often 'http' unless configured. 
    # Let's verify middleware logic.
    assert response.status_code == 403
    assert "HTTPS required" in response.json()["detail"]

def test_org_join_unauthorized(db, test_setup):
    org, user = test_setup
    token = create_access_token(subject=str(user.id), org_id=org.id, roles=[RoleType.GENERAL_USER.value])
    headers = {"Authorization": f"Bearer {token}"}

    # Create another org
    other_org = db.scalar(select(Organization).where(Organization.org_code == "other_org"))
    if not other_org:
        other_org = Organization(org_code="other_org", name="Other Org")
        db.add(other_org)
        db.commit()
        db.refresh(other_org)

    # Try to join WITHOUT membership record
    response = client.post("/api/auth/join-organization", json={"org_code": "other_org"}, headers=headers)
    assert response.status_code == 403
    assert "membership" in response.json()["detail"].lower()
