import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from datetime import datetime, timedelta

from app.main import app
from app.models.entities import User, Organization, Role, RoleType, Patient, Doctor, Appointment, Expense, RolePermission, OrganizationMembership
from app.core.security import get_password_hash

@pytest.fixture
def setup_orgs_and_roles(db):
    # Setup Org 1
    org1 = db.scalar(select(Organization).where(Organization.org_code == "ORG1"))
    if not org1:
        org1 = Organization(org_code="ORG1", name="Organization 1")
        db.add(org1)
    
    # Setup Org 2
    org2 = db.scalar(select(Organization).where(Organization.org_code == "ORG2"))
    if not org2:
        org2 = Organization(org_code="ORG2", name="Organization 2")
        db.add(org2)
    
    db.commit()
    db.refresh(org1)
    db.refresh(org2)
    
    # Setup Roles
    roles = {}
    for rt in RoleType:
        role = db.scalar(select(Role).where(Role.name == rt))
        if not role:
            role = Role(name=rt)
            db.add(role)
            db.flush()
        roles[rt] = role
        
        # Grant hospital permissions to all roles for testing except they see masked data
        # We'll grant 'read', 'create', 'update'
        for action in ["read", "create", "update"]:
            exists = db.scalar(select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.resource == "hospital",
                RolePermission.action == action
            ))
            if not exists:
                db.add(RolePermission(role_id=role.id, resource="hospital", action=action))
    
    db.commit()
    return org1, org2, roles

@pytest.fixture
def test_users(db, setup_orgs_and_roles):
    org1, org2, roles = setup_orgs_and_roles
    
    # Org 1 Admin
    admin1 = db.scalar(select(User).where(User.username == "admin1"))
    if not admin1:
        admin1 = User(org_id=org1.id, role_id=roles[RoleType.ADMIN].id, username="admin1", hashed_password=get_password_hash("Pass123!"), is_active=True)
        db.add(admin1)
        db.flush()
        db.add(OrganizationMembership(user_id=admin1.id, org_id=org1.id, role_id=admin1.role_id, is_active=True))
        
    # Org 1 Reviewer (Non-Admin)
    reviewer1 = db.scalar(select(User).where(User.username == "reviewer1"))
    if not reviewer1:
        reviewer1 = User(org_id=org1.id, role_id=roles[RoleType.REVIEWER].id, username="reviewer1", hashed_password=get_password_hash("Pass123!"), is_active=True)
        db.add(reviewer1)
        db.flush()
        db.add(OrganizationMembership(user_id=reviewer1.id, org_id=org1.id, role_id=reviewer1.role_id, is_active=True))
        
    # Org 2 Admin
    admin2 = db.scalar(select(User).where(User.username == "admin2"))
    if not admin2:
        admin2 = User(org_id=org2.id, role_id=roles[RoleType.ADMIN].id, username="admin2", hashed_password=get_password_hash("Pass123!"), is_active=True)
        db.add(admin2)
        db.flush()
        db.add(OrganizationMembership(user_id=admin2.id, org_id=org2.id, role_id=admin2.role_id, is_active=True))
        
    db.commit()
    return {"admin1": admin1, "reviewer1": reviewer1, "admin2": admin2}

def get_auth_headers(client, username):
    response = client.post("/api/auth/login", json={
        "org_code": "ORG1" if "1" in username else "ORG2",
        "username": username,
        "password": "Pass123!"
    })
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

def test_hospital_filtering_and_privacy(client, db, test_users):
    headers_admin = get_auth_headers(client, "admin1")
    headers_reviewer = get_auth_headers(client, "reviewer1")
    
    # Seed Patients
    p1 = Patient(org_id=test_users["admin1"].org_id, patient_number="PN-001", full_name="John Doe", dob=datetime(1990, 1, 1))
    p2 = Patient(org_id=test_users["admin1"].org_id, patient_number="PN-002", full_name="Jane Smith", dob=datetime(1985, 5, 20))
    p3 = Patient(org_id=test_users["admin2"].org_id, patient_number="PN-003", full_name="Outside Patient", dob=datetime(2000, 1, 1))
    db.add_all([p1, p2, p3])
    db.commit()
    
    # 1. Combined Filtering Test (Patient)
    response = client.get("/api/hospital/patients?full_name=John&limit=10", headers=headers_admin)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["full_name"] == "John Doe"
    
    # 2. Privacy Test: Non-Admin (Reviewer) masked response
    response = client.get("/api/hospital/patients", headers=headers_reviewer)
    assert response.status_code == 200
    data = response.json()
    # John Doe -> J***, PN-001 -> PN-0* (masking logic check)
    # Check security.py for masking patterns
    # full_name: text[0] + "*" * (len(text) - 1) -> J******* (for John Doe)
    assert data[0]["full_name"].startswith("J")
    assert "*" in data[0]["full_name"]
    assert data[0]["patient_number"].startswith("PN-0")
    assert "*" in data[0]["patient_number"]

    # 3. Privacy Test: Admin unmasked response
    response = client.get("/api/hospital/patients", headers=headers_admin)
    assert response.json()[0]["full_name"] == "John Doe"
    
    # 4. Tenant Isolation Test
    # admin1 should not see p3
    assert all(d["full_name"] != "Outside Patient" for d in response.json())
    
    # 5. Mutation Masking Test (POST)
    response = client.post("/api/hospital/patients", json={
        "patient_number": "PN-NEW",
        "full_name": "New Patient",
        "dob": "1995-10-10T00:00:00"
    }, headers=headers_reviewer)
    assert response.status_code == 200
    assert response.json()["full_name"].startswith("N")
    assert "*" in response.json()["full_name"]

def test_hospital_sorting_and_pagination(client, db, test_users):
    headers = get_auth_headers(client, "admin1")
    
    # Clear existing if needed or just use fresh org logic
    # Actually just adding more
    for i in range(10):
        db.add(Expense(org_id=test_users["admin1"].org_id, expense_number=f"EXP-{i}", amount=100.0 + i, category="test", submitted_by=test_users["admin1"].id))
    db.commit()
    
    # Test Pagination
    response = client.get("/api/hospital/expenses?limit=5&offset=0&sort_by=amount&order=asc", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    assert data[0]["amount"] == 100.0
    
    response = client.get("/api/hospital/expenses?limit=5&offset=5&sort_by=amount&order=asc", headers=headers)
    assert len(response.json()) == 5
    assert response.json()[0]["amount"] == 105.0

def test_hospital_doctors_combined_search(client, db, test_users):
    headers = get_auth_headers(client, "admin1")
    db.add(Doctor(org_id=test_users["admin1"].org_id, license_number="LIC-A1", full_name="Alice Wang", specialty="Cardiology", is_active=True))
    db.add(Doctor(org_id=test_users["admin1"].org_id, license_number="LIC-B2", full_name="Bob Li", specialty="Neurology", is_active=True))
    db.commit()
    
    # Combined search
    response = client.get("/api/hospital/doctors?specialty=Cardiology&is_active=true", headers=headers)
    assert len(response.json()) == 1
    assert response.json()[0]["full_name"] == "Alice Wang"
    
    # Blind index search
    response = client.get("/api/hospital/doctors?license_number=LIC-B2", headers=headers)
    assert len(response.json()) == 1
    assert response.json()[0]["full_name"] == "Bob Li"
