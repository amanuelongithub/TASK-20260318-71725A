import pytest
from datetime import datetime, timedelta
from fastapi import status
from sqlalchemy import select, update
from app.models.entities import User, Organization, Role, RoleType, RolePermission, ProcessInstance, ProcessDefinition

@pytest.fixture
def test_admin_user(db):
    org = db.scalar(select(Organization).where(Organization.org_code == "FIX_ORG"))
    if not org:
        org = Organization(org_code="FIX_ORG", name="Fix Org")
        db.add(org)
    
    for rt in RoleType:
        role = db.scalar(select(Role).where(Role.name == rt))
        if not role:
            db.add(Role(name=rt))
    db.flush()
    
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    resources = ["metrics", "process", "users", "org", "data_governance"]
    for res in resources:
        for action in ["read", "write", "create", "update", "approve", "manage_members"]:
            db.add(RolePermission(role_id=admin_role.id, resource=res, action=action))
    db.flush()

    from app.core.security import get_password_hash
    user = User(
        org_id=org.id,
        role_id=admin_role.id,
        username="fix_admin",
        hashed_password=get_password_hash("FixPass123!"),
        is_active=True
    )
    db.add(user)
    db.flush()
    return user

@pytest.fixture
def auth_headers(client, test_admin_user):
    resp = client.post("/api/auth/login", json={
        "org_code": "FIX_ORG",
        "username": "fix_admin",
        "password": "FixPass123!"
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_workflow_start_success(client, auth_headers):
    resp = client.post(
        "/api/process/definitions",
        json={
            "name": "Test Workflow",
            "definition": {
                "first_node": "start",
                "nodes": {"start": {"timeout_hours": 24}},
                "assignees": {"start": ["role:administrator"]}
            }
        },
        headers=auth_headers
    )
    assert resp.status_code == 200
    def_id = resp.json()["id"]

    resp = client.post(
        "/api/process/instances",
        json={
            "process_definition_id": def_id,
            "business_id": "TEST-FIX-001",
            "idempotency_key": "ik-fix-001"
        },
        headers=auth_headers
    )
    assert resp.status_code == 200

def test_idempotency_24h_window(client, auth_headers, db):
    # Setup: Create def
    resp_def = client.post(
        "/api/process/definitions",
        json={"name": "Idem Workflow", "definition": {"first_node": "start", "nodes": {"start": {}}}},
        headers=auth_headers
    )
    def_id = resp_def.json()["id"]

    payload = {
        "process_definition_id": def_id, 
        "business_id": "IDEM-FIX-001",
        "idempotency_key": "ik-idem-fix-1"
    }
    
    # 1. First submission
    resp1 = client.post("/api/process/instances", json=payload, headers=auth_headers)
    id1 = resp1.json()["id"]
    
    # 2. Duplicate (same business_id) -> SAME
    resp2 = client.post("/api/process/instances", json=payload, headers=auth_headers)
    assert resp2.json()["id"] == id1
    
    # 3. Manually update in DB. Use RAW connection to avoid session issues.
    from sqlalchemy import text
    db.execute(text("UPDATE process_instances SET created_at = :dt WHERE id = :id"), {"dt": datetime.utcnow() - timedelta(hours=25), "id": id1})
    db.commit()
    
    # 4. Submission after 24h -> NEW
    # We must refresh the login since commit might have messed up the token check if it re-validates user
    resp3 = client.post("/api/process/instances", json=payload, headers=auth_headers)
    assert resp3.status_code == 200
    assert resp3.json()["id"] != id1

def test_add_member_and_join_flow(client, auth_headers, db):
    from app.core.security import get_password_hash
    new_user = User(
        org_id=1, 
        role_id=1,
        username="newmember",
        hashed_password=get_password_hash("NewPass123!"),
    )
    db.add(new_user)
    db.flush()

    resp = client.post(
        "/api/auth/members",
        json={"username": "newmember", "role": "general_user"},
        headers=auth_headers
    )
    assert resp.status_code == 200
    
    from app.models.entities import OrganizationMembership
    m = db.query(OrganizationMembership).filter_by(user_id=new_user.id).first()
    assert m is not None

def test_custom_reporting(client, auth_headers):
    resp = client.post(
        "/api/metrics/reports/custom",
        json={"metric_types": ["sla", "expenses"]},
        headers=auth_headers
    )
    assert resp.status_code == 200
