import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ExportJob, User, Organization, Role, RoleType, AuditLog
from app.tasks.jobs import process_export_job
from app.db.session import SessionLocal

@pytest.fixture
def setup_data(db: Session):
    # Ensure role exists
    from app.models.entities import Role, RoleType, Organization, User
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if not admin_role:
        admin_role = Role(name=RoleType.ADMIN)
        db.add(admin_role)
        db.flush()
    
    # Ensure org exists
    org = db.scalar(select(Organization).where(Organization.org_code == "test_org"))
    if not org:
        org = Organization(org_code="test_org", name="Test Org")
        db.add(org)
        db.flush()
        db.refresh(org)
    
    # Ensure user exists
    user = db.scalar(select(User).where(User.username == "test_admin", User.org_id == org.id))
    if not user:
        user = User(
            org_id=org.id,
            role_id=admin_role.id,
            username="test_admin",
            hashed_password="fake",
            is_active=True
        )
        db.add(user)
        db.flush()
        db.refresh(user)
        from app.models.entities import OrganizationMembership
        db.add(OrganizationMembership(user_id=user.id, org_id=org.id, role_id=admin_role.id, is_active=True))
        db.flush()
    
    return org, user

def test_process_export_job_lifecycle_completed(db: Session, setup_data, tmp_path):
    org, user = setup_data
    
    # 1. Create a job in 'queued' state
    job = ExportJob(
        org_id=org.id,
        requested_by=user.id,
        fields={"columns": ["username", "org_id"], "format": "csv", "desensitize": False},
        status="queued"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    job_id = job.id
    
    # 2. Run the task
    with patch("app.tasks.jobs.settings") as mock_settings:
        with patch("app.tasks.jobs.SessionLocal", return_value=db):
            with patch.object(db, "close", MagicMock()): 
                mock_settings.file_storage_path = str(tmp_path)
                process_export_job.apply(args=[job_id])
    
    # 3. Verify status and audit log
    db.expire_all()
    job = db.get(ExportJob, job_id)
    assert job.status == "completed"
    assert job.output_path is not None
    assert Path(job.output_path).exists()
    
    audit = db.scalar(
        select(AuditLog).where(AuditLog.event == "export.job_completed", AuditLog.org_id == org.id)
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.event_metadata["job_id"] == job_id

def test_process_export_job_lifecycle_failed(db: Session, setup_data):
    org, user = setup_data
    
    # 1. Create a job that will fail (e.g. invalid columns)
    job = ExportJob(
        org_id=org.id,
        requested_by=user.id,
        fields={"columns": None, "format": "csv"},
        status="queued"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    job_id = job.id
    
    # 2. Run the task
    with patch("app.tasks.jobs.SessionLocal", return_value=db):
        with patch.object(db, "close", MagicMock()):
            with patch("app.services.export_service.generate_export_csv", side_effect=Exception("Simulated failure")):
                try:
                    process_export_job.apply(args=[job_id])
                except Exception:
                    pass
            
    # 3. Verify status and audit log
    db.expire_all()
    job = db.get(ExportJob, job_id)
    assert job.status == "failed"
    
    audit = db.scalar(
        select(AuditLog).where(AuditLog.event == "export.job_failed", AuditLog.org_id == org.id)
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.event_metadata["job_id"] == job_id
    assert "Export generation failed due to an internal error." in audit.event_metadata["error"]
