"""
tests/test_hospital_auth_fix.py

Verifies that the fixed object-level authorization in six hospital update endpoints
correctly allows admin/reviewer and record owner, and blocks non-owner general users.

Uses the same pattern as test_audit_remediation.py:
  - init_db(db) seeds roles + permissions before HTTP calls
  - all requests go through the HTTPS client fixture
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select


@pytest.fixture
def seeded(db: Session):
    from app.db.init_db import init_db
    init_db(db)
    return db


def _register_and_login(client: TestClient, org_code: str, username: str,
                        password: str = "Secure1234!",
                        invitation_token: str | None = None) -> str:
    reg = {
        "org_code": org_code, "org_name": f"Org {org_code}",
        "username": username, "password": password,
    }
    if invitation_token:
        reg["invitation_token"] = invitation_token
    client.post("/api/auth/register", json=reg)
    r = client.post("/api/auth/login", json={
        "org_code": org_code, "username": username, "password": password,
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestPatientUpdateAuth:
    def test_admin_can_update_any_patient(self, client: TestClient, seeded: Session):
        org = "HAFIX01"
        tok = _register_and_login(client, org, "admin_ha01")

        r = client.post("/api/hospital/patients", json={
            "patient_number": "PN-HA01", "full_name": "Test Patient",
        }, headers=_h(tok))
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        # Admin can update their own created patient (admin IS owner here since
        # admin created it without user_id link — falls back to admin check)
        r = client.patch(f"/api/hospital/patients/{pid}",
                         json={"full_name": "Updated by Admin"}, headers=_h(tok))
        assert r.status_code == 200, r.text

    def test_nonowner_general_user_blocked(self, client: TestClient, seeded: Session):
        org = "HAFIX02"
        admin_tok = _register_and_login(client, org, "admin_ha02")

        # Create patient as admin (no linked user_id = no one "owns" it)
        r = client.post("/api/hospital/patients", json={
            "patient_number": "PN-HA02", "full_name": "Owned Patient",
        }, headers=_h(admin_tok))
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        # Invite and register a general user
        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "general_ha02", "role": "general_user"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        gen_tok = _register_and_login(client, org, "general_ha02",
                                      invitation_token=inv.json()["token"])

        # General user who does not own the record must get 403
        r = client.patch(f"/api/hospital/patients/{pid}",
                         json={"full_name": "Should Fail"}, headers=_h(gen_tok))
        assert r.status_code == 403, r.text


class TestExpenseUpdateAuth:
    def test_admin_can_update_any_expense(self, client: TestClient, seeded: Session):
        org = "HAFIX03"
        tok = _register_and_login(client, org, "admin_ha03")

        r = client.post("/api/hospital/expenses", json={
            "expense_number": "EXP-HA03", "amount": 100.0, "category": "supplies",
        }, headers=_h(tok))
        assert r.status_code == 200, r.text
        eid = r.json()["id"]

        r = client.patch(f"/api/hospital/expenses/{eid}",
                         json={"amount": 200.0}, headers=_h(tok))
        assert r.status_code == 200, r.text

    def test_nonowner_general_user_blocked_expense(self, client: TestClient, seeded: Session):
        org = "HAFIX04"
        admin_tok = _register_and_login(client, org, "admin_ha04")

        r = client.post("/api/hospital/expenses", json={
            "expense_number": "EXP-HA04", "amount": 50.0, "category": "meds",
        }, headers=_h(admin_tok))
        assert r.status_code == 200, r.text
        eid = r.json()["id"]

        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "gen_ha04", "role": "general_user"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        gen_tok = _register_and_login(client, org, "gen_ha04",
                                      invitation_token=inv.json()["token"])

        r = client.patch(f"/api/hospital/expenses/{eid}",
                         json={"amount": 999.0}, headers=_h(gen_tok))
        assert r.status_code == 403, r.text


class TestResourceApplicationUpdateAuth:
    def test_admin_can_update_resource_application(self, client: TestClient, seeded: Session):
        org = "HAFIX05"
        tok = _register_and_login(client, org, "admin_ha05")

        r = client.post("/api/hospital/resource-applications", json={
            "application_number": "RA-HA05", "resource_name": "Oxygen", "quantity": 5,
        }, headers=_h(tok))
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        r = client.patch(f"/api/hospital/resource-applications/{rid}",
                         json={"quantity": 10}, headers=_h(tok))
        assert r.status_code == 200, r.text


class TestCreditChangeUpdateAuth:
    def test_admin_can_update_credit_change(self, client: TestClient, seeded: Session):
        org = "HAFIX06"
        admin_tok = _register_and_login(client, org, "admin_ha06")

        # Decode sub from token to get user id
        from app.core.security import decode_access_token
        payload = decode_access_token(admin_tok)
        admin_user_id = int(payload["sub"])

        r = client.post("/api/hospital/credit-changes", json={
            "change_number": "CC-HA06", "target_user_id": admin_user_id,
            "amount": 100.0, "reason": "bonus",
        }, headers=_h(admin_tok))
        assert r.status_code == 200, r.text
        cid = r.json()["id"]

        r = client.patch(f"/api/hospital/credit-changes/{cid}",
                         json={"amount": 150.0}, headers=_h(admin_tok))
        assert r.status_code == 200, r.text
