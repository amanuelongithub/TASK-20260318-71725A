import pytest
from sqlalchemy import select, inspect
from app.models.entities import ProcessDefinition, MetricsSnapshot, Organization, User, Role, RoleType, OrganizationMembership, Task, ResourceApplication, CreditChange, RolePermission, ProcessInstance, ProcessStatus, TaskStatus
from app.tasks.jobs import aggregate_daily_metrics
from app.db.init_db import init_db
from app.core.security import create_access_token

def test_seeding_regression(db):
    # Setup: Run init_db
    init_db(db)
    
    # Verify definitions exist
    res_flow = db.scalar(select(ProcessDefinition).where(ProcessDefinition.name == "Resource Application Flow"))
    crd_flow = db.scalar(select(ProcessDefinition).where(ProcessDefinition.name == "Credit Change Flow"))
    
    assert res_flow is not None
    assert crd_flow is not None
    assert "submit" in res_flow.definition["nodes"]
    assert "data_entry" in crd_flow.definition["nodes"]

def test_metrics_task_functional(db):
    # Setup: org and user
    org = Organization(id=1, org_code="METRICS_ORG", name="Metrics Org")
    db.add(org)
    db.flush()
    
    # Run the task directly
    result = aggregate_daily_metrics(org.id, db)
    assert result is not None
    
    # Verify snapshot
    snapshot = db.scalar(select(MetricsSnapshot).where(MetricsSnapshot.org_id == org.id))
    assert snapshot is not None
    assert "attendance_anomaly_rate" in snapshot.payload
    assert isinstance(snapshot.payload["attendance_anomaly_rate"], float)

def test_e2e_resource_application_workflow(client, db):
    # Setup: Full environment
    init_db(db)
    org = db.scalar(select(Organization).limit(1))
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    
    user = User(username="e2e_user", hashed_password="...", org_id=org.id, role_id=admin_role.id)
    db.add(user)
    
    reviewer_role = db.scalar(select(Role).where(Role.name == RoleType.REVIEWER))
    reviewer = User(username="reviewer_user", hashed_password="...", org_id=org.id, role_id=reviewer_role.id)
    db.add(reviewer)
    
    db.flush()
    db.add(OrganizationMembership(user_id=user.id, org_id=org.id, role_id=admin_role.id))
    db.add(OrganizationMembership(user_id=reviewer.id, org_id=org.id, role_id=reviewer_role.id))
    db.commit()
    
    token = create_access_token(subject=str(user.id), org_id=org.id, roles=["administrator"])
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create a Resource Application via Public API
    resp = client.post("/api/hospital/resource-applications", json={
        "application_number": "RES-001",
        "resource_name": "Ventilator",
        "quantity": 5,
        "status": "pending"
    }, headers=headers)
    assert resp.status_code == 200
    res_app_id = resp.json()["id"]
    
    # 2. Define and Start Process (Manual to ensure no seed nesting issues)
    workflow_defn = {
        "first_node": "submit",
        "nodes": {
            "submit": {"timeout_hours": 24},
            "manager_review": {"timeout_hours": 48},
            "finance_approval": {"timeout_hours": 72}
        },
        "transitions": {
            "submit": {"approve": "manager_review"},
            "manager_review": {"approve": "finance_approval", "reject": "submit"},
            "finance_approval": {"approve": "completed", "reject": "manager_review"}
        },
        "assignees": {
            "manager_review": "role:administrator",
            "finance_approval": "role:administrator"
        }
    }
    defn = ProcessDefinition(org_id=org.id, name="Manual E2E Flow", definition=workflow_defn)
    db.add(defn)
    db.commit()
    
    resp = client.post("/api/process/instances", json={
        "process_definition_id": defn.id,
        "business_id": "RES-001",
        "idempotency_key": "IDEM-RES-001-MANUAL",
        "variables": {}
    }, headers=headers)
    assert resp.status_code == 200
    instance_id = resp.json()["id"]
    
    # 3. Verify Task creation and ID linkage (Regression Proof)
    db.expire_all()
    task = db.scalar(select(Task).where(Task.process_instance_id == instance_id))
    assert task is not None
    assert task.process_instance_id == instance_id
    
    # 4. Complete Tasks to trigger writeback
    # First node is 'submit', but in our seed the first node is actually 'submit' (wait, let's check seed)
    # Transitions: submit -> manager_review -> finance_approval -> completed
    
    # Complete 'submit'
    resp = client.post(f"/api/process/tasks/{task.id}/complete", json={"decision": "approve"}, headers=headers)
    assert resp.status_code == 200
    
    # Get next task (manager_review)
    db.expire_all()
    tasks = db.scalars(select(Task).where(Task.process_instance_id == instance_id, Task.status == TaskStatus.PENDING)).all()
    task2 = next((t for t in tasks if t.node_key == "manager_review"), None)
    assert task2 is not None, f"Manager review task not found. Available nodes: {[t.node_key for t in tasks]}"
    resp = client.post(f"/api/process/tasks/{task2.id}/complete", json={"decision": "approve"}, headers=headers)
    assert resp.status_code == 200
    
    # Get next task (finance_approval)
    db.expire_all()
    tasks = db.scalars(select(Task).where(Task.process_instance_id == instance_id, Task.status == TaskStatus.PENDING)).all()
    task3 = next((t for t in tasks if t.node_key == "finance_approval"), None)
    assert task3 is not None
    resp = client.post(f"/api/process/tasks/{task3.id}/complete", json={"decision": "approve"}, headers=headers)
    assert resp.status_code == 200
    
    # 5. Verify Writeback via Search API (End-to-End)
    db.expire_all()
    resp = client.get(f"/api/hospital/resource-applications?status=approved", headers=headers)
    assert resp.status_code == 200
    results = resp.json() # The endpoint returns list[ResourceApplicationOut]
    assert any(r["application_number"] == "RES-001" and r["status"] == "approved" for r in results)

def test_index_and_constraint_validation(db):
    inspector = inspect(db.bind)
    
    for table_name in ["resource_applications", "credit_changes"]:
        indexes = inspector.get_indexes(table_name)
        # SQLite might name unique indexes differently or hide them in unique constraints list
        uniques = inspector.get_unique_constraints(table_name)
        
        # Check for status index (explicitly added as index=True)
        assert any("status" in idx["column_names"] for idx in indexes), f"No index on status for {table_name}"
        # Check for created_at index (explicitly added as index=True)
        assert any("created_at" in idx["column_names"] for idx in indexes), f"No index on created_at for {table_name}"
        
        # Check for unique business number constraint
        all_cols = []
        for uq in uniques: all_cols.extend(uq["column_names"])
        for idx in indexes: 
            if idx.get("unique"): all_cols.extend(idx["column_names"])
            
        has_business_num_uq = any(col in all_cols for col in ["application_number", "change_number"])
        has_org_id_uq = "org_id" in all_cols
        assert has_business_num_uq and has_org_id_uq, f"Missing unique constraint on business number/org_id for {table_name}"

def test_https_enforcement_regression(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "allow_plain_http", False)
    
    # Use a fresh client without the X-Forwarded-Proto header from the fixture
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        # This should fail now without the exemption and without the bypass
        response = c.get("/health")
        assert response.status_code == 403
    
    # Sanity check: if we explicitly pass a different scheme, it should still fail or be handled
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        monkeypatch.setattr(settings, "allow_plain_http", False)
        resp = c.get("/health")
        # Middleware checks x-forwarded-proto first. If missing, it checks request.url.scheme.
        # TestClient defaults to http.
        assert resp.status_code == 403
