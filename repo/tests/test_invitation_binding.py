import pytest
import asyncio
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.services.auth_service import register
from app.schemas.auth import RegisterRequest
from app.models.entities import Organization, OrganizationInvitation, Role
from tests.utils import create_test_org
from app.core.security import deterministic_hash

def test_invitation_binding_email_match(db):
    from app.db.init_db import init_db
    init_db(db)
    org = create_test_org(db, "INVMAIL")
    role = db.query(Role).first()
    
    # Invitation for a specific email
    invite = OrganizationInvitation(
        org_id=org.id,
        email_or_username="target@example.com",
        role_id=role.id,
        token_hash=deterministic_hash("token1"),
        expires_at=datetime.utcnow() + timedelta(days=1),
        created_by=1
    )
    db.add(invite)
    db.commit()
    
    # 1. Mismatch email
    req_fail = RegisterRequest(
        username="user1",
        password="Password123!",
        full_name="User One",
        email="WRONG@example.com",
        org_code=org.org_code,
        org_name=org.name,
        invitation_token="token1" # token_hash matches find_invitation mock logic
    )
    
    # Mocking verify_password is fine if we want to skip hashing, 
    # but register doesn't even call it until AFTER our identity check.
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(register(db, req_fail))
    assert "Invitation is bound to a different email identity" in str(excinfo.value.detail)

def test_invitation_binding_username_match(db):
    from app.db.init_db import init_db
    init_db(db)
    org = create_test_org(db, "INVUSER")
    role = db.query(Role).first()
    
    # Invitation for a specific username
    invite = OrganizationInvitation(
        org_id=org.id,
        email_or_username="bounduser",
        role_id=role.id,
        token_hash=deterministic_hash("token2"),
        expires_at=datetime.utcnow() + timedelta(days=1),
        created_by=1
    )
    db.add(invite)
    db.commit()
    
    # mismatch username
    req_fail = RegisterRequest(
        username="wronguser",
        password="Password123!",
        full_name="Wrong User",
        org_code=org.org_code,
        org_name=org.name,
        invitation_token="token2"
    )
    
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(register(db, req_fail))
    assert "Invitation is bound to a different username identity" in str(excinfo.value.detail)

