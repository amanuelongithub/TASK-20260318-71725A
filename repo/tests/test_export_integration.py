import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ExportJob, User, Organization, Role, RoleType, AuditLog
from app.tasks.jobs import process_export_job
from app.db.session import SessionLocal

@pytest.fixture
def db_session():
    session = SessionLocal()
    # In a real integration test, we might want to use a separate test DB
    # or a transaction that rolls back. For now, we'll try to use the current DB
    # but we must be careful with cleanup.
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def setup_data(db_session: Session):
    # Ensure role exists
    admin_role = db_session.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if not admin_role:
        admin_role = Role(name=RoleType.ADMIN)
        db_session.add(admin_role)
        db_session.commit()
    
    # Ensure org exists
    org = db_session.scalar(select(Organization).where(Organization.org_code == "test_org"))
    if not org:
        org = Organization(org_code="test_org", name="Test Org")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)
    
    # Ensure user exists
    user = db_session.scalar(select(User).where(User.username == "test_admin", User.org_id == org.id))
    if not user:
        user = User(
            org_id=org.id,
            role_id=admin_role.id,
            username="test_admin",
            hashed_password="fake",
            is_active=True
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    
    return org, user

def test_process_export_job_lifecycle_completed(db_session: Session, setup_data, tmp_path):
    org, user = setup_data
    
    # 1. Create a job in 'queued' state
    job = ExportJob(
        org_id=org.id,
        requested_by=user.id,
        fields={"columns": ["username", "org_id"], "format": "csv", "desensitize": False},
        status="queued"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    
    job_id = job.id
    
    # 2. Run the task
    # We patch settings to use our tmp_path for storage
    with patch("app.tasks.jobs.settings") as mock_settings:
        mock_settings.file_storage_path = str(tmp_path)
        # We also need to patch generate_user_export_csv to avoid real file Ops if we want, 
        # but here we actually WANT to test the integration.
        
        # We need to patch SessionLocal in jobs.py to use our session (or just let it use its own)
        # Using its own is more 'integration-y' but harder to cleanup.
        # For this test, we'll let it use its own and then verify in our session.
        
        process_export_job.apply(args=[job_id])
    
    # 3. Verify status and audit log
    db_session.expire_all()
    job = db_session.get(ExportJob, job_id)
    assert job.status == "completed"
    assert job.output_path is not None
    assert Path(job.output_path).exists()
    
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.event == "export.job_completed", AuditLog.org_id == org.id)
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.event_metadata["job_id"] == job_id

def test_process_export_job_lifecycle_failed(db_session: Session, setup_data):
    org, user = setup_data
    
    # 1. Create a job that will fail (e.g. invalid columns)
    job = ExportJob(
        org_id=org.id,
        requested_by=user.id,
        fields={"columns": None, "format": "csv"}, # This should cause error in _collect_rows
        status="queued"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    
    job_id = job.id
    
    # 2. Run the task (it will retry and eventually fail, but we can catch the exception)
    # Since we use .apply(), it runs synchronously.
    # Note: process_export_job has retry logic, we might need to handle it.
    
    with patch("app.tasks.jobs.generate_user_export_csv", side_effect=Exception("Simulated failure")):
        try:
            process_export_job.apply(args=[job_id])
        except Exception:
            pass
            
    # 3. Verify status and audit log
    db_session.expire_all()
    job = db_session.get(ExportJob, job_id)
    assert job.status == "failed"
    
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.event == "export.job_failed", AuditLog.org_id == org.id)
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.event_metadata["job_id"] == job_id
    assert "Simulated failure" in audit.event_metadata["error"]
