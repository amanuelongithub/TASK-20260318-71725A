import pytest
from sqlalchemy import select
from app.models.entities import Organization, User, Role, RoleType, OrganizationMembership, Patient, Doctor, Appointment, Expense, ResourceApplication, CreditChange, DataVersion
from app.services import data_governance_service
from app.core.security import deterministic_hash

@pytest.fixture
def test_data(db):
    from app.db.init_db import init_db
    init_db(db)
    org = db.scalar(select(Organization).where(Organization.org_code == "audit_test"))
    if not org:
        org = Organization(org_code="audit_test", name="Audit Test Org")
        db.add(org)
    db.flush()
    
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    user = db.scalar(select(User).where(User.username == "admin_user"))
    if not user:
        user = User(org_id=org.id, role_id=admin_role.id, username="admin_user", hashed_password="...")
        db.add(user)
    
    db.flush()
    db.add(OrganizationMembership(user_id=user.id, org_id=org.id, role_id=admin_role.id, is_active=True))
    db.commit()
    return org, user

def test_rollback_entities(db, test_data):
    org, actor = test_data
    
    # 1. Patient Rollback
    p = Patient(org_id=org.id, full_name="Original Name", dob=None)
    p.patient_number = "PAT-001"
    db.add(p)
    db.flush()
    
    # Create version
    v = data_governance_service.create_data_version(db, actor, "patient", "PAT-001", {"full_name": "Original Name"})
    db.commit()
    
    # Modify
    p.full_name = "Modified Name"
    db.commit()
    
    # Rollback
    data_governance_service.rollback_to_version(db, actor, v.id)
    db.expire_all()
    assert p.full_name == "Original Name"

    # 2. Doctor Rollback
    d = Doctor(org_id=org.id, full_name="Original Doc", specialty="General")
    d.license_number = "LIC-001"
    db.add(d)
    db.flush()
    
    v2 = data_governance_service.create_data_version(db, actor, "doctor", "LIC-001", {"full_name": "Original Doc"})
    db.commit()
    
    d.full_name = "Modified Doc"
    db.commit()
    
    data_governance_service.rollback_to_version(db, actor, v2.id)
    db.expire_all()
    assert d.full_name == "Original Doc"

    # 3. Resource Application Rollback
    res = ResourceApplication(org_id=org.id, application_number="RES-001", resource_name="Res 1", quantity=10, applicant_id=actor.id)
    db.add(res)
    db.flush()
    
    v3 = data_governance_service.create_data_version(db, actor, "resource_application", "RES-001", {"resource_name": "Res 1", "quantity": 10})
    db.commit()
    
    res.resource_name = "Res Updated"
    db.commit()
    
    data_governance_service.rollback_to_version(db, actor, v3.id)
    db.expire_all()
    assert res.resource_name == "Res 1"

def test_validation_fail_closed(db, test_data):
    org, actor = test_data
    from app.models.entities import ImportBatch
    
    # Create batch record first
    batch = ImportBatch(batch_id="batch-123", org_id=org.id, source_name="test.json", status="pending")
    db.add(batch)
    batch2 = ImportBatch(batch_id="batch-456", org_id=org.id, source_name="test2.json", status="pending")
    db.add(batch2)
    db.commit()
    
    # Try validation with unknown entity_type
    result = data_governance_service.validate_records(db, actor, "batch-123", [{"any": "data"}], entity_type="unknown")
    assert result["status"] == "failed"
    assert "Unsupported" in result["detail"]
    
    # Try validation with known entity_type but bad data
    result2 = data_governance_service.validate_records(db, actor, "batch-456", [{"amount": -10, "expense_number": "EXP-1"}], entity_type="expense")
    assert result2["status"] == "failed"
    assert result2["issue_count"] > 0
def test_validation_within_batch_duplicates(db, test_data):
    org, actor = test_data
    from app.models.entities import ImportBatch
    
    batch = ImportBatch(batch_id="batch-dup", org_id=org.id, source_name="dup.json", status="pending")
    db.add(batch)
    db.commit()
    
    # Records with duplicate identifiers within the same batch
    records = [
        {"id": "rec1", "amount": 100, "expense_number": "EXP-DUP"},
        {"id": "rec2", "amount": 200, "expense_number": "EXP-DUP"}
    ]
    
    result = data_governance_service.validate_records(db, actor, "batch-dup", records, entity_type="expense")
    assert result["status"] == "failed"
    
    # Should have a 'batch_duplicate' issue
    from app.models.entities import DataValidationIssue
    issue = db.scalar(select(DataValidationIssue).where(
        DataValidationIssue.batch_id == "batch-dup",
        DataValidationIssue.issue_type == "batch_duplicate"
    ))
    assert issue is not None
    assert issue.field_name == "expense_number"
    assert "within this batch" in issue.message
