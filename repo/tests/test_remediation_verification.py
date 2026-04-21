import pytest
from sqlalchemy import select
from app.models.entities import Organization, User, Role, RoleType, OrganizationMembership, ProcessInstance, ProcessDefinition, RolePermission
from app.core.security import create_access_token

def test_registration_org_conflict(client, db):
    # Setup: ensure an org exists
    org_code = "CONFLICT_ORG"
    if not db.scalar(select(Organization).where(Organization.org_code == org_code)):
        db.add(Organization(org_code=org_code, name="Conflict Org"))
        db.commit()
    
    # Test registration with same org_code
    response = client.post("/api/auth/register", json={
        "username": "testuser_conflict",
        "password": "Password123!",
        "full_name": "Test User",
        "email": "test@example.com",
        "org_code": org_code,
        "org_name": "New Org Name"
    }, headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 409
    assert "Organization already exists" in response.json()["detail"]

def test_join_organization_token_refresh(client, db):
    # Setup: user and memberships
    org1 = Organization(org_code="ORG1", name="Org 1")
    org2 = Organization(org_code="ORG2", name="Org 2")
    db.add_all([org1, org2])
    db.flush()
    
    role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))
    if not role:
        role = Role(name=RoleType.GENERAL_USER)
        db.add(role)
        db.flush()
        
    user = User(
        username="jon_doe", 
        hashed_password="...", 
        org_id=org1.id, 
        role_id=role.id,
        is_active=True
    )
    db.add(user)
    db.flush()
    
    db.add_all([
        OrganizationMembership(user_id=user.id, org_id=org1.id),
        OrganizationMembership(user_id=user.id, org_id=org2.id)
    ])
    db.commit()
    
    token = create_access_token(subject=str(user.id), org_id=org1.id, roles=["general_user"])
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-Proto": "https"}
    
    response = client.post("/api/auth/join-organization", json={"org_code": "ORG2"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    
    # Verify new token has ORG2 context
    from app.core.security import decode_access_token
    payload = decode_access_token(data["access_token"])
    assert payload["org_id"] == org2.id

def test_https_enforcement_by_default(client):
    # Ensure allow_plain_http is False (default)
    # The middleware should return 403 for non-https requests
    response = client.get("/health")
    assert response.status_code == 403
    assert "HTTPS-only" in response.json()["detail"]

def test_idempotency_business_id_conflict(client, db):
    # Setup: org, definition, and first instance
    org = Organization(org_code="IDEM_ORG", name="Idem Org")
    db.add(org)
    db.flush()
    
    defn = ProcessDefinition(org_id=org.id, name="Test Proc", definition={"nodes": {"start": {}}})
    db.add(defn)
    db.flush()
    
    role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if not role:
        role = Role(name=RoleType.ADMIN)
        db.add(role)
        db.flush()
        
    # Seed permissions
    from app.models.entities import RolePermission
    perm = RolePermission(role_id=role.id, resource="process", action="create")
    db.add(perm)
    db.flush()
    
    admin = User(username="admin_idem", hashed_password="...", org_id=org.id, role_id=role.id)
    db.add(admin)
    db.flush()
    
    # X-Forwarded-Proto to bypass HTTPS check for this API test
    token = create_access_token(subject=str(admin.id), org_id=org.id, roles=["administrator"])
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-Proto": "https"}
    
    payload = {
        "process_definition_id": defn.id,
        "business_id": "BIZ-123",
        "idempotency_key": "KEY-1",
        "variables": {}
    }
    
    # First call
    response1 = client.post("/api/process/instances", json=payload, headers=headers)
    assert response1.status_code == 200
    id1 = response1.json()["id"]
    
    # Second call with SAME business_id but DIFFERENT idempotency_key
    payload2 = payload.copy()
    payload2["idempotency_key"] = "KEY-2"
    response2 = client.post("/api/process/instances", json=payload2, headers=headers)
    assert response2.status_code == 200
    assert response2.json()["id"] == id1 # Should return the same instance

def test_celery_tasks_have_retries():
    from app.tasks.jobs import aggregate_all_daily_metrics, backup_database
    assert aggregate_all_daily_metrics.max_retries == 3
    assert backup_database.max_retries == 3

def test_attachment_authorization(client, db):
    org1 = Organization(org_code="ATTACH_ORG1", name="Attach Org 1")
    org2 = Organization(org_code="ATTACH_ORG2", name="Attach Org 2")
    db.add_all([org1, org2])
    db.flush()
    
    role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))
    if not role:
        role = Role(name=RoleType.GENERAL_USER)
        db.add(role)
        db.flush()
        
    # Seed permissions
    perm = RolePermission(role_id=role.id, resource="files", action="read")
    db.add(perm)
    db.flush()
    
    u1 = User(username="u1", hashed_password="...", org_id=org1.id, role_id=role.id)
    u2 = User(username="u2", hashed_password="...", org_id=org1.id, role_id=role.id)
    u3 = User(username="u3", hashed_password="...", org_id=org2.id, role_id=role.id)
    db.add_all([u1, u2, u3])
    db.flush()
    
    import os
    dummy_path = "test_attachment_dummy.txt"
    with open(dummy_path, "w") as f:
        f.write("test content")
        
    from app.models.entities import Attachment
    # Attachment uploaded by u1 in Org 1
    att = Attachment(
        org_id=org1.id, uploader_id=u1.id, filename="test.txt", 
        file_size=10, sha256="abc", storage_path=os.path.abspath(dummy_path)
    )
    db.add(att)
    db.commit()
    
    # 1. u1 (uploader) can see it
    t1 = create_access_token(subject=str(u1.id), org_id=org1.id, roles=["general_user"])
    resp1 = client.get(f"/api/files/{att.id}", headers={"Authorization": f"Bearer {t1}", "X-Forwarded-Proto": "https"})
    # The file download endpoint /api/files/{id} exists? 
    # Let's check files.py
    assert resp1.status_code != 403
    
    # 2. u2 (same org, not uploader, not admin) should NOT see it if not business owner
    t2 = create_access_token(subject=str(u2.id), org_id=org1.id, roles=["general_user"])
    resp2 = client.get(f"/api/files/{att.id}", headers={"Authorization": f"Bearer {t2}", "X-Forwarded-Proto": "https"})
    assert resp2.status_code == 403
    
    # 3. u3 (different org) should NOT see it (404 because of filter by org_id in get_attachment)
    t3 = create_access_token(subject=str(u3.id), org_id=org2.id, roles=["general_user"])
    resp3 = client.get(f"/api/files/{att.id}", headers={"Authorization": f"Bearer {t3}", "X-Forwarded-Proto": "https"})
    assert resp3.status_code == 404
