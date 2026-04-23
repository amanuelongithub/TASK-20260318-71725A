# Medical Operations and Process Governance Middle Platform API

Expanded implementation baseline for your full plan.

## Implemented
- FastAPI layered architecture with domain/service/api separation
- SQLAlchemy models for identity, RBAC, workflow, exports, metrics, audit, data governance, attachments
- JWT auth, password hashing, lockout policy, org-level isolation
- Field encryption utility and SHA256 fingerprint deduplication
- Permission middleware driven by role-permission mappings
- Workflow APIs: create definition, start instance with idempotency keys, complete task
- Transition evaluator supports conditional branches and multi-node next steps
- Data governance APIs: versioning, validation, rollback lookup
- Export/audit/metrics APIs with permission checks
- CSV export generation with optional field desensitization
- Celery workers for daily metrics and SLA monitoring
- Alembic setup with multi-phase remediation migrations
- Docker compose for hardened production-ready deployment

## Security & Audit Compliance (Remediated & Verified)

| Audit Goal | Implementation Detail | Verification Path |
|:---|:---|:---|
| **Alembic Integrity** | Disconnected branches merged into single head `20260422_09`. | `alembic heads` |
| **Tenant Membership** | Authorization truth moved to `OrganizationMembership`; `User.org_id` denotes home org only. | `app/services/auth_service.py` |
| **HTTPS Enforcement** | Strict HTTPS middleware; plain HTTP requests are rejected in every environment unless already TLS-terminated and forwarded as HTTPS. | `app/main.py:22` |
| **Invitation Security** | Invitation tokens strictly bound to registrant `username` or `email` identity. | `app/services/auth_service.py:45` |
| **File Hardening** | Magic-number content signature validation (PDF, PNG, JPEG, JSON). | `app/services/storage_service.py` |
| **Audit Traceability** | ID persistence (flush) guaranteed before audit log generation. | `app/services/storage_service.py` |
| **Secret Protection** | Committed TLS keys removed; `.gitignore` hardened for secrets/certs. | `.gitignore` |

## Hardened Deployment
1. Generate unique production certificates:
   ```bash
   python scripts/generate_certs.py
   ```
   (Outputs `server.crt` and `server.key` to `deploy/certs/`)
2. Start the full hardened stack:
   ```bash
   docker-compose up -d
   ```
   (Stacks Nginx with TLS termination and enforced 301 redirects)

## Run locally (Development)
1. Copy `.env.example` to `.env`
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start backing services: `docker-compose up -d db redis`
4. Apply migrations: `PYTHONPATH=. alembic upgrade head`
5. Seed initial data (RBAC, Dictionary): `python -m app.db.init_db`
6. Run the API behind TLS:
   ```bash
   python scripts/generate_certs.py
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-certfile deploy/certs/server.crt --ssl-keyfile deploy/certs/server.key
   ```
   Alternatively, proxy local traffic through the included Nginx TLS terminator.

## Metrics Semantics
- **Work Order SLA**: % of tasks completed before their `sla_due_at`.
- **Message Reach**: % of unique organization users (membership-based) who performed an action.
- **Attendance Anomalies**: Ratio of overdue pending tasks per active member count.

## Verification Suite
Run the full validation suite to ensure audit compliance:
```bash
pytest
```
Individual critical tests:
- `tests/test_audit_remediation.py` (Tenant Membership, HTTPS, Magic Numbers, Lockout)
- `tests/test_data_governance.py` (Rollback for 6 entities, Fail-Closed Validation)
- `tests/test_idempotency_concurrency.py` (Persistence-layer 24h triggers)
- `tests/test_health.py` (HTTPS-only health check)

The test suite bootstraps a temporary SQLite schema from the current models and installs SQLite parity triggers for persistence-level safeguards such as the 24-hour idempotency rule.

## Operational Reliability
- **Idempotency**: 24-hour window enforced at the service layer AND persistence layer via DB triggers.
- **Membership Identity**: Global users with context-bound memberships.
- **Lockout Policy**: 5 failed attempts in 10 minutes results in a 30-minute account lockout.
