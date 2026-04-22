import pytest
from sqlalchemy import select
from app.models.entities import Organization, User, Role, RoleType, ProcessInstance, ProcessStatus, Task, TaskStatus, Expense, Appointment
from app.core.security import create_access_token

def test_tenant_isolation_hospital_data(client, db):
    # Setup two organizations
    org1 = Organization(org_code="T1", name="Tenant 1")
    org2 = Organization(org_code="T2", name="Tenant 2")
    db.add_all([org1, org2])
    db.flush()
    
    role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    if not role:
        role = Role(name=RoleType.ADMIN)
        db.add(role)
        db.flush()
        
    u1 = User(username="admin_t1", hashed_password="...", org_id=org1.id, role_id=role.id, is_active=True)
    u2 = User(username="admin_t2", hashed_password="...", org_id=org2.id, role_id=role.id, is_active=True)
    db.add_all([u1, u2])
    db.flush()
    
    # Org 1 data
    exp1 = Expense(org_id=org1.id, expense_number="EXP-T1", amount=100.0, category="Medical", submitted_by=u1.id)
    db.add(exp1)
    # Org 2 data
    exp2 = Expense(org_id=org2.id, expense_number="EXP-T2", amount=200.0, category="Medical", submitted_by=u2.id)
    db.add(exp2)
    db.commit()
    
    # Verify u1 cannot see exp2
    token1 = create_access_token(subject=str(u1.id), org_id=org1.id, roles=["administrator"])
    headers1 = {"Authorization": f"Bearer {token1}", "X-Forwarded-Proto": "https"}
    
    response = client.get("/api/hospital/expenses", headers=headers1)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["expense_number"] == "EXP-T1"
    assert "EXP-T2" not in [e["expense_number"] for e in data]

def test_rbac_auditor_read_only(client, db):
    org = Organization(org_code="AUDIT_ORG", name="Audit Org")
    db.add(org)
    db.flush()
    
    auditor_role = db.scalar(select(Role).where(Role.name == RoleType.AUDITOR))
    if not auditor_role:
        auditor_role = Role(name=RoleType.AUDITOR)
        db.add(auditor_role)
        db.flush()
        
    auditor = User(username="auditor1", hashed_password="...", org_id=org.id, role_id=auditor_role.id, is_active=True)
    db.add(auditor)
    db.commit()
    
    token = create_access_token(subject=str(auditor.id), org_id=org.id, roles=["auditor"])
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-Proto": "https"}
    
    # Auditor should be able to read audit logs (if seeds exist, but here we check status code)
    response_read = client.get("/api/audit/logs", headers=headers)
    assert response_read.status_code in {200, 404} # 404 if no logs, but not 403
    
    # Auditor should NOT be able to create a process definition
    payload = {"name": "Audit Test", "definition": {}}
    response_write = client.post("/api/process/definitions", json=payload, headers=headers)
    assert response_write.status_code == 403

def test_workflow_full_chain_writeback(client, db):
    from datetime import datetime
    org = Organization(org_code="WORKFLOW_ORG", name="Workflow Org")
    db.add(org)
    db.flush()
    
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    admin = User(username="workflow_admin", hashed_password="...", org_id=org.id, role_id=admin_role.id, is_active=True)
    db.add(admin)
    db.flush()
    
    # Create an expense to be approved
    expense = Expense(org_id=org.id, expense_number="EXP-WF-1", amount=500.0, category="Travel", submitted_by=admin.id, status="pending")
    db.add(expense)
    db.flush()
    
    # Mock a process instance and task for this expense
    instance = ProcessInstance(
        org_id=org.id, process_definition_id=1, initiator_id=admin.id, 
        business_id="EXP-WF-1", status="running", idempotency_key="key1"
    )
    db.add(instance)
    db.flush()
    
    task = Task(org_id=org.id, process_instance_id=instance.id, assignee_id=admin.id, node_key="review", status="pending")
    db.add(task)
    db.commit()
    
    token = create_access_token(subject=str(admin.id), org_id=org.id, roles=["administrator"])
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-Proto": "https"}
    
    # Complete the task with 'approve'
    response = client.post(f"/api/process/tasks/{task.id}/complete", json={"decision": "approve", "comment": "Verified"}, headers=headers)
    assert response.status_code == 200
    
    # Verify full-chain writeback
    db.expire_all()
    updated_expense = db.scalar(select(Expense).where(Expense.id == expense.id))
    assert updated_expense.status == "approved"
    assert updated_expense.approved_at is not None
    
    updated_instance = db.scalar(select(ProcessInstance).where(ProcessInstance.id == instance.id))
    assert updated_instance.status == "completed"
    assert updated_instance.completed_at is not None
    
    # Verify specialized audit event
    from app.models.entities import AuditLog
    audit = db.scalar(select(AuditLog).where(AuditLog.event == "hospital.expense_writeback", AuditLog.org_id == org.id))
    assert audit is not None
    assert audit.event_metadata["business_id"] == "EXP-WF-1"
