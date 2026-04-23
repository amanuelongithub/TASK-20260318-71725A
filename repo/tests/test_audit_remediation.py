import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db.session import SessionLocal
from app.models.entities import User, Organization, Role, RoleType, OrganizationMembership, TokenBlacklist
from app.core.config import settings
from app.core.security import create_access_token

from sqlalchemy.orm import Session

@pytest.fixture
def test_setup(db: Session):
    # Ensure tables are ready and seed permissions
    from app.db.init_db import init_db
    init_db(db)
    
    from app.models.entities import Role, RoleType, Organization, User, OrganizationMembership
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    gen_role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))

    # Setup Org
    org = db.scalar(select(Organization).where(Organization.org_code == "audit_test"))
    if not org:
        org = Organization(org_code="audit_test", name="Audit Test Org")
        db.add(org)
        db.commit()
        db.refresh(org)

    # Setup User
    user = db.scalar(select(User).where(User.username == "audit_user"))
    if not user:
        from app.core.security import get_password_hash
        user = User(
            org_id=org.id,
            role_id=gen_role.id,
            username="audit_user",
            hashed_password=get_password_hash("password123"),
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
        db.add(OrganizationMembership(user_id=user.id, org_id=org.id, role_id=gen_role.id, is_active=True))
        db.commit()

    return org, user

def test_login_membership_enforcement(db, client, test_setup):
    org, user = test_setup
    
    # 1. Successful login
    response = client.post("/api/auth/login", json={
        "org_code": org.org_code,
        "username": user.username,
        "password": "password123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
    
    # 2. Login to wrong org (no membership)
    from app.models.entities import Organization
    other_org = Organization(org_code="no_member_org", name="No Member")
    db.add(other_org)
    db.commit()
    
    response = client.post("/api/auth/login", json={
        "org_code": "no_member_org",
        "username": user.username,
        "password": "password123"
    })
    assert response.status_code == 401
    assert "member" in response.json()["detail"].lower()

def test_account_lockout_policy(db, client, test_setup):
    org, user = test_setup
    
    # Reset attempts
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    
    # 5 Failed attempts
    for _ in range(5):
        client.post("/api/auth/login", json={
            "org_code": org.org_code,
            "username": user.username,
            "password": "wrong_password"
        })
    
    # Next attempt should be locked
    response = client.post("/api/auth/login", json={
        "org_code": org.org_code,
        "username": user.username,
        "password": "password123"
    })
    assert response.status_code == 423
    assert "locked" in response.json()["detail"].lower()

def test_file_validation_magic_numbers(db, client, test_setup):
    org, user = test_setup
    from app.models.entities import RoleType
    token = create_access_token(subject=str(user.id), org_id=org.id, roles=[RoleType.GENERAL_USER.value])
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Valid PDF
    files = {"upload": ("test.pdf", b"%PDF-1.4\ncontent", "application/pdf")}
    response = client.post("/api/files/upload", files=files, headers=headers)
    assert response.status_code == 200
    
    # 2. Invalid PDF (Spoofed extension)
    files = {"upload": ("spoof.pdf", b"NOT-A-PDF", "application/pdf")}
    response = client.post("/api/files/upload", files=files, headers=headers)
    assert response.status_code == 400
    assert "format" in response.json()["detail"].lower()

def test_object_level_authorization_hospital(db, client, test_setup):
    org, user = test_setup
    from app.models.entities import RoleType, Role, RolePermission
    
    # Verify permission was seeded by test_setup
    perm = db.scalar(select(RolePermission).join(Role).where(
        Role.name == RoleType.GENERAL_USER,
        RolePermission.resource == "hospital",
        RolePermission.action == "update"
    ))
    assert perm is not None, "Hospital update permission not found for GENERAL_USER"

    token = create_access_token(subject=str(user.id), org_id=org.id, roles=[RoleType.GENERAL_USER.value])
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create a patient owned by someone else
    from app.models.entities import Patient
    other_patient = Patient(org_id=org.id, user_id=999, full_name="Other Patient")
    other_patient.patient_number = "PAT-999"
    db.add(other_patient)
    db.commit()
    
    # Try to update other patient
    response = client.patch(f"/api/hospital/patients/{other_patient.id}", json={"full_name": "Hack"}, headers=headers)
    
    # If it fails with 403, we check the message
    if response.status_code == 403:
         detail = response.json()["detail"].lower()
         # It could be either middleware blocking or our object-level logic
         assert "own" in detail or "insufficient" in detail
    else:
         pytest.fail(f"Expected 403, got {response.status_code}: {response.text}")

def test_audit_traceability_flushing(db, client, test_setup):
    # This test verifies that log_event gets the ID from a flushed object
    from app.services.audit_service import log_event
    from app.models.entities import Attachment
    
    org, user = test_setup
    row = Attachment(org_id=org.id, uploader_id=user.id, filename="trace.txt", sha256="abc", storage_path="/tmp/trace", file_size=100)
    db.add(row)
    db.flush()
    
    assert row.id is not None
    log_event(db, org.id, user.id, "test.trace", {"id": row.id})
    db.commit()
    
    from app.models.entities import AuditLog
    log_entry = db.scalar(select(AuditLog).where(AuditLog.event == "test.trace"))
    assert log_entry.event_metadata["id"] == row.id
