"""
tests/test_audit_desensitization.py

Verifies that audit log responses apply role-aware metadata desensitization:
- ADMIN: full metadata including raw usernames
- AUDITOR: event visible, sensitive metadata keys masked
- REVIEWER / GENERAL_USER: no access to audit:read (403)
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


class TestAuditDesensitization:
    def test_admin_sees_full_metadata(self, client: TestClient, seeded: Session):
        org = "AUDS01"
        admin_tok = _register_and_login(client, org, "admin_auds01")

        # Login generates audit events; now read them back
        r = client.get("/api/audit/logs", headers=_h(admin_tok))
        assert r.status_code == 200, r.text
        logs = r.json()
        assert len(logs) > 0, "Expected at least one audit log entry"
        # Admin should receive raw metadata dict (not None)
        assert logs[0]["metadata"] is not None, "Admin should see full metadata"

    def test_auditor_sees_sanitized_metadata(self, client: TestClient, seeded: Session):
        org = "AUDS02"
        admin_tok = _register_and_login(client, org, "admin_auds02")

        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "auditor_auds02", "role": "auditor"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        auditor_tok = _register_and_login(client, org, "auditor_auds02",
                                          invitation_token=inv.json()["token"])

        r = client.get("/api/audit/logs", headers=_h(auditor_tok))
        assert r.status_code == 200, r.text
        logs = r.json()
        assert len(logs) > 0

        # Sensitive keys like 'username' must be masked for auditor
        for log in logs:
            meta = log.get("metadata")
            if meta and "username" in meta:
                val = meta["username"]
                assert "*" in val, (
                    f"Expected username to be masked for auditor, got: {val!r}"
                )

    def test_general_user_cannot_read_audit_logs(self, client: TestClient, seeded: Session):
        org = "AUDS03"
        admin_tok = _register_and_login(client, org, "admin_auds03")

        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "gen_auds03", "role": "general_user"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        gen_tok = _register_and_login(client, org, "gen_auds03",
                                      invitation_token=inv.json()["token"])

        # general_user does NOT have audit:read — must get 403
        r = client.get("/api/audit/logs", headers=_h(gen_tok))
        assert r.status_code == 403, (
            f"Expected 403 for general_user on audit logs, got {r.status_code}: {r.text}"
        )

    def test_reviewer_cannot_read_audit_logs(self, client: TestClient, seeded: Session):
        org = "AUDS04"
        admin_tok = _register_and_login(client, org, "admin_auds04")

        inv = client.post("/api/auth/invitations",
                          json={"email_or_username": "rev_auds04", "role": "reviewer"},
                          headers=_h(admin_tok))
        assert inv.status_code == 200, inv.text
        rev_tok = _register_and_login(client, org, "rev_auds04",
                                      invitation_token=inv.json()["token"])

        # reviewer does NOT have audit:read — must get 403
        r = client.get("/api/audit/logs", headers=_h(rev_tok))
        assert r.status_code == 403, (
            f"Expected 403 for reviewer on audit logs, got {r.status_code}: {r.text}"
        )
