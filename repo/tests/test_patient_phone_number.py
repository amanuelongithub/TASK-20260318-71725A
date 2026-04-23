"""
tests/test_patient_phone_number.py

Verifies:
1. phone_number is encrypted and persisted on Patient create
2. phone_number is updated correctly on Patient update
3. phone_number is NOT exposed in the PatientOut API response
4. Admin-issued token password-recovery flow works end-to-end
5. Non-admin cannot call the issue-reset-token endpoint
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


def _register_and_login(client, org_code, username, password="Secure1234!",
                        invitation_token=None):
    reg = {"org_code": org_code, "org_name": f"Org {org_code}",
           "username": username, "password": password}
    if invitation_token:
        reg["invitation_token"] = invitation_token
    client.post("/api/auth/register", json=reg)
    r = client.post("/api/auth/login", json={
        "org_code": org_code, "username": username, "password": password,
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


class TestPatientPhoneNumber:
    def test_phone_number_persisted_on_create(self, client: TestClient, db: Session, seeded: Session):
        org = "PPHN01"
        tok = _register_and_login(client, org, "admin_pphn01")

        r = client.post("/api/hospital/patients", json={
            "patient_number": "PN-PH01",
            "full_name": "Phone Patient",
            "phone_number": "+251911000001",
        }, headers=_h(tok))
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        # Verify in DB that the encrypted blob is populated, and round-trip decrypts correctly
        from app.models.entities import Patient
        db.expire_all()
        patient = db.scalar(select(Patient).where(Patient.id == pid))
        assert patient is not None
        assert patient.phone_number_encrypted is not None, "phone_number_encrypted should be non-null"
        assert patient.phone_number == "+251911000001", "Decrypted phone_number should match input"

    def test_phone_number_not_exposed_in_response(self, client: TestClient, seeded: Session):
        org = "PPHN02"
        tok = _register_and_login(client, org, "admin_pphn02")

        r = client.post("/api/hospital/patients", json={
            "patient_number": "PN-PH02",
            "full_name": "Phone Patient 2",
            "phone_number": "+251922000002",
        }, headers=_h(tok))
        assert r.status_code == 200, r.text
        body = r.json()

        # PatientOut schema does not expose phone_number (it is PII - server-side only)
        assert "phone_number" not in body, (
            "phone_number MUST NOT appear in PatientOut API response"
        )
        assert "phone_number_encrypted" not in body, (
            "phone_number_encrypted MUST NOT appear in API response"
        )

    def test_phone_number_updated_on_patch(self, client: TestClient, db: Session, seeded: Session):
        org = "PPHN03"
        tok = _register_and_login(client, org, "admin_pphn03")

        r = client.post("/api/hospital/patients", json={
            "patient_number": "PN-PH03",
            "full_name": "Phone Patient 3",
            "phone_number": "+251933000003",
        }, headers=_h(tok))
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        r = client.patch(f"/api/hospital/patients/{pid}",
                         json={"phone_number": "+251944000004"}, headers=_h(tok))
        assert r.status_code == 200, r.text

        from app.models.entities import Patient
        db.expire_all()
        patient = db.scalar(select(Patient).where(Patient.id == pid))
        assert patient.phone_number == "+251944000004", (
            "phone_number should be updated to new value after PATCH"
        )


class TestAdminIssueResetToken:
    """End-to-end test: admin issues token, user uses it to complete password reset."""

    def test_admin_issue_and_user_confirm_reset(self, client: TestClient, seeded: Session):
        org = "PPHN04"
        admin_tok = _register_and_login(client, org, "admin_pphn04")

        # Register a second user via invitation
        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "user_pphn04", "role": "general_user"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        user_tok = _register_and_login(client, org, "user_pphn04",
                                       invitation_token=inv.json()["token"])

        # Admin issues a reset token for the user (the production recovery path)
        r = client.post("/api/auth/users/user_pphn04/issue-reset-token",
                        headers=_h(admin_tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "reset_token" in body, "Response must include reset_token"
        reset_token = body["reset_token"]
        assert len(reset_token) > 20, "Token should be a cryptographically strong string"

        # User uses the token to reset their password
        r = client.post("/api/auth/password-reset/confirm", json={
            "org_code": org,
            "token": reset_token,
            "new_password": "NewSecure9999!",
        })
        assert r.status_code == 200, r.text

        # User can now log in with the new password
        r = client.post("/api/auth/login", json={
            "org_code": org, "username": "user_pphn04", "password": "NewSecure9999!",
        })
        assert r.status_code == 200, r.text

    def test_non_admin_cannot_issue_reset_token(self, client: TestClient, seeded: Session):
        org = "PPHN05"
        admin_tok = _register_and_login(client, org, "admin_pphn05")

        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "gen_pphn05", "role": "general_user"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        gen_tok = _register_and_login(client, org, "gen_pphn05",
                                      invitation_token=inv.json()["token"])

        # general_user does not have org:update permission — must get 403
        r = client.post("/api/auth/users/admin_pphn05/issue-reset-token",
                        headers=_h(gen_tok))
        assert r.status_code == 403, r.text

    def test_reset_token_not_reusable(self, client: TestClient, seeded: Session):
        """A used reset token must be cleared; second confirm must fail."""
        org = "PPHN06"
        admin_tok = _register_and_login(client, org, "admin_pphn06")

        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "user_pphn06", "role": "general_user"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        _register_and_login(client, org, "user_pphn06",
                             invitation_token=inv.json()["token"])

        r = client.post("/api/auth/users/user_pphn06/issue-reset-token",
                        headers=_h(admin_tok))
        reset_token = r.json()["reset_token"]

        # First use — succeeds
        r1 = client.post("/api/auth/password-reset/confirm", json={
            "org_code": org, "token": reset_token, "new_password": "NewPass111!",
        })
        assert r1.status_code == 200, r1.text

        # Second use — must fail (token cleared after use)
        r2 = client.post("/api/auth/password-reset/confirm", json={
            "org_code": org, "token": reset_token, "new_password": "AnotherPass222!",
        })
        assert r2.status_code == 400, f"Expected 400 on token reuse, got {r2.status_code}"
