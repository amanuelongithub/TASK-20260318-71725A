import pytest
import sqlalchemy as sa
from datetime import datetime, timedelta
from sqlalchemy import select
from app.models.entities import ProcessInstance, ProcessDefinition, Organization
from app.services.process_service import start_process
from tests.utils import create_test_user

def test_persistence_layer_idempotency_trigger(db):
    # Seed roles
    from app.db.init_db import init_db
    init_db(db)
    
    # MANUALLY APPLY TRIGGER FOR TEST (since Base.metadata.create_all doesn't create triggers)
    db.execute(sa.text("""
        CREATE TRIGGER IF NOT EXISTS validate_process_idempotency_sqlite_24h
        BEFORE INSERT ON process_instances
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'Persistence-layer violation: Duplicate business_id or idempotency_key within 24-hour window')
            WHERE EXISTS (
                SELECT 1 FROM process_instances
                WHERE org_id = NEW.org_id
                  AND (business_id = NEW.business_id OR idempotency_key = NEW.idempotency_key)
                  AND created_at >= datetime('now', '-24 hours')
            );
        END;
    """))
    db.commit()

    # Setup
    org = Organization(org_code="TESTIDEM", name="Idempotency Org")
    db.add(org)
    db.commit()
    
    user = create_test_user(db, org.id)
    
    defn = ProcessDefinition(org_id=org.id, name="Test Proc", definition={"nodes": {"start": {}}, "start_node": "start"})
    db.add(defn)
    db.commit()

    business_id = "BUS-1"
    
    # 1. First submission
    p1 = start_process(db, user, defn.id, business_id=business_id, idempotency_key="key-1")
    assert p1.business_id == business_id
    
    # 2. Duplicate submission (should hit service-layer check first)
    p2 = start_process(db, user, defn.id, business_id=business_id, idempotency_key="key-1")
    assert p2.id == p1.id
    
    # 3. Simulate race condition or service bypass hitting the trigger
    # We'll manually insert a row that violates the trigger
    from sqlalchemy.exc import DBAPIError, SQLAlchemyError
    
    # This direct insert bypasses the service check but should hit the DB TRIGGER
    # SQLite gives IntegrityError: 'Persistence-layer violation...'
    with pytest.raises(Exception) as excinfo:
        db.execute(
            sa.insert(ProcessInstance).values(
                org_id=org.id,
                process_definition_id=defn.id,
                initiator_id=user.id,
                business_id=business_id,
                idempotency_key="diff-key", # different key but same business_id
                created_at=datetime.utcnow()
            )
        )
        db.commit()
    assert "Persistence-layer violation" in str(excinfo.value) or "duplicate_idempotency_24h" in str(excinfo.value)
    db.rollback()

def test_after_24_hours_allowed(db):
    org = Organization(org_code="TESTTIME", name="Time Org")
    db.add(org)
    db.commit()
    user = create_test_user(db, org.id)
    defn = ProcessDefinition(org_id=org.id, name="Test Proc", definition={"nodes": {"start": {}}, "start_node": "start"})
    db.add(defn)
    db.commit()

    business_id = "BUS-TIME"
    
    # Create one record 25 hours ago
    past_instance = ProcessInstance(
        org_id=org.id,
        process_definition_id=defn.id,
        initiator_id=user.id,
        business_id=business_id,
        idempotency_key="key-old",
        created_at=datetime.utcnow() - timedelta(hours=25)
    )
    db.add(past_instance)
    db.commit()
    
    # Now start a new one with same business_id - SHOULD BE ALLOWED (trigger window passed)
    p_new = start_process(db, user, defn.id, business_id=business_id, idempotency_key="key-new")
    assert p_new.id != past_instance.id
    assert p_new.business_id == business_id

