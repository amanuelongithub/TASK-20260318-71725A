import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models.entities import User, Organization, Role, RoleType, ExportJob, RolePermission

@pytest.fixture
def test_user(db):
    org = db.scalar(select(Organization).where(Organization.org_code == "TEST_ORG"))
    if not org:
        org = Organization(org_code="TEST_ORG", name="Test Org")
        db.add(org)
        db.flush()
    
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if not admin_role:
        admin_role = Role(name=RoleType.ADMIN)
        db.add(admin_role)
        db.flush()

    # Seed permissions for ADMIN role
    resources = ["metrics", "export", "audit", "data_governance", "files", "process", "hospital", "users"]
    for res in resources:
        for action in ["read", "write", "delete", "admin"]:
            existing_perm = db.scalar(select(RolePermission).where(
                RolePermission.role_id == admin_role.id,
                RolePermission.resource == res,
                RolePermission.action == action
            ))
            if not existing_perm:
                db.add(RolePermission(role_id=admin_role.id, resource=res, action=action))
    db.flush()

    user = db.scalar(select(User).where(User.username == "test_audit_admin"))
    if not user:
        from app.core.security import get_password_hash
        user = User(
            org_id=org.id,
            role_id=admin_role.id,
            username="test_audit_admin",
            hashed_password=get_password_hash("TestPass123!"),
            is_active=True
        )
        db.add(user)
        db.flush()
    
    db.commit()
    return user

def get_token(client, user_username):
    response = client.post("/api/auth/login", json={
        "org_code": "TEST_ORG",
        "username": user_username,
        "password": "TestPass123!"
    })
    return response.json()["access_token"]

def test_export_download_endpoint(client, test_user, db):
    token = get_token(client, test_user.username)
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create a dummy completed job
    import os
    dummy_file = "test_export.csv"
    with open(dummy_file, "w") as f:
        f.write("test,data")
    
    job = ExportJob(
        org_id=test_user.org_id,
        requested_by=test_user.id,
        status="completed",
        output_path=os.path.abspath(dummy_file),
        fields={"columns": ["test"]}
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # 2. Test download
    response = client.get(f"/api/export/jobs/{job.id}/download", headers=headers)
    assert response.status_code == 200
    assert response.content == b"test,data"
    
    # Cleanup
    os.remove(dummy_file)

def test_password_reset_flow(client, db, test_user):
    # This test primarily verifies the endpoint doesn't crash and returns success
    response = client.post("/api/auth/password-reset/request", json={
        "org_code": "TEST_ORG",
        "username": "test_audit_admin"
    })
    assert response.status_code == 200
    assert "reset token has been generated" in response.json()["message"]

def test_advanced_metrics(client, test_user):
    token = get_token(client, test_user.username)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/metrics/reports/advanced", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "sla_compliance_rate" in data
    assert "activity_24h" in data

def test_response_desensitization_me(client, test_user):
    token = get_token(client, test_user.username)
    headers = {"Authorization": f"Bearer {token}"}
    
    response = client.get("/api/users/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "email" in data

def test_data_governance_lineage_rbac(client, test_user, db):
    token = get_token(client, test_user.username)
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test read permission on lineage - FIXED path
    response = client.get("/api/data-governance/lineage/expense/EXP-123", headers=headers)
    # Should be 200 if ADMIN has 'read'
    assert response.status_code == 200
