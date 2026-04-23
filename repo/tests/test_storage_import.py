import pytest
from io import BytesIO
from fastapi import UploadFile
from starlette.datastructures import Headers
from sqlalchemy import select
from app.models.entities import Organization, User, Role, RoleType, OrganizationMembership, ImportBatch
from app.services import storage_service

@pytest.fixture
def test_setup(db):
    from app.db.init_db import init_db
    init_db(db)
    org = db.scalar(select(Organization).limit(1))
    admin_role = db.scalar(select(Role).where(Role.name == RoleType.ADMIN))
    user = User(org_id=org.id, role_id=admin_role.id, username="storage_admin", hashed_password="...")
    db.add(user)
    db.flush()
    db.add(OrganizationMembership(user_id=user.id, org_id=org.id, role_id=admin_role.id, is_active=True))
    db.commit()
    return org, user

@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_save_attachment_import_derivation(db, test_setup, anyio_backend):
    org, actor = test_setup
    
    class MockUploadFile(UploadFile):
        def __init__(self, filename, file, content_type):
            super().__init__(filename=filename, file=file)
            self._content_type = content_type
        @property
        def content_type(self):
            return self._content_type

    # 1. Successful derivation from business_owner_id prefix
    from app.models.entities import Expense
    exp = Expense(org_id=org.id, expense_number="EXP-001", amount=50, category="Test", submitted_by=actor.id)
    db.add(exp)
    db.commit()

    content = b'[{"expense_number": "EXP-001", "amount": 100, "category": "Travel"}]'
    upload = MockUploadFile(filename="batch_expenses.json", file=BytesIO(content), content_type="application/json")
    
    result = await storage_service.save_attachment(
        db, actor, upload, business_owner_id="EXP-001"
    )
    assert result["validation_status"] == "validated"
    
    # Verify ImportBatch exists
    batch = db.scalar(select(ImportBatch).order_by(ImportBatch.created_at.desc()))
    assert batch is not None
    assert batch.status == "validated"

    # 2. Explicit entity_type provided
    content2 = b'[{"application_number": "RES-002", "resource_name": "Masks", "quantity": 500}]'
    upload2 = MockUploadFile(filename="batch_res.json", file=BytesIO(content2), content_type="application/json")
    
    result2 = await storage_service.save_attachment(
        db, actor, upload2, entity_type="resource_application"
    )
    assert result2["validation_status"] == "validated"

    # 3. Fail closed on unknown derivation
    from app.models.entities import ProcessInstance
    proc = ProcessInstance(org_id=org.id, business_id="PROC-1", process_definition_id=1, initiator_id=actor.id, idempotency_key="ik-1")
    db.add(proc)
    db.commit()

    content3 = b'[{"something": "else"}]'
    upload3 = MockUploadFile(filename="batch_unknown.json", file=BytesIO(content3), content_type="application/json")
    
    result3 = await storage_service.save_attachment(
        db, actor, upload3, business_owner_id="PROC-1"
    )
    assert result3["validation_status"] == "failed"
