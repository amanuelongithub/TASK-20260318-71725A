import pytest
import io
from sqlalchemy import select
from fastapi.testclient import TestClient
from fastapi import UploadFile
from app.db.init_db import init_db
from app.models.entities import (
    Organization, User, Role, RoleType, OrganizationMembership, 
    Patient, Doctor, Appointment, ResourceApplication, CreditChange,
    Task, ProcessInstance
)
from app.core.security import create_access_token

@pytest.fixture
def setup_hospital_org(db):
    init_db(db)
    # Use org_id=10 for isolation
    org = Organization(id=10, org_code="HOSP_ORG_10", name="Hospital Org 10")
    db.add(org)
    db.flush()
    
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    user = User(username="hosp_admin_10", hashed_password="...", org_id=org.id, role_id=admin_role.id)
    db.add(user)
    db.flush()
    
    db.add(OrganizationMembership(user_id=user.id, org_id=org.id, role_id=admin_role.id))
    db.commit()
    
    token = create_access_token(subject=str(user.id), org_id=org.id, roles=["administrator"])
    headers = {"Authorization": f"Bearer {token}"}
    return org, user, headers

def test_patient_doctor_crud_isolated(client, db, setup_hospital_org):
    org, user, headers = setup_hospital_org
    
    # 1. Create Patient
    resp = client.post("/api/hospital/patients", json={
        "patient_number": "PAT-001",
        "full_name": "Alice Smith",
        "dob": "1990-01-01T00:00:00"
    }, headers=headers)
    assert resp.status_code == 200
    pat_id = resp.json()["id"]
    
    # 2. Patch Patient
    resp = client.patch(f"/api/hospital/patients/{pat_id}", json={
        "full_name": "Alice J. Smith"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Alice J. Smith"
    
    # 3. Create Doctor
    resp = client.post("/api/hospital/doctors", json={
        "license_number": "LIC-123",
        "full_name": "Dr. Bob",
        "specialty": "Cardiology",
        "is_active": True
    }, headers=headers)
    assert resp.status_code == 200
    doc_id = resp.json()["id"]
    
    # 4. Patch Doctor
    resp = client.patch(f"/api/hospital/doctors/{doc_id}", json={
        "specialty": "Neurology"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["specialty"] == "Neurology"

def test_multitenancy_linkage_validation(client, db, setup_hospital_org):
    org, user, headers = setup_hospital_org
    
    # Create an entity in ANOTHER org
    other_org = Organization(id=11, org_code="OTHER_ORG_11", name="Other Org 11")
    db.add(other_org)
    db.flush()
    
    # Foreign Patient
    other_pat = Patient(org_id=other_org.id, patient_number="PAT-FOREIGN", full_name="Foreigner")
    # Native Doctor
    doc_resp = client.post("/api/hospital/doctors", json={
        "license_number": "LIC-NATIVE",
        "full_name": "Native Doc",
        "specialty": "GP",
        "is_active": True
    }, headers=headers)
    doc_id = doc_resp.json()["id"]
    
    db.add(other_pat)
    db.commit()
    
    # Try to create an Appointment in org 10 linking to a patient in org 11
    resp = client.post("/api/hospital/appointments", json={
        "appointment_number": "APT-CROSS-ORG",
        "patient_id": other_pat.id,
        "doctor_id": doc_id,
        "status": "pending",
        "scheduled_time": "2024-01-01T10:00:00"
    }, headers=headers)
    
    # Expected to fail due to cross-org validation
    assert resp.status_code == 400
    assert "belong to your organization" in resp.json()["detail"]

def test_attachment_initiator_access(client, db, setup_hospital_org):
    org, user, headers = setup_hospital_org
    
    # 1. Create a Resource Application
    resp = client.post("/api/hospital/resource-applications", json={
        "application_number": "RES-OWNERSHIP",
        "resource_name": "Audit Sample",
        "quantity": 1,
        "status": "pending"
    }, headers=headers)
    assert resp.status_code == 200
    
    # 2. Upload attachment linked to RES-OWNERSHIP
    files = {"upload": ("sample.pdf", b"%PDF-1.4\n%test content", "application/pdf")}
    data = {"business_owner_id": "RES-OWNERSHIP"}
    resp = client.post("/api/files/upload", files=files, data=data, headers=headers)
    assert resp.status_code == 200
    at_id = resp.json()["attachment_id"]
    
    # 3. Verify access
    resp = client.get(f"/api/files/{at_id}", headers=headers)
    assert resp.status_code == 200
    
    # 4. Verify access denied for a different user in same org WITHOUT participation
    viewer_role = db.scalar(select(Role).where(Role.name == RoleType.GENERAL_USER))
    stranger = User(username="stranger_10", hashed_password="...", org_id=org.id, role_id=viewer_role.id)
    db.add(stranger)
    db.flush()
    db.add(OrganizationMembership(user_id=stranger.id, org_id=org.id, role_id=viewer_role.id))
    db.commit()
    
    stranger_token = create_access_token(subject=str(stranger.id), org_id=org.id, roles=["general_user"])
    stranger_headers = {"Authorization": f"Bearer {stranger_token}"}
    
    resp = client.get(f"/api/files/{at_id}", headers=stranger_headers)
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]

def test_auth_middleware_non_mutating(db, setup_hospital_org):
    from app.middleware.auth import get_current_user, AuthenticatedActor
    
    org, user, headers = setup_hospital_org
    
    # Record original org_id
    original_org_id = user.org_id
    
    payload = {"sub": str(user.id), "org_id": org.id}
    actor = get_current_user(payload=payload, db=db)
    
    # Assert result is the proxy, not the base model
    assert isinstance(actor, AuthenticatedActor)
    assert actor.org_id == org.id
    
    # Verify DB User instance in session is NOT mutated (one of the core audit findings)
    # Note: SQLAlchemy might have the object in session.
    db.refresh(user)
    assert user.org_id == original_org_id
